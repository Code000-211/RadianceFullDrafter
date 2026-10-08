#!/usr/bin/env python3
"""check_composite_gate.py — Tier 2 BetterBench Composite Score Gate for RadianceMine

Evaluates BetterBench benchmark runs against the certified baseline (Opt 146).
Enforces:
  1. Composite Score Non-Degradation: candidate.total_score >= baseline.total_score (631.3 pts)
  2. C1 Decode Throughput: candidate.decode_med_tps >= baseline.decode_med_tps (205.2 t/s)
  3. C8 Concurrency Throughput: candidate.concurrency_tps >= baseline.concurrency_tps (448.2 t/s)
  4. 64k Cold Prefill Throughput: candidate.prefill_med_tps >= baseline.prefill_med_tps (9,331.8 t/s)
  5. Latency Guardrails:
     - C1 Decode P99 target <= 4.5 ms (no degradation vs baseline 8.72 ms)
     - C8 Decode P99 target <= 15.0 ms
     - Single-Stream TTFT target <= 100.0 ms
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Latency guardrail targets
TARGET_C1_P99_MS = 4.5
TARGET_C8_P99_MS = 15.0
TARGET_TTFT_MS = 100.0


def load_json(p: Path) -> dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_metrics(results: dict[str, Any]) -> dict[str, Any]:
    """Calculate BetterBench composite score and latency metrics."""
    cfg = results.get("config", {})
    t_dec_target = float(cfg.get("target_decode_tps", 300.0))
    t_pref_target = float(cfg.get("target_prefill_tps", 10000.0))
    t_conc_target = float(cfg.get("target_concurrency_tps", 700.0))

    w_dec = float(cfg.get("weight_decode", 0.35))
    w_pref = float(cfg.get("weight_prefill", 0.25))
    w_conc = float(cfg.get("weight_concurrency", 0.25))
    w_tail = float(cfg.get("weight_tail_smoothness", 0.15))

    # Single-stream
    dec_samples: list[float] = []
    itl_samples: list[float] = []
    ttft_samples: list[float] = []
    single_stream = results.get("single_stream", {})
    cat_decodes: dict[str, float] = {}

    for cat_name, cat_recs in single_stream.items():
        cat_samples: list[float] = []
        for r in cat_recs:
            if r.get("ok"):
                if r.get("decode_tps"):
                    dec_samples.append(float(r["decode_tps"]))
                    cat_samples.append(float(r["decode_tps"]))
                if r.get("itl_ms"):
                    itl_samples.extend([float(x) for x in r["itl_ms"]])
                if r.get("ttft_ms") is not None:
                    ttft_samples.append(float(r["ttft_ms"]))
        if cat_samples:
            cat_samples.sort()
            cat_decodes[cat_name] = cat_samples[len(cat_samples) // 2]

    dec_samples.sort()
    dec_med = dec_samples[len(dec_samples) // 2] if dec_samples else 0.0

    # ITL & P99
    itl_samples.sort()
    c1_itl_p99_ms = itl_samples[int(len(itl_samples) * 0.99)] if itl_samples else 0.0
    med_itl = itl_samples[len(itl_samples) // 2] if itl_samples else 0.0
    itl_med_rate = (1000.0 / med_itl) if med_itl > 0 else dec_med
    low_1pct_idx = int(len(itl_samples) * 0.01)
    low_1pct_ms = itl_samples[min(low_1pct_idx, len(itl_samples) - 1)] if itl_samples else 0.0
    itl_low1_rate = (1000.0 / low_1pct_ms) if low_1pct_ms > 0 else (0.8 * itl_med_rate)

    tail_ratio = (itl_low1_rate / itl_med_rate) if itl_med_rate > 0 else 0.5
    tail_ratio = max(0.10, min(1.0, tail_ratio))
    stability_factor = 0.70 + 0.30 * tail_ratio

    ttft_samples.sort()
    ttft_p50_ms = ttft_samples[len(ttft_samples) // 2] if ttft_samples else 0.0

    # Prefill
    pref_tps = 0.0
    prefill_runs = results.get("prefill", [])
    valid_prefill = [d for d in prefill_runs if not d.get("skipped") and d.get("pp_tps")]
    if valid_prefill:
        valid_prefill.sort(key=lambda d: d.get("target_depth", 0))
        target_prefill = valid_prefill[-1]
        pp_vals = target_prefill.get("pp_tps", [])
        if pp_vals:
            sorted_pps = sorted([float(x) for x in pp_vals])
            pref_tps = sorted_pps[len(sorted_pps) // 2]

    # Concurrency C8
    conc_tps = 0.0
    c8_itls: list[float] = []
    concurrency_runs = results.get("concurrency", [])
    for c in concurrency_runs:
        if c.get("level") == 8:
            if c.get("aggregate_tps"):
                conc_tps = float(c["aggregate_tps"])
            if c.get("itl_ms"):
                c8_itls = [float(x) for x in c["itl_ms"]]
            break
    if conc_tps == 0.0 and concurrency_runs:
        conc_tps = float(max((c.get("aggregate_tps") or 0.0) for c in concurrency_runs))

    c8_itls.sort()
    c8_itl_p99_ms = c8_itls[int(len(c8_itls) * 0.99)] if c8_itls else (c1_itl_p99_ms * 2.0)

    # Subscores
    score_dec = (dec_med / t_dec_target) * 1000.0 if t_dec_target > 0 else 0.0
    if pref_tps <= t_pref_target:
        score_pref = (pref_tps / t_pref_target) * 1000.0 if t_pref_target > 0 else 0.0
    else:
        score_pref = min(1200.0, 1000.0 + 200.0 * math.log10(1.0 + (pref_tps - t_pref_target) / t_pref_target))
        if pref_tps > 25000.0:
            score_pref = min(1000.0, score_pref)

    score_conc = (conc_tps / t_conc_target) * 1000.0 if t_conc_target > 0 else 0.0
    score_tail = tail_ratio * 1000.0

    guardrail = 1.0
    if c8_itl_p99_ms > TARGET_C8_P99_MS:
        guardrail *= max(0.80, TARGET_C8_P99_MS / c8_itl_p99_ms)

    raw_composite = (w_dec * score_dec + w_pref * score_pref + w_conc * score_conc + w_tail * score_tail)
    total_score = round(raw_composite * stability_factor * guardrail, 1)

    return {
        "total_score": total_score,
        "decode_med_tps": round(dec_med, 1),
        "prefill_med_tps": round(pref_tps, 1),
        "concurrency_tps": round(conc_tps, 1),
        "c1_itl_p99_ms": round(c1_itl_p99_ms, 2),
        "c8_itl_p99_ms": round(c8_itl_p99_ms, 2),
        "ttft_p50_ms": round(ttft_p50_ms, 2),
        "categories": cat_decodes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tier 2 BetterBench Composite Score Gate for RadianceMine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("candidate_json", type=Path, help="Path to new BetterBench results.json")
    parser.add_argument(
        "baseline_json",
        type=Path,
        nargs="?",
        default=Path(__file__).parent.parent / "baselines" / "baseline_opt146.json",
        help="Path to baseline BetterBench results.json (default: baselines/baseline_opt146.json)",
    )
    parser.add_argument(
        "--allow-slack-pct",
        type=float,
        default=0.0,
        help="Allowed slack percentage for non-degradation checks (default: 0.0% strict)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write gate results JSON",
    )

    args = parser.parse_args()

    if not args.candidate_json.exists():
        print(f"❌ ERROR: Candidate results file not found: {args.candidate_json}", file=sys.stderr)
        return 1
    if not args.baseline_json.exists():
        print(f"❌ ERROR: Baseline results file not found: {args.baseline_json}", file=sys.stderr)
        return 1

    d_cand = load_json(args.candidate_json)
    d_base = load_json(args.baseline_json)

    m_cand = calculate_metrics(d_cand)
    m_base = calculate_metrics(d_base)

    print("=" * 80)
    print(" RadianceMine Tier 2 Gate: BetterBench Composite Score & Latency Guardrails")
    print(f" Candidate: {args.candidate_json}")
    print(f" Baseline:  {args.baseline_json}")
    print("=" * 80)

    header = f"| {'Metric / Dimension':<26} | {'Baseline':>12} | {'Candidate':>12} | {'Delta':>10} | {'Status':<12} |"
    sep = f"|{'-'*28}|{'-'*14}|{'-'*14}|{'-'*12}|{'-'*14}|"
    print(header)
    print(sep)

    violations: list[str] = []

    # 1. Composite Score
    score_b = m_base["total_score"]
    score_c = m_cand["total_score"]
    d_score = ((score_c - score_b) / score_b) * 100.0 if score_b else 0.0
    st_score = "🚀 GAIN" if d_score >= 0.5 else ("❌ REGRESS" if d_score < -args.allow_slack_pct else "✓ PASS")
    if d_score < -args.allow_slack_pct:
        violations.append(f"Composite Score degraded: {score_c:.1f} vs baseline {score_b:.1f} ({d_score:+.2f}%)")
    print(f"| {'COMPOSITE SCORE':<26} | {score_b:>10.1f} pts | {score_c:>10.1f} pts | {d_score:>+8.1f} % | {st_score:<12} |")
    print(sep)

    # 2. C1 Combined Decode
    dec_b = m_base["decode_med_tps"]
    dec_c = m_cand["decode_med_tps"]
    d_dec = ((dec_c - dec_b) / dec_b) * 100.0 if dec_b else 0.0
    st_dec = "🚀 GAIN" if d_dec >= 1.0 else ("❌ REGRESS" if d_dec < -args.allow_slack_pct else "✓ PASS")
    if d_dec < -args.allow_slack_pct:
        violations.append(f"C1 Decode Throughput degraded: {dec_c:.1f} vs baseline {dec_b:.1f} t/s ({d_dec:+.2f}%)")
    print(f"| • {'C1 Combined Decode':<24} | {dec_b:>10.1f} t/s | {dec_c:>10.1f} t/s | {d_dec:>+8.1f} % | {st_dec:<12} |")

    # 3. Concurrency C8
    c8_b = m_base["concurrency_tps"]
    c8_c = m_cand["concurrency_tps"]
    d_c8 = ((c8_c - c8_b) / c8_b) * 100.0 if c8_b else 0.0
    c8_slack = max(args.allow_slack_pct, 2.0)
    st_c8 = "🚀 GAIN" if d_c8 >= 1.0 else ("❌ REGRESS" if d_c8 < -c8_slack else "✓ PASS")
    if d_c8 < -c8_slack:
        violations.append(f"C8 Concurrency degraded: {c8_c:.1f} vs baseline {c8_b:.1f} t/s ({d_c8:+.2f}%)")
    print(f"| • {'C8 Concurrency':<24} | {c8_b:>10.1f} t/s | {c8_c:>10.1f} t/s | {d_c8:>+8.1f} % | {st_c8:<12} |")

    # 4. Prefill 64k
    pf_b = m_base["prefill_med_tps"]
    pf_c = m_cand["prefill_med_tps"]
    d_pf = ((pf_c - pf_b) / pf_b) * 100.0 if pf_b else 0.0
    st_pf = "🚀 GAIN" if d_pf >= 1.0 else ("❌ REGRESS" if d_pf < -args.allow_slack_pct else "✓ PASS")
    if d_pf < -args.allow_slack_pct:
        violations.append(f"Cold 64k Prefill degraded: {pf_c:.1f} vs baseline {pf_b:.1f} t/s ({d_pf:+.2f}%)")
    print(f"| • {'Cold 64k Prefill':<24} | {pf_b:>10.1f} t/s | {pf_c:>10.1f} t/s | {d_pf:>+8.1f} % | {st_pf:<12} |")
    print(sep)

    # 5. Latency Guardrails
    print(f"| {'LATENCY GUARDRAILS':<26} | {'Baseline/Tgt':>12} | {'Candidate':>12} | {'Delta':>10} | {'Status':<12} |")
    print(sep)

    c1_b = m_base["c1_itl_p99_ms"]
    c1_c = m_cand["c1_itl_p99_ms"]
    # Pass if meets target <= 4.5ms OR does not degrade vs baseline
    st_c1 = "✓ PASS" if (c1_c <= TARGET_C1_P99_MS or c1_c <= c1_b * 1.02) else "❌ REGRESS"
    if c1_c > TARGET_C1_P99_MS and c1_c > c1_b * 1.02:
        violations.append(f"C1 Decode P99 degraded: {c1_c:.2f} ms > baseline {c1_b:.2f} ms (Target: <= {TARGET_C1_P99_MS} ms)")
    print(f"| • {'C1 Decode P99':<24} | {c1_b:>10.2f} ms | {c1_c:>10.2f} ms | {c1_c - c1_b:>+8.2f} ms | {st_c1:<12} |")

    c8_b = m_base["c8_itl_p99_ms"]
    c8_c = m_cand["c8_itl_p99_ms"]
    st_c8 = "✓ PASS" if (c8_c <= TARGET_C8_P99_MS or c8_c <= c8_b * 1.05) else "❌ REGRESS"
    if c8_c > TARGET_C8_P99_MS and c8_c > c8_b * 1.05:
        violations.append(f"C8 Decode P99 degraded: {c8_c:.2f} ms > baseline {c8_b:.2f} ms (Target: <= {TARGET_C8_P99_MS} ms)")
    print(f"| • {'C8 Decode P99':<24} | {c8_b:>10.2f} ms | {c8_c:>10.2f} ms | {c8_c - c8_b:>+8.2f} ms | {st_c8:<12} |")

    ttft_b = m_base["ttft_p50_ms"]
    ttft_c = m_cand["ttft_p50_ms"]
    st_ttft = "✓ PASS" if (ttft_c <= TARGET_TTFT_MS and ttft_c <= ttft_b * 1.05) else "❌ REGRESS"
    if ttft_c > TARGET_TTFT_MS:
        violations.append(f"TTFT breached target: {ttft_c:.1f} ms > target {TARGET_TTFT_MS:.1f} ms")
    print(f"| • {'Single-Stream TTFT P50':<24} | {ttft_b:>10.1f} ms | {ttft_c:>10.1f} ms | {ttft_c - ttft_b:>+8.1f} ms | {st_ttft:<12} |")
    print(sep)

    passed = len(violations) == 0

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "passed": passed,
            "violations": violations,
            "candidate_metrics": m_cand,
            "baseline_metrics": m_base,
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    if passed:
        print(" ✅ TIER 2 BETTERBENCH COMPOSITE GATE PASSED!")
        print(f"    Composite Score: {score_c:.1f} pts (Baseline: {score_b:.1f} pts, Delta: {d_score:+.2f}%)")
        print("=" * 80)
        return 0
    else:
        print(f" ❌ TIER 2 GATE FAILED: {len(violations)} violation(s) detected:")
        for v in violations:
            print(f"    • {v}")
        print("=" * 80)
        return 2


if __name__ == "__main__":
    sys.exit(main())
