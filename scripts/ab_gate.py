#!/usr/bin/env python3
"""ab_gate.py — Tier 1 + Tier 2: parity and A/B speed of a candidate build against a baseline build.

Both engines do not fit in VRAM together, so each block starts one engine, measures it and
stops it again:

    mode "ab":   A, B        mode "abba": A, B, B, A   (A = baseline build, B = candidate build)

Per block:
  1. start scripts/start_engine.sh in its own process group on tier2.port and check that the
     process serving it runs the expected binary (sha256 recorded in the manifest)
  2. Tier 1: one parity run is discarded as warmup, the next one must match the goldens
     (baseline blocks too; a baseline that fails parity means the goldens are stale)
  3. BetterBench single-stream + concurrency with baselines/bench_config.json, and a prefill
     sweep with random nonces (BetterBench seeds its prefill nonces, so a second run in the
     same engine would measure the prefix cache)
  4. MCLK sampled from sysfs during the measurement, reported per card
  5. the engine's process group is stopped; nothing else is touched

Verdict per metric: candidate mean vs baseline mean must not be worse than
tier2.slack_pct. In "abba" mode the A/A spread is checked against the slack as well;
a spread larger than the slack makes the result inconclusive, which fails the gate.

Exit codes: 0 pass, 2 candidate fails (parity, speed, or its engine does not start),
3 setup error (GPUs busy, baseline engine does not start) / inconclusive.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import secrets
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import bench_metrics
import gate_thresholds

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

HIGHER_IS_BETTER = ("decode_med_tps", "concurrency_tps", "prefill_med_tps")
LOWER_IS_BETTER = ("c1_itl_p99_ms", "c8_itl_p99_ms", "ttft_p50_ms")


class SetupError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def radiance_processes() -> list[tuple[int, str, int]]:
    """(pid, exe, pgid) of every running bin/radiance process."""
    out = []
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            exe = os.readlink(pid_dir / "exe")
            if exe.endswith("/bin/radiance"):
                out.append((int(pid_dir.name), exe, os.getpgid(int(pid_dir.name))))
        except (OSError, ProcessLookupError):
            continue
    return out


def tail(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def endpoint_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


class Engine:
    def __init__(self, build_dir: Path, port: int, log_path: Path, extra_args: list[str], extra_env: dict[str, str]):
        self.build_dir = build_dir.resolve()
        self.port = port
        self.log_path = log_path
        self.extra_args = extra_args
        self.extra_env = extra_env
        self.proc: subprocess.Popen | None = None

    def start(self, timeout_s: int) -> dict[str, Any]:
        binary = self.build_dir / "bin" / "radiance"
        if not binary.is_file():
            raise SetupError(f"no engine binary at {binary}")
        env = {**os.environ, **self.extra_env}
        cmd = ["bash", str(SCRIPT_DIR / "start_engine.sh"), "--build-dir", str(self.build_dir), "--port", str(self.port)]
        if self.extra_args:
            # start_engine.sh takes the model path as first positional argument before extra flags
            cmd += [str(Path(env.get("MODEL_PATH", "/root/models/qwen3.8-next-flash-fp8-iq4r-moe/qwen3.8-next-flash-fp8-iq4r-moe.rad")))]
            cmd += self.extra_args
        log_f = self.log_path.open("w")
        t0 = time.time()
        self.proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        while not endpoint_up(self.port):
            if self.proc.poll() is not None:
                raise SetupError(f"engine exited during startup (rc={self.proc.returncode}), see {self.log_path}")
            if time.time() - t0 > timeout_s:
                self.stop()
                raise SetupError(f"engine not ready after {timeout_s}s, see {self.log_path}")
            time.sleep(2)
        ours = [p for p in radiance_processes() if p[2] == self.proc.pid]
        if len(ours) != 1 or Path(ours[0][1]).resolve() != binary.resolve():
            self.stop()
            raise SetupError(f"port {self.port} is not served by {binary} from this block: {ours}")
        return {
            "binary": str(binary),
            "binary_sha256": sha256_file(binary),
            "pid": ours[0][0],
            "startup_s": round(time.time() - t0, 1),
            "extra_args": self.extra_args,
            "extra_env": self.extra_env,
        }

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.time() + 60
        while time.time() < deadline and any(p[2] == self.proc.pid for p in radiance_processes()):
            time.sleep(1)
        if any(p[2] == self.proc.pid for p in radiance_processes()):
            os.killpg(self.proc.pid, signal.SIGKILL)
            time.sleep(3)
        self.proc.wait(timeout=30)
        self.proc = None


class MclkSampler(threading.Thread):
    """Samples the active memory clock level of every card until stopped."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.paths = sorted(Path("/sys/class/drm").glob("card*/device/pp_dpm_mclk"))
        self.samples: dict[str, list[int]] = {p.parent.parent.name: [] for p in self.paths}
        self.top: dict[str, int] = {}
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.is_set():
            for p in self.paths:
                try:
                    lines = p.read_text().splitlines()
                except OSError:
                    continue
                card = p.parent.parent.name
                self.top[card] = len(lines) - 1
                for line in lines:
                    if "*" in line:
                        self.samples[card].append(int(line.split(":")[0]))
            self.halt.wait(0.5)

    def summary(self) -> dict[str, Any]:
        return {
            card: {
                "samples": len(s),
                "top_level_share": round(sum(1 for x in s if x == self.top.get(card)) / len(s), 3) if s else None,
            }
            for card, s in self.samples.items()
        }


def run_parity(port: int, out: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "parity_check.py"), "--endpoint", f"http://127.0.0.1:{port}/v1",
         "--suite", "full", "--quiet", "--json-out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not out.is_file():
        raise SetupError(f"parity_check produced no report (rc={proc.returncode}): {proc.stderr.strip()[-400:]}")
    report = json.loads(out.read_text())
    return {
        "passed": proc.returncode == 0 and report.get("passed") is True,
        "failures": [
            {"id": r.get("id"), "reasons": r.get("divergence_reason")}
            for r in report.get("results", [])
            if not r.get("passed")
        ],
    }


def run_benchmark(port: int, cfg_path: Path, bb_path: str) -> dict[str, Any]:
    sys.path.insert(0, bb_path)
    from betterbench.client import stream_chat  # noqa: PLC0415
    from betterbench.config import Config  # noqa: PLC0415
    from betterbench.corpus import load_corpus  # noqa: PLC0415
    from betterbench.prefill import make_prefill_messages  # noqa: PLC0415
    from betterbench.runner import concurrency_sweep, single_stream  # noqa: PLC0415

    endpoint = f"http://127.0.0.1:{port}/v1"
    model = "qwen4exp"
    cfg = Config.load(cfg_path)
    corpus = load_corpus(None, None)
    quiet = lambda *_a, **_k: None  # noqa: E731

    results: dict[str, Any] = {"config": cfg.as_dict()}
    results["single_stream"] = asyncio.run(single_stream(endpoint, model, corpus, cfg, log=quiet))
    results["concurrency"] = asyncio.run(concurrency_sweep(endpoint, model, corpus, cfg, log=quiet))

    async def prefill() -> list[dict[str, Any]]:
        rows = []
        for depth in cfg.prefill_depths:
            recs = []
            for _ in range(cfg.prefill_warmup + cfg.prefill_runs):
                msgs = make_prefill_messages(depth, secrets.token_hex(8))
                recs.append(await stream_chat(
                    endpoint, model, msgs, max_tokens=cfg.prefill_max_tokens, temperature=0.0,
                    top_p=cfg.top_p, top_k=cfg.top_k, seed=cfg.seed, category="prefill",
                    prompt_id=f"pp{depth}", timeout=cfg.timeout_s,
                ))
            ok = [r for r in recs[cfg.prefill_warmup:] if r.ok]
            rows.append({
                "target_depth": depth,
                "prompt_tokens": [r.prompt_tokens for r in ok if r.prompt_tokens],
                "ttft_ms": [r.ttft_ms for r in ok if r.ttft_ms],
                "pp_tps": [r.pp_tps for r in ok if r.pp_tps],
            })
        return rows

    results["prefill"] = asyncio.run(prefill())
    return results


def run_block(name: str, role: str, engine: Engine, cfg: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    log(f"block {name} ({role}): starting {engine.build_dir}")
    manifest = engine.start(cfg["engine_ready_timeout_s"])
    log(f"block {name}: engine ready after {manifest['startup_s']}s (sha256 {manifest['binary_sha256'][:12]})")
    try:
        run_parity(engine.port, out_dir / f"{name}_parity_warmup.json")
        parity = run_parity(engine.port, out_dir / f"{name}_parity.json")
        log(f"block {name}: parity {'PASS' if parity['passed'] else 'FAIL'}")
        sampler = MclkSampler()
        sampler.start()
        try:
            bench = run_benchmark(engine.port, REPO_ROOT / cfg["bench_config"], cfg["betterbench_path"])
        finally:
            sampler.halt.set()
            sampler.join()
        (out_dir / f"{name}_bench.json").write_text(json.dumps(bench, indent=2))
        metrics = bench_metrics.calculate_metrics(bench)
        log(f"block {name}: decode {metrics['decode_med_tps']} C8 {metrics['concurrency_tps']} prefill {metrics['prefill_med_tps']}")
        return {"name": name, "role": role, "manifest": manifest, "parity": parity, "metrics": metrics, "mclk": sampler.summary()}
    finally:
        engine.stop()
        log(f"block {name}: engine stopped")


def compare(blocks: list[dict[str, Any]], slack: dict[str, float]) -> dict[str, Any]:
    a = [b["metrics"] for b in blocks if b["role"] == "baseline"]
    c = [b["metrics"] for b in blocks if b["role"] == "candidate"]
    rows, regressions, inconclusive = [], [], []
    for metric in HIGHER_IS_BETTER + LOWER_IS_BETTER:
        a_mean = statistics.mean(m[metric] for m in a)
        c_mean = statistics.mean(m[metric] for m in c)
        delta = (c_mean - a_mean) / a_mean * 100.0 if a_mean else 0.0
        worse = -delta if metric in HIGHER_IS_BETTER else delta
        a_spread = (max(m[metric] for m in a) - min(m[metric] for m in a)) / a_mean * 100.0 if len(a) > 1 and a_mean else None
        row = {"metric": metric, "baseline": round(a_mean, 2), "candidate": round(c_mean, 2),
               "delta_pct": round(delta, 2), "slack_pct": slack[metric],
               "baseline_spread_pct": round(a_spread, 2) if a_spread is not None else None}
        if a_spread is not None and a_spread > slack[metric]:
            row["verdict"] = "INCONCLUSIVE"
            inconclusive.append(metric)
        elif worse > slack[metric]:
            row["verdict"] = "REGRESSION"
            regressions.append(metric)
        else:
            row["verdict"] = "OK"
        rows.append(row)
    return {"rows": rows, "regressions": regressions, "inconclusive": inconclusive}


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        f"# A/B Gate: {summary['verdict']}",
        "",
        f"- Baseline build: `{summary['baseline_build']}`",
        f"- Candidate build: `{summary['candidate_build']}`",
        f"- Mode: `{summary['mode']}`, blocks: {', '.join(b['name'] for b in summary['blocks'])}",
        "",
        "## Tier 1: parity",
        "",
    ]
    for b in summary["blocks"]:
        status = "PASS" if b["parity"]["passed"] else f"FAIL {b['parity']['failures']}"
        lines.append(f"- {b['name']} ({b['role']}): {status}")
    lines += ["", "## Tier 2: speed (candidate vs baseline)", "",
              "| Metric | Baseline | Candidate | Delta | Slack | A/A spread | Verdict |", "|---|---|---|---|---|---|---|"]
    for r in summary["comparison"]["rows"]:
        spread = "-" if r["baseline_spread_pct"] is None else f"{r['baseline_spread_pct']:.1f} %"
        lines.append(f"| {r['metric']} | {r['baseline']} | {r['candidate']} | {r['delta_pct']:+.1f} % | {r['slack_pct']} % | {spread} | {r['verdict']} |")
    lines += ["", "## Engines", ""]
    for b in summary["blocks"]:
        m = b["manifest"]
        lines.append(f"- {b['name']}: `{m['binary']}` sha256 `{m['binary_sha256'][:16]}`, startup {m['startup_s']} s, MCLK top-level share {b['mclk']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Tier 1 + Tier 2: parity and A/B speed gate")
    parser.add_argument("--baseline-build", type=Path, required=True)
    parser.add_argument("--candidate-build", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="directory for logs, per-block results and report")
    parser.add_argument("--abba", action="store_true", help="A,B,B,A instead of A,B (adds an A/A noise check)")
    parser.add_argument("--candidate-arg", action="append", default=[], help="extra engine flag for the candidate (repeatable)")
    parser.add_argument("--candidate-env", action="append", default=[], help="KEY=VALUE environment for the candidate (repeatable)")
    args = parser.parse_args()

    cfg = gate_thresholds.load()["tier2"]
    mode = "abba" if args.abba else cfg["mode"]
    args.out.mkdir(parents=True, exist_ok=True)
    cand_env = dict(kv.split("=", 1) for kv in args.candidate_env)

    busy = radiance_processes()
    if busy:
        log(f"❌ GPUs busy: other radiance engines are running {busy}; stop them first")
        return 3

    order = ["baseline", "candidate"] if mode == "ab" else ["baseline", "candidate", "candidate", "baseline"]
    blocks: list[dict[str, Any]] = []
    for i, role in enumerate(order, start=1):
        build = args.baseline_build if role == "baseline" else args.candidate_build
        engine = Engine(build, cfg["port"], args.out / f"block{i}_{role}.log",
                        args.candidate_arg if role == "candidate" else [],
                        cand_env if role == "candidate" else {})
        try:
            blocks.append(run_block(f"block{i}", role, engine, cfg, args.out))
        except SetupError as e:
            # A candidate that cannot start or serve is the candidate's failure; a baseline
            # that cannot is a problem of the test setup.
            verdict, rc = (f"FAIL (candidate engine: {e})", 2) if role == "candidate" else (f"SETUP_ERROR (baseline engine: {e})", 3)
            log(f"❌ {verdict}")
            (args.out / "summary.json").write_text(json.dumps({"verdict": verdict, "blocks": blocks}, indent=2))
            (args.out / "report.md").write_text(
                f"# A/B Gate: {verdict}\n\nEngine log: `{engine.log_path}`\n\n```\n{tail(engine.log_path, 25)}\n```\n")
            return rc

    comparison = compare(blocks, cfg["slack_pct"])
    baseline_parity_ok = all(b["parity"]["passed"] for b in blocks if b["role"] == "baseline")
    candidate_parity_ok = all(b["parity"]["passed"] for b in blocks if b["role"] == "candidate")
    if not baseline_parity_ok:
        verdict, rc = "SETUP_ERROR (baseline fails parity: goldens stale)", 3
    elif not candidate_parity_ok:
        verdict, rc = "FAIL (parity)", 2
    elif comparison["inconclusive"]:
        verdict, rc = f"INCONCLUSIVE ({', '.join(comparison['inconclusive'])})", 3
    elif comparison["regressions"]:
        verdict, rc = f"FAIL ({', '.join(comparison['regressions'])})", 2
    else:
        verdict, rc = "PASS", 0

    summary = {
        "verdict": verdict,
        "mode": mode,
        "baseline_build": str(args.baseline_build.resolve()),
        "candidate_build": str(args.candidate_build.resolve()),
        "blocks": blocks,
        "comparison": comparison,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    report = render_report(summary)
    (args.out / "report.md").write_text(report)
    print(report)
    return rc


if __name__ == "__main__":
    random.seed()
    sys.exit(main())
