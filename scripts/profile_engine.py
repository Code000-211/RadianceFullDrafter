#!/usr/bin/env python3
"""profile_engine.py — how fast main is, and where its time goes, as evidence for every lever.

    profile_engine.py --build-dir <build_hip> --out <dir> [--concurrency 1,8] [--tokens 256]

Three parts, one engine start each, all with scripts/start_engine.sh (the gate's configuration):

  score    untraced BetterBench exactly as the gate runs it (ab_gate.run_benchmark with
           baselines/bench_config.json, scripts/bench_metrics.py): total score, its subscores
           (decode, prefill, concurrency, tail/1% lows) and latencies. scripts/goal.py judges the
           target against this. Plus greedy chat requests (ignore_eos) per concurrency level whose
           untraced decode time calibrates the tracer below.
  decode   per concurrency level, the same greedy requests under libr4d/isa/trace.sh; a
           steady-state window keyed on the sampler marker that fires once per decode step
           (tsum.sh's method): per rank busy time as a union, gaps attributed to the kernel that
           follows them, the transitions with the largest gaps, small launch-bound kernels; and the
           SLOWEST steps against typical ones, which is where the 1% lows come from.
  prefill  one BetterBench prefill request (same depth as the benchmark) traced; the last burst of
           activity is the prefill, analysed like a decode step but per run.

Reading rules carried into the report (libr4d/isa/trace.sh, AGENTS.md §5): kernel durations are
hardware timestamps and real; gaps absorb the tracer's per-dispatch cost and are an UPPER BOUND.
That cost is calibrated from the same greedy request traced and untraced (identical tokens, so
identical steps): overhead_us = (traced ms/step - untraced ms/step) / dispatches per rank per step.

Output in --out: PROFILE.md, summary.json, score.json, tsum/gaps text, gzipped traces, engine logs.
The GPUs must be free; the lever queue runs this.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json
import os
import re
import secrets
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
import ab_gate  # noqa: E402  (Engine, benchmark, process checks: the gate's own way of doing them)
import bench_metrics  # noqa: E402
import gate_thresholds  # noqa: E402

ISA = REPO_ROOT / "libr4d" / "isa"
MARKER = os.environ.get("PROFILE_MARKER", "r4d_rowtopk_stage1")  # tsum.sh's once-per-decode-step kernel
PROMPT = ("Schreibe einen ausführlichen technischen Aufsatz über die Geschichte des Buchdrucks, "
          "mit Abschnitten zu Technik, Wirtschaft und Folgen für die Wissenschaft.")
SMALL_KERNEL_US = 10.0   # below this a dispatch is mostly launch floor: first thing a fusion removes
BURST_GAP_NS = 500_000_000  # idle longer than this separates the prefill from model load
PORT = 8190


# ---------------------------------------------------------------- workload

def chat_stream(port: int, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
    body = {"model": "m", "messages": messages, "max_tokens": max_tokens, "temperature": 0, "ignore_eos": True,
            "stream": True, "stream_options": {"include_usage": True}}
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
        raise RuntimeError("stream without usage or without any token; cannot time it")
    return {"t_start": t0, "t_first": first, "t_end": t1, "completion_tokens": usage["completion_tokens"],
            "prompt_tokens": usage.get("prompt_tokens")}


def drive(port: int, streams: int, max_tokens: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = [None] * streams  # type: ignore[list-item]
    errors: list[str] = []

    def one(i: int) -> None:
        try:
            results[i] = chat_stream(port, [{"role": "user", "content": f"{PROMPT} (s{i})"}], max_tokens)
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


def prefill_messages(bb_path: str, depth: int) -> list[dict[str, str]]:
    sys.path.insert(0, bb_path)
    from betterbench.prefill import make_prefill_messages  # noqa: PLC0415
    return make_prefill_messages(depth, secrets.token_hex(8))


# ---------------------------------------------------------------- engines

class TracedEngine:
    """scripts/start_engine.sh with rocprofv3 in front of bin/radiance only (RADIANCE_ENGINE_PREFIX),
    the same rocprofv3 call as libr4d/isa/trace.sh. Wrapping the whole script made rocprofv3
    instrument every helper process, and on epyc the traced engine then failed ar_ipc_alloc
    ("hip: invalid argument") and never served. Stops bin/radiance with SIGTERM only."""

    def __init__(self, build_dir: Path, port: int, trace_dir: Path, log_path: Path):
        self.build_dir, self.port, self.trace_dir, self.log_path = build_dir.resolve(), port, trace_dir, log_path
        self.proc: subprocess.Popen | None = None

    def start(self, timeout_s: int) -> None:
        if self.trace_dir.exists():
            shutil.rmtree(self.trace_dir)
        self.trace_dir.mkdir(parents=True)
        free_mib = shutil.disk_usage(self.trace_dir).free >> 20
        if free_mib < 4096:  # trace.sh's floor: a decode trace writes ~85 MB a minute
            raise RuntimeError(f"only {free_mib} MiB free under {self.trace_dir}, refusing to trace")
        rocm = os.environ.get("ROCM_PATH", "/opt/rocm")
        prefix = f"{rocm}/bin/rocprofv3 --kernel-trace --output-format csv -d {self.trace_dir} -o k --"
        cmd = ["bash", str(SCRIPT_DIR / "start_engine.sh"), "--build-dir", str(self.build_dir), "--port", str(self.port)]
        self.proc = subprocess.Popen(cmd, stdout=self.log_path.open("w"), stderr=subprocess.STDOUT,
                                     env={**os.environ, "RADIANCE_ENGINE_PREFIX": prefix}, start_new_session=True)
        t0 = time.time()
        while not ab_gate.endpoint_up(self.port):
            if self.proc.poll() is not None:
                raise RuntimeError(f"traced engine exited during startup (rc={self.proc.returncode}), see {self.log_path}")
            if time.time() - t0 > timeout_s:
                self.kill()
                raise RuntimeError(f"traced engine not ready after {timeout_s}s, see {self.log_path}")
            time.sleep(1)

    def stop(self) -> Path:
        """SIGTERM to the server so rocprofv3 finalises (a SIGKILL leaves no trace at all)."""
        for pid, _exe, pgid in ab_gate.radiance_processes():
            if self.proc and pgid == self.proc.pid:
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


def traced(build_dir: Path, out: Path, name: str, timeout_s: int, workload) -> tuple[Path, Any]:
    tdir = out / f"trace_{name}"
    engine = TracedEngine(build_dir, PORT, tdir, out / f"engine_traced_{name}.log")
    engine.start(timeout_s)
    try:
        result = workload()  # at once: an idle traced server stops recording
    finally:
        csv_path = engine.stop()
    return csv_path, result


# ---------------------------------------------------------------- trace analysis (tsum.sh's method)

Row = tuple[str, int, int, str]  # agent, start ns, end ns, kernel


def norm_name(n: str) -> str:
    n = n.replace("(anonymous namespace)::", "")
    n = re.sub(r"^void ", "", n)
    n = re.sub(r"\(.*$", "", n)
    return n.replace(" ", "")


def read_trace(path: Path) -> list[Row]:
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


def marker_starts(rows: list[Row]) -> list[int]:
    marked = [(s, a) for a, s, _e, k in rows if MARKER in k]
    first_rank = min(marked)[1] if marked else None  # ONE rank: interleaved ranks halve every interval
    return sorted(s for s, a in marked if a == first_rank)


def steady_window(rows: list[Row], want: int = 20) -> tuple[int, int, int]:
    """Longest run of marker intervals within 25% of the median; `want` steps from its middle."""
    marks = marker_starts(rows)
    if len(marks) < 4:
        raise RuntimeError(f"marker {MARKER} fired {len(marks)} times: the trace holds no decode steps")
    d = [b - a for a, b in zip(marks, marks[1:])]
    med = statistics.median(d)
    best = run = best_end = 0
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


def last_burst(rows: list[Row]) -> tuple[int, int, int]:
    """The last stretch of activity without an idle gap over BURST_GAP_NS: the request after load."""
    events = sorted((s, e) for _a, s, e, _k in rows)
    if not events:
        raise RuntimeError("empty trace")
    start, hi = events[0][0], events[0][1]
    for s, e in events[1:]:
        if s - hi > BURST_GAP_NS:
            start = s
        hi = max(hi, e)
    return start, hi, 1


def analyse(rows: list[Row], overhead_us: float, window: tuple[int, int, int] | None = None) -> dict[str, Any]:
    t0, t1, nstep = window or steady_window(rows)
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
    nr = max(len(ranks), 1)
    kernels = sorted(({"kernel": k, "calls_per_step": round(len(v) / nstep, 2),
                       "us_per_step": round(sum(v) / nstep, 1), "avg_us": round(statistics.mean(v), 2),
                       "min_us": round(min(v), 2)} for k, v in per_kernel.items()),
                     key=lambda x: -x["us_per_step"])
    small = [k for k in kernels if k["avg_us"] < SMALL_KERNEL_US]
    join_rows = sorted(({"from": a, "to": b, "count_per_step": round(len(v) / nstep / nr, 2),
                         "gap_us_per_step": round(sum(v) / nstep / nr, 1)}
                        for (a, b), v in joins.items()), key=lambda x: -x["gap_us_per_step"])
    return {"window_steps": nstep, "traced_ms_per_step": round((t1 - t0) / 1e6 / nstep, 4), "ranks": ranks,
            "kernels": kernels,
            "small_kernels": {"count_per_step": round(sum(k["calls_per_step"] for k in small) / nr, 1),
                              "us_per_step": round(sum(k["us_per_step"] for k in small) / nr, 1),
                              "threshold_us": SMALL_KERNEL_US},
            "joins": join_rows[:40]}


def slow_steps(rows: list[Row], overhead_us: float, share: float = 0.05) -> dict[str, Any]:
    """Where the slowest decode steps lose time against typical ones (the 1% lows' causes).

    Steps are marker-to-marker on the marker's rank. Typical = the middle half by duration, slow =
    the slowest `share` (at least 3). Per kernel, the extra kernel time and the extra (corrected)
    gap before it in a slow step, averaged; so a slow step is explained by what it ran longer
    (an expert load, a longer GEMM) or by where it waited (a host round trip)."""
    marks = marker_starts(rows)
    if len(marks) < 8:
        raise RuntimeError(f"marker {MARKER} fired {len(marks)} times: too few decode steps for outliers")
    rank = next(a for a, s, _e, k in rows if MARKER in k and s == marks[0])
    mine = [r for r in rows if r[0] == rank]
    steps = []
    j = 0
    for lo, hi in zip(marks, marks[1:]):
        kt: dict[str, float] = defaultdict(float)
        gt: dict[str, float] = defaultdict(float)
        end = None
        while j < len(mine) and mine[j][1] < lo:
            j += 1
        i = j
        while i < len(mine) and mine[i][1] < hi:
            _a, s, e, k = mine[i]
            kt[k] += (e - s) / 1000.0
            if end is not None and s > end:
                gt[k] += max(0.0, (s - end) / 1000.0 - overhead_us)
            end = e if end is None else max(end, e)
            i += 1
        steps.append({"ms": (hi - lo) / 1e6, "kernel": kt, "gap": gt})
    order = sorted(steps, key=lambda x: x["ms"])
    n = len(order)
    typical = order[n // 4: max(n // 4 + 1, 3 * n // 4)]
    slow = order[-max(3, int(n * share)):]

    def avg(group: list[dict], field: str) -> dict[str, float]:
        acc: dict[str, float] = defaultdict(float)
        for st in group:
            for k, v in st[field].items():
                acc[k] += v / len(group)
        return acc

    tk, sk, tg, sg = avg(typical, "kernel"), avg(slow, "kernel"), avg(typical, "gap"), avg(slow, "gap")
    contrib = [{"kernel": k, "where": "Kernel-Zeit", "extra_us": round(sk.get(k, 0) - tk.get(k, 0), 1)} for k in set(sk) | set(tk)]
    contrib += [{"kernel": k, "where": "Lücke davor", "extra_us": round(sg.get(k, 0) - tg.get(k, 0), 1)} for k in set(sg) | set(tg)]
    contrib.sort(key=lambda c: -c["extra_us"])
    ms = [s["ms"] for s in order]
    return {"rank": rank, "steps": n, "slow_count": len(slow),
            "step_ms_traced": {"p50": round(ms[n // 2], 3), "p95": round(ms[min(n - 1, int(n * 0.95))], 3),
                               "p99": round(ms[min(n - 1, int(n * 0.99))], 3), "max": round(ms[-1], 3)},
            "typical_ms": round(statistics.mean(s["ms"] for s in typical), 3),
            "slow_ms": round(statistics.mean(s["ms"] for s in slow), 3),
            "contributors": [c for c in contrib if c["extra_us"] > 0][:15]}


def run_tool(cmd: list[str], out: Path, env: dict[str, str] | None = None) -> str | None:
    """The engine's own summaries are a cross-check of ours; a failure is reported in PROFILE.md
    and summary.json instead of discarding the whole profile."""
    proc = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False)
    out.write_text(proc.stdout + (f"\n--- stderr ---\n{proc.stderr}" if proc.stderr.strip() else ""))
    return None if proc.returncode == 0 else f"{Path(cmd[1]).name} rc={proc.returncode}, siehe {out.name}"


def keep_trace(csv_path: Path) -> None:
    with open(csv_path, "rb") as src, gzip.open(csv_path.with_suffix(".csv.gz"), "wb") as dst:
        shutil.copyfileobj(src, dst)
    csv_path.unlink()


# ---------------------------------------------------------------- report

def table_section(a: dict[str, Any], unit: str, untraced_ms: float | None) -> list[str]:
    L = [f"| Rang | Dispatches/{unit} | Kernel-Zeit ms | Lücke ms (traced) | Lücke ms (korrigiert) | Lückenanteil |",
         "|---|---|---|---|---|---|"]
    for rank, r in a["ranks"].items():
        share = f"{100 * r['gap_ms_per_step_corrected'] / untraced_ms:.1f} %" if untraced_ms else "–"
        L.append(f"| {rank} | {r['dispatches_per_step']} | {r['busy_ms_per_step']} | {r['gap_ms_per_step_traced']} | "
                 f"{r['gap_ms_per_step_corrected']} | {share} |")
    sk = a["small_kernels"]
    L += ["", f"Kleine Kernel (< {sk['threshold_us']:.0f} µs im Mittel): {sk['count_per_step']} je Rang und {unit}, "
              f"zusammen {sk['us_per_step']} µs Kernel-Zeit.", "",
          f"**Größte Übergänge** (korrigierte Lücke vor `nach`, je Rang und {unit}). Eine Fusion von `von` und `nach` "
          "gewinnt höchstens diese Lücke plus den eingesparten Speicherverkehr:", "",
          f"| von | nach | Anzahl/{unit} | Lücke µs/{unit} |", "|---|---|---|---|"]
    L += [f"| `{j['from']}` | `{j['to']}` | {j['count_per_step']} | {j['gap_us_per_step']} |" for j in a["joins"][:20]]
    L += ["", "**Teuerste Kernel** (beide Ränge summiert):", "",
          f"| Kernel | Aufrufe/{unit} | µs/{unit} | Ø µs | min µs |", "|---|---|---|---|---|"]
    L += [f"| `{k['kernel']}` | {k['calls_per_step']} | {k['us_per_step']} | {k['avg_us']} | {k['min_us']} |"
          for k in a["kernels"][:20]]
    return L


def render(summary: dict[str, Any]) -> str:
    L = [f"# Engine-Profil {summary['commit'][:10]}", "",
         f"Build `{summary['build_dir']}`, {summary['date']}. Werkzeuge: BetterBench wie im Gate, "
         "`libr4d/isa/trace.sh`, `tsum.sh`, `gaps.sh`.", "",
         "**Lesen:** Kernel-Zeit ist echt (Hardware-Zeitstempel). Lücken enthalten den Tracer und sind eine",
         "Obergrenze; „korrigiert“ zieht die kalibrierte Tracer-Last je Dispatch ab. „Busy“ sagt nichts über",
         "Auslastung: ein Kernel auf 1 von 64 CUs zählt wie ein voller GEMM. Geschwindigkeiten immer aus dem",
         "Score-Teil (ohne Trace) nehmen.", ""]
    sc = summary.get("score")
    if sc:
        L += ["## Score (BetterBench, ohne Trace)", "",
              f"Gesamt **{sc['total_score']}**; Teilscores {sc['subscores']} bei Gewichten {sc['weights']}; "
              f"Stabilitätsfaktor {sc['stability_factor']} (1%-Lows {sc['itl_low1_ms']} ms gegen Median "
              f"{sc['itl_med_ms']} ms), Guardrail {sc['guardrail']}.", "",
              "| Metrik | Wert |", "|---|---|"]
        L += [f"| `{k}` | {sc[k]} |" for k in ("decode_med_tps", "prefill_med_tps", "concurrency_tps", "c1_itl_p99_ms",
                                               "c8_itl_p99_ms", "ttft_p50_ms")]
        L += ["", "Stand gegen das Ziel: `python3 scripts/goal.py` bzw. `reports/goal_status.json`.", ""]
    for c in summary["levels"]:
        a = c["analysis"]
        L += [f"## Decode, {c['streams']} Stream(s)", "",
              f"- Ohne Trace: {c['untraced']['decode_tps']} tok/s, {c['untraced_ms_per_step']} ms/Schritt "
              f"(kalibriert); mit Trace {a['traced_ms_per_step']} ms/Schritt; Tracer-Last {c['overhead_us']} µs je Dispatch", ""]
        L += table_section(a, "Schritt", c["untraced_ms_per_step"])
        so = c.get("slow_steps")
        if so:
            L += ["", f"**Langsamste Schritte** (Ursache der 1%-Lows; Rang {so['rank']}, {so['slow_count']} von {so['steps']} "
                      f"Schritten): Schrittzeit traced p50 {so['step_ms_traced']['p50']} / p95 {so['step_ms_traced']['p95']} / "
                      f"p99 {so['step_ms_traced']['p99']} / max {so['step_ms_traced']['max']} ms; typisch {so['typical_ms']} ms, "
                      f"langsam {so['slow_ms']} ms. Was ein langsamer Schritt zusätzlich braucht:", "",
                  "| Kernel | wo | zusätzlich µs |", "|---|---|---|"]
            L += [f"| `{x['kernel']}` | {x['where']} | {x['extra_us']} |" for x in so["contributors"]]
        L += ["", f"Vollständige Tabellen: `tsum_c{c['streams']}.txt`, `gaps_c{c['streams']}.txt`."]
        L += [f"**Warnung:** {w}" for w in c.get("warnings", [])] + [""]
    if summary.get("trace_error"):
        L += ["## Trace fehlgeschlagen", "",
              f"Die getracten Teile wurden abgebrochen: `{summary['trace_error']}`. Der Score oben ist davon "
              "unberührt; Kernel-Zeiten, Lücken und langsamste Schritte fehlen in diesem Profil.", ""]
    pf = summary.get("prefill")
    if pf:
        a = pf["analysis"]
        L += [f"## Prefill, {pf['prompt_tokens']} Prompt-Tokens", "",
              f"- Ohne Trace (BetterBench): {pf['untraced_tps']} tok/s; mit Trace {a['traced_ms_per_step']} ms für den "
              f"ganzen Prefill; Tracer-Last aus Decode c1 übernommen ({pf['overhead_us']} µs, Näherung)", ""]
        L += table_section(a, "Lauf", None)
        L += [f"**Warnung:** {w}" for w in pf.get("warnings", [])] + [""]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--concurrency", default="1,8")
    ap.add_argument("--tokens", type=int, default=256)
    ap.add_argument("--startup-timeout", type=int, default=1200)
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    levels = [int(x) for x in args.concurrency.split(",")]
    busy = ab_gate.radiance_processes()
    if busy:
        print(f"GPUs busy: radiance processes running {busy}", file=sys.stderr)
        return 3
    tier2 = gate_thresholds.load()["tier2"]
    bench_cfg_path = REPO_ROOT / tier2["bench_config"]
    depth = json.loads(bench_cfg_path.read_text())["prefill_depths"][-1]
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
            raw = ab_gate.run_benchmark(PORT, bench_cfg_path, tier2["betterbench_path"])
        finally:
            engine.stop()
        (out / "betterbench_raw.json").write_text(json.dumps(raw, indent=1, default=str))
        summary["score"] = bench_metrics.calculate_metrics(raw)
        (out / "score.json").write_text(json.dumps(summary["score"], indent=2))
    except (RuntimeError, OSError, ab_gate.SetupError, subprocess.SubprocessError, ValueError, KeyError) as e:
        (out / "ERROR.txt").write_text(str(e) + "\n")
        print(f"profile failed: {e}", file=sys.stderr)
        return 2

    # THE TRACES ARE THE SECOND HALF, AND THEIR FAILURE IS A FINDING, NOT A LOST PROFILE. The score
    # above stands on its own (the target is judged on it); a trace that cannot be taken stops the
    # remaining traced parts, because each costs an engine start, and is reported in PROFILE.md.
    try:
        for n in levels:
            csv_path, traced_run = traced(args.build_dir, out, f"c{n}", args.startup_timeout,
                                          lambda n=n: drive(PORT, n, args.tokens))
            rows = read_trace(csv_path)
            first = analyse(rows, 0.0)
            factor = traced_run["decode_s"] / untraced[n]["decode_s"]
            untraced_ms = first["traced_ms_per_step"] / factor
            per_rank = max(r["dispatches_per_step"] for r in first["ranks"].values())
            overhead_us = max(0.0, (first["traced_ms_per_step"] - untraced_ms) * 1000 / per_rank)
            warnings = [w for w in (
                run_tool(["sh", str(ISA / "tsum.sh"), str(csv_path)], out / f"tsum_c{n}.txt",
                         {"OVERUS": f"{overhead_us:.3f}", "MARK": MARKER, "ISA_OUT": str(out / "tsum_tmp")}),
                run_tool(["sh", str(ISA / "gaps.sh"), str(csv_path)], out / f"gaps_c{n}.txt")) if w]
            summary["levels"].append({"streams": n, "untraced": untraced[n], "traced": traced_run,
                                      "untraced_ms_per_step": round(untraced_ms, 4), "overhead_us": round(overhead_us, 3),
                                      "analysis": analyse(rows, overhead_us), "slow_steps": slow_steps(rows, overhead_us),
                                      "warnings": warnings})
            keep_trace(csv_path)

        overhead_c1 = summary["levels"][0]["overhead_us"] if summary["levels"] else 0.0
        messages = prefill_messages(tier2["betterbench_path"], depth)
        csv_path, pre = traced(args.build_dir, out, "prefill", args.startup_timeout,
                               lambda: chat_stream(PORT, messages, 1))
        rows = read_trace(csv_path)
        summary["prefill"] = {"depth": depth, "prompt_tokens": pre.get("prompt_tokens"),
                              "untraced_tps": summary["score"]["prefill_med_tps"], "overhead_us": overhead_c1,
                              # tsum.sh would sum the whole trace including model load here (it has no
                              # prefill marker), so only our last-burst window is reported.
                              "analysis": analyse(rows, overhead_c1, last_burst(rows)), "warnings": []}
        keep_trace(csv_path)
    except (RuntimeError, OSError, ab_gate.SetupError, subprocess.SubprocessError, ValueError, KeyError) as e:
        summary["trace_error"] = str(e)
        (out / "ERROR.txt").write_text(f"trace part: {e}\n")
        print(f"profile: trace part failed, score kept: {e}", file=sys.stderr)
    shutil.rmtree(out / "tsum_tmp", ignore_errors=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "PROFILE.md").write_text(render(summary))
    print(f"profile written: {out / 'PROFILE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
