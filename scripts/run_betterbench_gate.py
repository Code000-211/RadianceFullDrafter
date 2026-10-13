#!/usr/bin/env python3
"""run_betterbench_gate.py — Run BetterBench and compute composite metrics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BetterBench and score results")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bench-config", type=Path, required=True)
    parser.add_argument("--betterbench-path", type=str, default="/opt/BetterBench")
    parser.add_argument("--raw-out", type=Path, required=True)
    parser.add_argument("--score-out", type=Path, required=True)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    import ab_gate
    import bench_metrics

    print(f"Running BetterBench against port {args.port} using config {args.bench_config}...")
    raw = ab_gate.run_benchmark(args.port, args.bench_config, args.betterbench_path)
    args.raw_out.write_text(json.dumps(raw, indent=2, default=str))

    score = bench_metrics.calculate_metrics(raw)
    args.score_out.write_text(json.dumps(score, indent=2))

    print("\n" + "=" * 70)
    print(f"🏆 BetterBench Composite Score: {score['total_score']}")
    print("=" * 70)
    print(f"Decode Median TPS:      {score['decode_med_tps']:.1f} tok/s")
    print(f"Prefill Throughput:     {score['prefill_med_tps']:.1f} tok/s")
    print(f"Concurrency C8 TPS:     {score['concurrency_tps']:.1f} tok/s")
    print(f"C1 ITL P99:             {score['c1_itl_p99_ms']:.2f} ms")
    print(f"C8 ITL P99:             {score['c8_itl_p99_ms']:.2f} ms")
    print("\nCategory Breakdown (tok/s):")
    for cat, val in score.get("categories", {}).items():
        print(f"  - {cat:15s}: {val:.1f} tok/s")


if __name__ == "__main__":
    main()
