"""bench_metrics.py — turns a BetterBench-schema results dict into the gate metrics.

Shared by ab_gate.py (per engine block). total_score is the BetterBench-style composite;
it is reported for reference only and never gated, because it swings with prefill.
"""

from __future__ import annotations

import math
from typing import Any

import gate_thresholds

TARGET_C8_P99_MS = gate_thresholds.load()["tier2"]["latency_targets_ms"]["c8_itl_p99"]


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
    # "1% lows" are the SLOWEST 1% of inter-token latencies, i.e. the 99th percentile of the
    # ascending list. Index 1% picked the fastest ones, which made tail_ratio >= 1, clamped to 1.0,
    # so the tail subscore was always 1000 and stability_factor always 1.0.
    low_1pct_idx = int(len(itl_samples) * 0.99)
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
        # The composite's parts, so a target can say which part is short (scripts/goal.py).
        # Reported only; the gate compares the metrics above.
        "itl_med_ms": round(med_itl, 3),
        "itl_low1_ms": round(low_1pct_ms, 3),
        "tail_ratio": round(tail_ratio, 4),
        "stability_factor": round(stability_factor, 4),
        "guardrail": round(guardrail, 4),
        "subscores": {"decode": round(score_dec, 1), "prefill": round(score_pref, 1),
                      "concurrency": round(score_conc, 1), "tail": round(score_tail, 1)},
        "weights": {"decode": w_dec, "prefill": w_pref, "concurrency": w_conc, "tail": w_tail},
    }
