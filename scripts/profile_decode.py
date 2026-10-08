#!/usr/bin/env python3
"""profile_decode.py — where a decode step's time goes, as evidence for fusions and other levers.

    profile_decode.py --build-dir <build_hip> --out <dir> [--concurrency 1,8] [--tokens 256]

Uses the engine's own instruments and their reading rules (libr4d/isa/README.md, AGENTS.md §5):
libr4d/isa/trace.sh runs the engine under rocprofv3's kernel trace, libr4d/isa/tsum.sh and gaps.sh
summarise it. Per concurrency level:

  1. untraced engine (scripts/start_engine.sh, the gate's configuration): one greedy chat request
     per stream with ignore_eos, decode time from the streamed tokens
  2. traced engine, the same requests the moment it answers (trace.sh: an idle server's trace goes
     quiet), then SIGTERM to bin/radiance only so rocprofv3 can finalise
  3. steady-state window keyed on the sampler marker that fires once per decode step (tsum.sh's
     method), per rank: busy time as a union, gaps attributed to the kernel that follows them

Reading rules carried into the report: kernel durations are hardware timestamps and real; gaps
absorb the tracer's per-dispatch cost and are an UPPER BOUND. The tracer's cost per dispatch is
calibrated from the same greedy request traced and untraced (identical tokens, so identical
steps): overhead_us = (traced ms/step - untraced ms/step) / dispatches per rank per step.

Output in --out: PROFILE.md (for people and agents), summary.json, tsum_c<N>.txt, gaps_c<N>.txt,
the traces (gzipped) and engine logs. The GPUs must be free; the lever queue runs this.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
import ab_gate  # noqa: E402  (Engine, process checks: the gate's own way of starting and stopping)

ISA = REPO_ROOT / "libr4d" / "isa"
MARKER = os.environ.get("PROFILE_MARKER", "r4d_rowtopk_stage1")  # tsum.sh's once-per-decode-step kernel
PROMPT = ("Schreibe einen ausführlichen technischen Aufsatz über die Geschichte des Buchdrucks, "
          "mit Abschnitten zu Technik, Wirtschaft und Folgen für die Wissenschaft.")
SMALL_KERNEL_US = 10.0   # below this a dispatch is mostly launch floor: first thing a fusion removes
PORT = 8190


# ---------------------------------------------------------------- workload

def chat_stream(port: int, max_tokens: int, tag: str) -> dict[str, Any]:
    body = {"model": "m", "messages": [{"role": "user", "content": f"{PROMPT} ({tag})"}],
            "max_tokens": max_tokens, "temperature": 0, "ignore_eos": True, "stream": True,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    first = None
    usage = None
    with urllib.request.urlopen(req, timeout=1800) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            ev = json.loads(line[5:])
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices", []):
                delta = ch.get("delta", {})
                if first is None and (delta.get("content") or delta.get("reasoning_content")):
                    first = time.time()
    t1 = time.time()
    if usage is None or first is None:
        raise RuntimeError("stream without usage or without any token; cannot time the decode")
    return {"t_start": t0, "t_first": first, "t_end": t1, "completion_tokens": usage["completion_tokens"]}


def drive(port: int, streams: int, max_tokens: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = [None] * streams  # type: ignore[list-item]
    errors: list[str] = []

    def one(i: int) -> None:
        try:
            results[i] = chat_stream(port, max_tokens, f"s{i}")
        except Exception as e:  # noqa: BLE001 - reported below, never swallowed
            errors.append(f"stream {i}: {e}")

    threads = [threading.Thread(target=one, args=(i,)) for i in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise RuntimeError("; ".join(errors))
    decode_s = max(r["t_end"] for r in results) - max(r["t_first"] for r in results)
    tokens = sum(r["completion_tokens"] for r in results)
    return {"streams": streams, "tokens": tokens, "decode_s": round(decode_s, 4),
            "decode_tps": round(tokens / decode_s, 2) if decode_s > 0 else None,
            "ttft_s": round(statistics.median(r["t_first"] - r["t_start"] for r in results), 4)}


# ---------------------------------------------------------------- engines

class TracedEngine:
    """scripts/start_engine.sh under libr4d/isa/trace.sh; stops bin/radiance with SIGTERM only."""

    def __init__(self, build_dir: Path, port: int, trace_dir: Path, log_path: Path):
        self.build_dir, self.port, self.trace_dir, self.log_path = build_dir.resolve(), port, trace_dir, log_path
        self.proc: subprocess.Popen | None = None

    def start(self, timeout_s: int) -> None:
        cmd = ["sh", str(ISA / "trace.sh"), str(self.trace_dir), "--",
               "bash", str(SCRIPT_DIR / "start_engine.sh"), "--build-dir", str(self.build_dir), "--port", str(self.port)]
        self.proc = subprocess.Popen(cmd, stdout=self.log_path.open("w"), stderr=subprocess.STDOUT,
                                     start_new_session=True)
        t0 = time.time()
        while not ab_gate.endpoint_up(self.port):
            if self.proc.poll() is not None:
                raise RuntimeError(f"traced engine exited during startup (rc={self.proc.returncode}), see {self.log_path}")
            if time.time() - t0 > timeout_s:
                self.kill()
                raise RuntimeError(f"traced engine not ready after {timeout_s}s, see {self.log_path}")
            time.sleep(1)

    def ours(self) -> list[int]:
        return [pid for pid, _exe, pgid in ab_gate.radiance_processes() if self.proc and pgid == self.proc.pid]

    def stop(self) -> Path:
        """SIGTERM to the server so rocprofv3 finalises (a SIGKILL leaves no trace at all)."""
        for pid in self.ours():
            os.kill(pid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=180)
        except subprocess.TimeoutExpired:
            self.kill()
            raise RuntimeError("traced engine did not finalise within 180 s; trace discarded")
        csv_path = self.trace_dir / "k_kernel_trace.csv"
        if not csv_path.is_file():
            raise RuntimeError(f"no trace written, see {self.log_path}")
        return csv_path

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=30)


# ---------------------------------------------------------------- trace analysis (tsum.sh's method)

def norm_name(n: str) -> str:
    n = n.replace("(anonymous namespace)::", "")
    n = re.sub(r"^void ", "", n)
    n = re.sub(r"\(.*$", "", n)
    return n.replace(" ", "")


def read_trace(path: Path) -> list[tuple[str, int, int, str]]:
    """(agent, start_ns, end_ns, kernel) for every KERNEL_DISPATCH row."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        need = {"Kind", "Agent_Id", "Kernel_Name", "Start_Timestamp", "End_Timestamp"}
        missing = need - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"trace {path} lacks columns {sorted(missing)}; rocprofv3 format changed?")
        for r in reader:
            if r["Kind"] == "KERNEL_DISPATCH":
                rows.append((r["Agent_Id"], int(r["Start_Timestamp"]), int(r["End_Timestamp"]), norm_name(r["Kernel_Name"])))
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows


def steady_window(rows: list[tuple[str, int, int, str]], want: int = 20) -> tuple[int, int, int]:
    """Marker starts on the first rank seen; longest run of intervals within 25% of the median;
    `want` steps from its middle. Raises when there is no steady decode in the trace."""
    marked = [(s, a) for a, s, _e, k in rows if MARKER in k]
    first_rank = min(marked)[1] if marked else None  # ONE rank: interleaved ranks halve every interval
    marks = sorted(s for s, a in marked if a == first_rank)
    if len(marks) < 4:
        raise RuntimeError(f"marker {MARKER} fired {len(marks)} times: the trace holds no decode steps")
    d = [b - a for a, b in zip(marks, marks[1:])]
    med = statistics.median(d)
    best = run = 0
    best_end = 0
    for i, x in enumerate(d):
        run = run + 1 if 0.75 * med < x < 1.25 * med else 0
        if run > best:
            best, best_end = run, i
    if best < 3:
        raise RuntimeError(f"no steady decode run at median {med / 1e6:.3f} ms")
    start = best_end - best + 1
    k = min(best, want)
    lo = start + (best - k) // 2
    return marks[lo], marks[lo + k], k


def analyse(rows: list[tuple[str, int, int, str]], overhead_us: float) -> dict[str, Any]:
    t0, t1, nstep = steady_window(rows)
    per_kernel: dict[str, list[float]] = defaultdict(list)
    joins: dict[tuple[str, str], list[float]] = defaultdict(list)
    ranks: dict[str, dict[str, float]] = {}
    for agent in sorted({r[0] for r in rows}):
        busy = 0
        hi = None
        prev = None
        n = 0
        gap_raw = gap_corr = 0.0
        for a, s, e, k in rows:
            if a != agent or s < t0 or e > t1:
                continue
            n += 1
            per_kernel[k].append((e - s) / 1000.0)
            if hi is None:
                busy += e - s
            elif s > hi:
                g = (s - hi) / 1000.0
                gap_raw += g
                gap_corr += max(0.0, g - overhead_us)
                joins[(prev, k)].append(max(0.0, g - overhead_us))
                busy += e - s
            elif e > hi:
                busy += e - hi
            hi = e if hi is None else max(hi, e)
            prev = k
        if n:
            ranks[agent] = {"dispatches_per_step": round(n / nstep, 1), "busy_ms_per_step": round(busy / 1e6 / nstep, 4),
                            "gap_ms_per_step_traced": round(gap_raw / 1000 / nstep, 4),
                            "gap_ms_per_step_corrected": round(gap_corr / 1000 / nstep, 4)}
    wall_ms = (t1 - t0) / 1e6 / nstep
    kernels = sorted(({"kernel": k, "calls_per_step": round(len(v) / nstep, 2),
                       "us_per_step": round(sum(v) / nstep, 1), "avg_us": round(statistics.mean(v), 2),
                       "min_us": round(min(v), 2)} for k, v in per_kernel.items()),
                     key=lambda x: -x["us_per_step"])
    small = [k for k in kernels if k["avg_us"] < SMALL_KERNEL_US]
    join_rows = sorted(({"from": a, "to": b, "count_per_step": round(len(v) / nstep / max(len(ranks), 1), 2),
                         "gap_us_per_step": round(sum(v) / nstep / max(len(ranks), 1), 1)}
                        for (a, b), v in joins.items()), key=lambda x: -x["gap_us_per_step"])
    return {"window_steps": nstep, "traced_ms_per_step": round(wall_ms, 4), "ranks": ranks,
            "kernels": kernels, "small_kernels": {"count_per_step": round(sum(k["calls_per_step"] for k in small) / max(len(ranks), 1), 1),
                                                  "us_per_step": round(sum(k["us_per_step"] for k in small) / max(len(ranks), 1), 1),
                                                  "threshold_us": SMALL_KERNEL_US},
            "joins": join_rows[:40]}


def run_tool(cmd: list[str], out: Path, env: dict[str, str] | None = None) -> str | None:
    """The engine's own summaries are a cross-check of ours; a failure is reported in PROFILE.md
    and summary.json instead of discarding the whole profile."""
    proc = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False)
    out.write_text(proc.stdout + (f"\n--- stderr ---\n{proc.stderr}" if proc.stderr.strip() else ""))
    return None if proc.returncode == 0 else f"{Path(cmd[1]).name} rc={proc.returncode}, siehe {out.name}"


# ---------------------------------------------------------------- report

def render(summary: dict[str, Any]) -> str:
    L = [f"# Decode-Profil {summary['commit'][:10]}", "",
         f"Build `{summary['build_dir']}`, {summary['date']}. Werkzeuge: `libr4d/isa/trace.sh`, `tsum.sh`, `gaps.sh`.", "",
         "**Lesen:** Kernel-Zeit ist echt (Hardware-Zeitstempel). Lücken enthalten den Tracer und sind eine",
         "Obergrenze; „korrigiert“ zieht die kalibrierte Tracer-Last je Dispatch ab. „Busy“ sagt nichts über",
         "Auslastung: ein Kernel auf 1 von 64 CUs zählt wie ein voller GEMM. Schrittzeit immer aus dem Lauf",
         "ohne Trace nehmen.", ""]
    for c in summary["levels"]:
        a = c["analysis"]
        L += [f"## {c['streams']} Stream(s)", "",
              f"- Ohne Trace: {c['untraced']['decode_tps']} tok/s, {c['untraced_ms_per_step']} ms/Schritt "
              f"(kalibriert); mit Trace {a['traced_ms_per_step']} ms/Schritt; Tracer-Last {c['overhead_us']} µs je Dispatch",
              ""]
        L += ["| Rang | Dispatches/Schritt | Kernel-Zeit ms | Lücke ms (traced) | Lücke ms (korrigiert) | Lückenanteil am untraced Schritt |",
              "|---|---|---|---|---|---|"]
        for rank, r in a["ranks"].items():
            share = 100 * r["gap_ms_per_step_corrected"] / c["untraced_ms_per_step"] if c["untraced_ms_per_step"] else 0
            L.append(f"| {rank} | {r['dispatches_per_step']} | {r['busy_ms_per_step']} | {r['gap_ms_per_step_traced']} | "
                     f"{r['gap_ms_per_step_corrected']} | {share:.1f} % |")
        sk = a["small_kernels"]
        L += ["", f"Kleine Kernel (< {sk['threshold_us']:.0f} µs im Mittel): {sk['count_per_step']} je Rang und Schritt, "
                  f"zusammen {sk['us_per_step']} µs Kernel-Zeit.", "",
              "**Größte Übergänge** (korrigierte Lücke vor `nach`, je Rang und Schritt). Eine Fusion von `von` und `nach` kann "
              "höchstens diese Lücke plus den eingesparten Speicherverkehr gewinnen:", "",
              "| von | nach | Anzahl/Schritt | Lücke µs/Schritt |", "|---|---|---|---|"]
        for j in a["joins"][:20]:
            L.append(f"| `{j['from']}` | `{j['to']}` | {j['count_per_step']} | {j['gap_us_per_step']} |")
        L += ["", "**Teuerste Kernel** (beide Ränge summiert):", "",
              "| Kernel | Aufrufe/Schritt | µs/Schritt | Ø µs | min µs |", "|---|---|---|---|---|"]
        for k in a["kernels"][:20]:
            L.append(f"| `{k['kernel']}` | {k['calls_per_step']} | {k['us_per_step']} | {k['avg_us']} | {k['min_us']} |")
        L += ["", f"Vollständige Tabellen: `tsum_c{c['streams']}.txt`, `gaps_c{c['streams']}.txt`."]
        L += [f"**Warnung:** {w}" for w in c.get("warnings", [])] + [""]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", default="1,8")
    ap.add_argument("--tokens", type=int, default=256)
    ap.add_argument("--startup-timeout", type=int, default=900)
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    levels = [int(x) for x in args.concurrency.split(",")]
    busy = ab_gate.radiance_processes()
    if busy:
        print(f"GPUs busy: radiance processes running {busy}", file=sys.stderr)
        return 3
    commit = subprocess.run(["git", "-C", str(args.build_dir.parent), "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    summary: dict[str, Any] = {"commit": commit, "build_dir": str(args.build_dir), "date": time.strftime("%Y-%m-%d %H:%M"),
                               "marker": MARKER, "tokens": args.tokens, "levels": []}
    try:
        engine = ab_gate.Engine(args.build_dir, PORT, out / "engine_untraced.log", [], {})
        engine.start(args.startup_timeout)
        try:
            drive(PORT, 1, 16)  # warmup, discarded
            untraced = {n: drive(PORT, n, args.tokens) for n in levels}
        finally:
            engine.stop()
        for n in levels:
            tdir = out / f"trace_c{n}"
            traced_engine = TracedEngine(args.build_dir, PORT, tdir, out / f"engine_traced_c{n}.log")
            traced_engine.start(args.startup_timeout)
            try:
                traced = drive(PORT, n, args.tokens)  # at once: an idle traced server stops recording
            finally:
                csv_path = traced_engine.stop()
            rows = read_trace(csv_path)
            first = analyse(rows, 0.0)
            factor = traced["decode_s"] / untraced[n]["decode_s"]
            untraced_ms = first["traced_ms_per_step"] / factor
            per_rank = max(r["dispatches_per_step"] for r in first["ranks"].values())
            overhead_us = max(0.0, (first["traced_ms_per_step"] - untraced_ms) * 1000 / per_rank)
            analysis = analyse(rows, overhead_us)
            warnings = [w for w in (
                run_tool(["sh", str(ISA / "tsum.sh"), str(csv_path)], out / f"tsum_c{n}.txt",
                         {"OVERUS": f"{overhead_us:.3f}", "MARK": MARKER, "ISA_OUT": str(out / "tsum_tmp")}),
                run_tool(["sh", str(ISA / "gaps.sh"), str(csv_path)], out / f"gaps_c{n}.txt")) if w]
            with open(csv_path, "rb") as src, gzip.open(tdir / "k_kernel_trace.csv.gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            csv_path.unlink()
            summary["levels"].append({"streams": n, "untraced": untraced[n], "traced": traced,
                                      "untraced_ms_per_step": round(untraced_ms, 4),
                                      "overhead_us": round(overhead_us, 3), "analysis": analysis,
                                      "warnings": warnings})
    except (RuntimeError, OSError, ab_gate.SetupError, subprocess.SubprocessError, ValueError) as e:
        (out / "ERROR.txt").write_text(str(e) + "\n")
        print(f"profile failed: {e}", file=sys.stderr)
        return 2
    shutil.rmtree(out / "tsum_tmp", ignore_errors=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "PROFILE.md").write_text(render(summary))
    print(f"profile written: {out / 'PROFILE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
