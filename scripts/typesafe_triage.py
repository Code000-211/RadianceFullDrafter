#!/usr/bin/env python3
"""
typesafe_triage.py — Fast Structured Decision Engine using TypeSafe AI (Jev)

Provides fast, typed decisions (<100ms) directly consumable by code:
  1. triage-suggestion: Classifies user proposals, detects hardware violations, scores feasibility.
  2. classify-regression: Identifies root cause of Master Gate failures (LDS, PCIe, Parity, Syntax).
  3. screen-candidate: Pre-screens arXiv/GitHub candidates for AMD RDNA4 compatibility.

Model: jev-latest (System One) via https://api.typesafe.ai/v1/systemone
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def get_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key:
        key_file = Path.home() / ".config" / "typesafe" / "api_key"
        if key_file.is_file():
            key = key_file.read_text(encoding="utf-8").strip()
    return key


def query_jev(state: str, questions: dict[str, Any]) -> dict[str, Any]:
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "TYPESAFE_API_KEY not found. Set it via env or in ~/.config/typesafe/api_key."
        )

    payload = {
        "state": state,
        "model": "jev-latest",
        "questions": questions,
    }

    req = urllib.request.Request(
        TYPESAFE_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("answers", {})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TypeSafe API Error HTTP {e.code}: {err_body}") from e
    except Exception as e:
        raise RuntimeError(f"Network error contacting TypeSafe API: {e}") from e


def triage_suggestion(text: str) -> dict[str, Any]:
    questions = {
        "subsystem": {
            "type": "choice",
            "instructions": "Which engine subsystem does this optimization proposal affect?",
            "criteria": {
                "gemm": "Matrix multiplication and linear projection kernels (FP8, INT4)",
                "gdn": "Gated Delta Network, recurrent SSM, linear attention",
                "qsa": "Qwen Sparse Attention, micro-block scoring, paged KV cache",
                "moe": "Mixture of Experts router, top-k scatter, expert GEMMs",
                "interconnect": "Dual-GPU P2P All-Reduce, PCIe DMA, memory fence synchronization",
                "drafter": "Speculative decoding, MTP drafter, acceptance controller",
                "general": "General engine, host CPU scheduling, or documentation",
            },
        },
        "violates_rdna4_limits": {
            "type": "noul",
            "instructions": (
                "Does this proposal contradict AMD RDNA4 gfx1201 hardware constraints "
                "(e.g. assumes PCIe 5.0 instead of 4.0, Wave64 instead of Wave32, >64KB LDS, or >84 VGPRs)?"
            ),
        },
        "feasibility": {
            "type": "score",
            "instructions": "Feasibility and architectural viability on dual AMD Radeon AI PRO R9700",
            "criteria": [
                "Unfeasible / contradicts hardware laws",
                "High risk or complex CUDA-specific dependency",
                "Moderate feasibility / experimental research needed",
                "Feasible / standard ROCm HIP implementation",
                "Immediate high-value quick win",
            ],
        },
    }
    return query_jev(text, questions)


def classify_regression(log_text: str) -> dict[str, Any]:
    questions = {
        "root_cause": {
            "type": "choice",
            "instructions": "What is the primary root cause of this test or gate failure?",
            "criteria": {
                "lds_bank_conflict": "LDS bank conflict, stride misalignment, or shared memory hazard",
                "pcie_barrier_saturation": "PCIe bus saturation from threadfence or interconnect deadlock",
                "parity_mismatch": "Bit-exactness or greedy parity mismatch against golden reference",
                "syntax_compile_error": "C++ or HIP compiler syntax, linking, or symbol resolution error",
                "gpu_timeout": "GPU hang, kernel timeout, or ROCm driver ring reset",
                "throughput_regression": "Tokens per second dropped below immutable speed floors",
                "other": "General environment or unclassified error",
            },
        },
        "severity": {
            "type": "score",
            "instructions": "Severity of regression",
            "criteria": [
                "Minor warning or timing jitter",
                "Small throughput drop (<5%)",
                "Major throughput degradation (>10%)",
                "Parity correctness failure",
                "Fatal compiler error or GPU lockup",
            ],
        },
        "recommended_action": {
            "type": "choice",
            "instructions": "What immediate action should be taken?",
            "criteria": {
                "fix_syntax": "Fix code compilation or symbol declaration",
                "revise_kernel_math": "Revise mathematical formulas, strides, or indexing in kernel",
                "warmup_clocks": "Warm up GPU clocks from DPM 0 (96 MHz) to DPM 5 (1258 MHz)",
                "revert_patch": "Revert patch; fundamental architectural regression",
            },
        },
    }
    return query_jev(log_text[-4000:], questions)


def screen_candidate(readme_text: str) -> dict[str, Any]:
    questions = {
        "cuda_specific": {
            "type": "noul",
            "instructions": "Does this technique require Nvidia-specific PTX, Tensor Cores, or CUDA-only features?",
        },
        "expected_roi": {
            "type": "score",
            "instructions": "Expected performance ROI on AMD dual R9700",
            "criteria": [
                "Placebo / zero or negative gain",
                "Marginal gain (<2%)",
                "Solid architectural gain (2-5%)",
                "High-impact gain (5-15%)",
                "Breakthrough gain (>15%)",
            ],
        },
    }
    return query_jev(readme_text[:4000], questions)


def main() -> int:
    parser = argparse.ArgumentParser(description="TypeSafe AI (Jev) Structured Triage Helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_sug = subparsers.add_parser("triage-suggestion", help="Triage user suggestion or research proposal")
    p_sug.add_argument("text", type=str, help="Suggestion text or hypothesis")
    p_sug.add_argument("--json", action="store_true", help="Output raw JSON")

    p_reg = subparsers.add_parser("classify-regression", help="Classify regression logs from Master Gate")
    p_reg.add_argument("log_path", type=Path, help="Path to failure log file or snippet")
    p_reg.add_argument("--json", action="store_true", help="Output raw JSON")

    p_scr = subparsers.add_parser("screen-candidate", help="Pre-screen a candidate lever README or paper")
    p_scr.add_argument("readme_path", type=Path, help="Path to candidate README.md")
    p_scr.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    try:
        if args.command == "triage-suggestion":
            res = triage_suggestion(args.text)
        elif args.command == "classify-regression":
            log_content = args.log_path.read_text(encoding="utf-8", errors="replace") if args.log_path.is_file() else str(args.log_path)
            res = classify_regression(log_content)
        elif args.command == "screen-candidate":
            readme_content = args.readme_path.read_text(encoding="utf-8", errors="replace")
            res = screen_candidate(readme_content)
        else:
            parser.print_help()
            return 1

        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print("================================================================================")
            print(" 🧠 TypeSafe AI (Jev System One) Structured Evaluation")
            print("================================================================================")
            for k, v in res.items():
                q_type = v.get("type", "")
                if q_type == "choice":
                    print(f" • {k.upper()}: {v.get('choice')} (Confidence: {v.get('confidence', 0):.0%})")
                elif q_type == "noul":
                    print(f" • {k.upper()} (Probability): {v.get('noul', 0):.2f}")
                elif q_type == "score":
                    print(f" • {k.upper()}: Level {v.get('score')} (Confidence: {v.get('confidence', 0):.0%})")
                else:
                    print(f" • {k}: {v}")
            print("================================================================================")
        return 0
    except (RuntimeError, urllib.error.URLError, ValueError, OSError) as e:
        print(f"⚠️  TypeSafe Triage failed: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
