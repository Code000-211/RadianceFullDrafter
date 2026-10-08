#!/usr/bin/env python3
"""parity_check.py — Strict Greedy Parity Pre-Benchmark Gate for RadianceMine

Executes standardized greedy decoding prompts (temperature=0.0) against the
running Radiance server and verifies bit-exact token completion parity against
known golden references.

Aborts immediately if divergence, premature end-of-turn, hallucination, or token
count drift is detected, preventing wasted benchmark runs on defective builds.

Tier 1 Gate Invariants:
  1. Token Exactness: 0 token discrepancy against certified reference vectors.
  2. Code Decode Speed: >= 230.0 tok/s on code_is_prime.
  3. Reasoning Decode Speed: >= 240.0 tok/s on reasoning_probability.
  4. Math Decode Speed: >= 210.0 tok/s on math_linear_eq.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ==============================================================================
# Built-in Default Golden References (Qwen3.8 / Qwen4Exp Baseline)
# ==============================================================================
DEFAULT_GOLDENS: list[dict[str, Any]] = [
    {
        "id": "sanity_arithmetic",
        "category": "sanity",
        "prompt": "What is 2+2? Answer with only the number.",
        "max_tokens": 16,
        "temperature": 0.0,
        "golden_tokens": 2,
        "golden_sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
        "expected_finish_reason": "stop",
        "golden_text": "4",
        "required_patterns": ["4"],
        "forbidden_patterns": ["<|im_start|>", "<|im_end|>", "error"],
    },
    {
        "id": "code_is_prime",
        "category": "code",
        "prompt": "Write a Python function `is_prime(n)` that returns True if n is prime and False otherwise. Include brief docstring and handle edge cases n <= 1.",
        "max_tokens": 128,
        "temperature": 0.0,
        "golden_tokens": 106,
        "golden_sha256": "7a35c5970c67530be90802ea7a6df10cb46fc1d51a69ea76c8cba766c075f80b",
        "expected_finish_reason": "stop",
        "golden_text": (
            "```python\ndef is_prime(n: int) -> bool:\n"
            "    \"\"\"Return True if n is prime, False otherwise.\"\"\"\n"
            "    if n <= 1:\n"
            "        return False\n"
            "    if n <= 3:\n"
            "        return True\n"
            "    if n % 2 == 0 or n % 3 == 0:\n"
            "        return False\n"
            "    i = 5\n"
            "    while i * i <= n:\n"
            "        if n % i == 0 or n % (i + 2) == 0:\n"
            "            return False\n"
            "        i += 6\n"
            "    return True\n```"
        ),
        "required_patterns": ["def is_prime", "if n <= 1:", "return True", "return False"],
        "forbidden_patterns": ["<|im_start|>", "<|im_end|>", "Traceback"],
    },
    {
        "id": "math_linear_eq",
        "category": "math",
        "prompt": "Solve the following equation step by step: 3*(x - 4) + 2*(2*x + 1) = 5*(x + 2) - 8. What is the value of x?",
        "max_tokens": 256,
        "temperature": 0.0,
        "golden_tokens": 249,
        "golden_sha256": "50cce287cbdfa2cf95dfb4e4708709ec543e33b5c65f9ea3f58e4483a9ce4257",
        "expected_finish_reason": "stop",
        "golden_text": (
            "To solve the equation step by step:\n\n"
            "Equation:\n"
            "$$3(x - 4) + 2(2x + 1) = 5(x + 2) - 8$$\n\n"
            "Step 1: Expand both sides.\n"
            "Left-hand side:\n"
            "$$3x - 12 + 4x + 2 = 7x - 10$$\n\n"
            "Right-hand side:\n"
            "$$5x + 10 - 8 = 5x + 2$$\n\n"
            "Now the equation is:\n"
            "$$7x - 10 = 5x + 2$$\n\n"
            "Step 2: Subtract $5x$ from both sides.\n"
            "$$2x - 10 = 2$$\n\n"
            "Step 3: Add 10 to both sides.\n"
            "$$2x = 12$$\n\n"
            "Step 4: Divide by 2.\n"
            "$$x = 6$$\n\n"
            "**Final Answer:**\n"
            "The value of $x$ is 6."
        ),
        "required_patterns": ["7x - 10", "5x + 2", "2x = 12", "x = 6"],
        "forbidden_patterns": ["<|im_start|>", "<|im_end|>"],
    },
    {
        "id": "reasoning_probability",
        "category": "reasoning",
        "prompt": "A box contains 3 red balls and 5 blue balls. Two balls are drawn sequentially at random without replacement. What is the exact probability that both balls are red? Express as a simplified fraction.",
        "max_tokens": 256,
        "temperature": 0.0,
        "golden_tokens": 251,
        "golden_sha256": "3df49c4033e6ca4a382dc3cbcc90c379a1f94d935f8a00ee6b47c4e5e78ecab7",
        "expected_finish_reason": "stop",
        "golden_text": (
            "To find the probability that both balls drawn are red without replacement:\n\n"
            "1. **Total number of balls initially**:\n"
            "   $$3 \\text{ (red)} + 5 \\text{ (blue)} = 8 \\text{ balls}$$\n\n"
            "2. **Probability that the first ball is red**:\n"
            "   $$P(R_1) = \\frac{3}{8}$$\n\n"
            "3. **Probability that the second ball is red given that the first was red**:\n"
            "   After drawing one red ball, there are 2 red balls left and 7 balls total.\n"
            "   $$P(R_2 \\mid R_1) = \\frac{2}{7}$$\n\n"
            "4. **Combined probability**:\n"
            "   $$P(R_1 \\cap R_2) = P(R_1) \\times P(R_2 \\mid R_1) = \\frac{3}{8} \\times \\frac{2}{7} = \\frac{6}{56}$$\n\n"
            "5. **Simplify the fraction**:\n"
            "   Dividing numerator and denominator by 2:\n"
            "   $$\\frac{6 \\div 2}{56 \\div 2} = \\frac{3}{28}$$\n\n"
            "**Final Answer:**\n"
            "The exact probability is **3/28**."
        ),
        "required_patterns": ["3/8", "2/7", "3/28"],
        "forbidden_patterns": ["<|im_start|>", "<|im_end|>"],
    },
]


@dataclass
class GoldenPrompt:
    id: str
    category: str
    prompt: str
    max_tokens: int
    temperature: float = 0.0
    golden_tokens: int = 0
    golden_sha256: str = ""
    expected_finish_reason: str = "stop"
    golden_text: str = ""
    required_patterns: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    prompt_id: str
    category: str
    passed: bool
    actual_tokens: int
    expected_tokens: int
    actual_sha256: str
    expected_sha256: str
    actual_finish_reason: str
    actual_text: str
    divergence_reason: list[str]
    ttft_ms: float
    total_ms: float
    decode_tps: float


def normalize_whitespace(text: str) -> str:
    """Normalize trailing whitespace and newlines for canonical hash comparison."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return "\n".join(lines)


def sha256_text(text: str) -> str:
    norm = normalize_whitespace(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def query_radiance(
    endpoint: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float = 0.0,
    timeout: float = 60.0,
) -> dict[str, Any]:
    url = f"{endpoint.rstrip('/')}/completions"
    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "RadianceMine-ParityGate/1.0"},
        method="POST",
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = (time.perf_counter() - t0) * 1000.0
            body = resp.read().decode("utf-8")
            res = json.loads(body)
            res["_request_elapsed_ms"] = elapsed
            return res
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {e.reason}\nResponse: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed to {url}: {e.reason}") from e


def run_single_prompt(
    test: GoldenPrompt,
    endpoint: str,
    model: str,
    token_tolerance: int = 0,
    timeout: float = 60.0,
) -> tuple[str, int, str, float, float, float]:
    data = query_radiance(
        endpoint=endpoint,
        model=model,
        prompt=test.prompt,
        max_tokens=test.max_tokens,
        temperature=test.temperature,
        timeout=timeout,
    )

    choice = data.get("choices", [{}])[0]
    content = choice.get("text", "")
    finish_reason = choice.get("finish_reason", "unknown")

    usage = data.get("usage", {})
    completion_tokens = usage.get("completion_tokens", len(content.split()))

    total_ms = data.get("_request_elapsed_ms", 0.0)
    timings = data.get("timings", {})
    ttft_ms = float(timings.get("prompt_ms", 0.0))
    predicted_ms = float(timings.get("predicted_ms", 0.0))

    if "predicted_per_second" in timings and timings["predicted_per_second"] is not None:
        decode_tps = float(timings["predicted_per_second"])
    elif predicted_ms > 0:
        decode_tps = completion_tokens / (predicted_ms / 1000.0)
    elif total_ms > 0:
        decode_tps = completion_tokens / (total_ms / 1000.0)
    else:
        decode_tps = 0.0

    return content, completion_tokens, finish_reason, ttft_ms, total_ms, decode_tps


def evaluate_output(
    test: GoldenPrompt,
    actual_text: str,
    actual_tokens: int,
    actual_finish: str,
    ttft_ms: float,
    total_ms: float,
    decode_tps: float,
    token_tolerance: int = 0,
) -> TestResult:
    reasons: list[str] = []
    actual_hash = sha256_text(actual_text)

    # 1. Finish reason check
    if actual_finish != test.expected_finish_reason:
        reasons.append(f"finish_reason mismatch: got '{actual_finish}', expected '{test.expected_finish_reason}'")

    # 2. Token discrepancy check
    diff_tokens = abs(actual_tokens - test.golden_tokens)
    if diff_tokens > token_tolerance:
        reasons.append(
            f"token count drift: got {actual_tokens}, expected {test.golden_tokens} (diff: {diff_tokens} > tol: {token_tolerance})"
        )

    # 3. Required patterns
    for pat in test.required_patterns:
        if pat not in actual_text:
            reasons.append(f"missing required semantic pattern: '{pat}'")

    # 4. Forbidden patterns
    for pat in test.forbidden_patterns:
        if pat in actual_text:
            reasons.append(f"contained forbidden leak/error pattern: '{pat}'")

    # 5. Exact hash comparison if tolerance is 0
    if (
        token_tolerance == 0
        and test.golden_sha256
        and actual_hash != test.golden_sha256
        and not any("missing required semantic pattern" in r for r in reasons)
    ):
        reasons.append(f"hash mismatch: got {actual_hash[:16]}..., expected {test.golden_sha256[:16]}...")

    passed = len(reasons) == 0

    return TestResult(
        prompt_id=test.id,
        category=test.category,
        passed=passed,
        actual_tokens=actual_tokens,
        expected_tokens=test.golden_tokens,
        actual_sha256=actual_hash,
        expected_sha256=test.golden_sha256,
        actual_finish_reason=actual_finish,
        actual_text=actual_text,
        divergence_reason=reasons,
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        decode_tps=decode_tps,
    )


def load_goldens(custom_path: Path | None) -> list[GoldenPrompt]:
    raw_data: list[dict[str, Any]] = []

    if custom_path and custom_path.exists():
        with open(custom_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    else:
        # Check standard locations
        candidates = [
            Path(__file__).parent / "golden_parity_reference.json",
            Path(__file__).parent.parent / "baselines" / "golden_parity_reference.json",
        ]
        found = False
        for c in candidates:
            if c.exists():
                with open(c, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                found = True
                break
        if not found:
            raw_data = DEFAULT_GOLDENS

    res: list[GoldenPrompt] = []
    for d in raw_data:
        res.append(
            GoldenPrompt(
                id=d["id"],
                category=d.get("category", "general"),
                prompt=d["prompt"],
                max_tokens=d.get("max_tokens", 128),
                temperature=d.get("temperature", 0.0),
                golden_tokens=d.get("golden_tokens", 0),
                golden_sha256=d.get("golden_sha256", ""),
                expected_finish_reason=d.get("expected_finish_reason", "stop"),
                golden_text=d.get("golden_text", ""),
                required_patterns=d.get("required_patterns", []),
                forbidden_patterns=d.get("forbidden_patterns", []),
            )
        )
    return res


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strict Greedy Parity Pre-Benchmark Gate for RadianceMine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("ENDPOINT", f"http://localhost:{os.getenv('PORT', '8000')}/v1"),
        help="Inference API endpoint (e.g. http://localhost:8000/v1)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("MODEL", "qwen4exp"),
        help="Model identifier",
    )
    parser.add_argument(
        "--goldens",
        type=Path,
        default=None,
        help="Path to golden reference JSON file",
    )
    parser.add_argument(
        "--suite",
        choices=["fast", "core", "full"],
        default="full",
        help="Test suite scope: 'fast' (sanity), 'core' (sanity + code), 'full' (all)",
    )
    parser.add_argument(
        "--token-tolerance",
        type=int,
        default=0,
        help="Maximum allowed token count discrepancy for passing (0 = strict exact)",
    )
    parser.add_argument(
        "--min-code-tps",
        type=float,
        default=float(os.getenv("MIN_CODE_TPS", "230.0")),
        help="Minimum required decode speed (t/s) on code_is_prime to pass parity gate (default: 230.0)",
    )
    parser.add_argument(
        "--min-reasoning-tps",
        type=float,
        default=float(os.getenv("MIN_REASONING_TPS", "240.0")),
        help="Minimum required decode speed (t/s) on reasoning_probability to pass parity gate (default: 240.0)",
    )
    parser.add_argument(
        "--min-math-tps",
        type=float,
        default=float(os.getenv("MIN_MATH_TPS", "210.0")),
        help="Minimum required decode speed (t/s) on math_linear_eq to pass parity gate (default: 210.0)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop immediately on the first parity discrepancy",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds per prompt query",
    )
    parser.add_argument(
        "--connect-retries",
        type=int,
        default=5,
        help="Number of readiness retry attempts before failing",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write full test results JSON report",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-prompt console printing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full generated text",
    )

    args = parser.parse_args()

    # Pre-flight Connectivity Verification
    health_url = f"{args.endpoint.rstrip('/')}/models"
    connected = False
    for attempt in range(1, args.connect_retries + 1):
        try:
            with urllib.request.urlopen(health_url, timeout=5.0) as resp:
                if resp.status == 200:
                    connected = True
                    break
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < args.connect_retries:
                time.sleep(1.0)

    if not connected:
        print(f"❌ FATAL: Unable to reach inference server at {health_url}", file=sys.stderr)
        print("Ensure the engine is running (`scripts/start_engine.sh`) before invoking parity_check.", file=sys.stderr)
        return 1

    goldens = load_goldens(args.goldens)

    # Filter suite
    if args.suite == "fast":
        tests = [g for g in goldens if g.category == "sanity"]
    elif args.suite == "core":
        tests = [g for g in goldens if g.category in ("sanity", "code")]
    else:
        tests = goldens

    if not tests:
        print(f"❌ No test prompts found for suite '{args.suite}'", file=sys.stderr)
        return 1

    if not args.quiet:
        print("=" * 80)
        print(" RadianceMine Tier 1 Gate: Strict Greedy Parity & Speed Verification")
        print(f" Target Endpoint: {args.endpoint} | Model: {args.model}")
        print(f" Scope: {args.suite.upper()} ({len(tests)} prompts) | Token Tolerance: {args.token_tolerance}")
        print(
            f" Thresholds: Code >= {args.min_code_tps:.1f} t/s, Reasoning >= {args.min_reasoning_tps:.1f} t/s, Math >= {args.min_math_tps:.1f} t/s"
        )
        print("=" * 80)
        header = f"| {'Test ID':<22} | {'Category':<10} | {'Result':<14} | {'Tokens':>11} | {'Speed':>10} |"
        sep = f"|{'-'*24}|{'-'*12}|{'-'*16}|{'-'*13}|{'-'*12}|"
        print(header)
        print(sep)

    results: list[TestResult] = []
    failures = 0

    for test in tests:
        try:
            content, tokens, finish_reason, ttft_ms, total_ms, decode_tps = run_single_prompt(
                test=test,
                endpoint=args.endpoint,
                model=args.model,
                token_tolerance=args.token_tolerance,
                timeout=args.timeout,
            )
            res = evaluate_output(
                test=test,
                actual_text=content,
                actual_tokens=tokens,
                actual_finish=finish_reason,
                ttft_ms=ttft_ms,
                total_ms=total_ms,
                decode_tps=decode_tps,
                token_tolerance=args.token_tolerance,
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as e:
            res = TestResult(
                prompt_id=test.id,
                category=test.category,
                passed=False,
                actual_tokens=0,
                expected_tokens=test.golden_tokens,
                actual_sha256="",
                expected_sha256=test.golden_sha256,
                actual_finish_reason="error",
                actual_text="",
                divergence_reason=[f"Execution exception: {e}"],
                ttft_ms=0.0,
                total_ms=0.0,
                decode_tps=0.0,
            )

        # Enforce Tier 1 Speed Floors
        if (
            test.id == "code_is_prime" or test.category == "code"
        ) and args.min_code_tps > 0 and res.decode_tps < args.min_code_tps:
            res.passed = False
            res.divergence_reason.append(
                f"Severe speed regression: Code TPS {res.decode_tps:.1f} t/s < threshold {args.min_code_tps:.1f} t/s"
            )

        if (
            test.id == "reasoning_probability" or test.category == "reasoning"
        ) and args.min_reasoning_tps > 0 and res.decode_tps < args.min_reasoning_tps:
            res.passed = False
            res.divergence_reason.append(
                f"Severe speed regression: Reasoning TPS {res.decode_tps:.1f} t/s < threshold {args.min_reasoning_tps:.1f} t/s"
            )

        if (
            test.id == "math_linear_eq" or test.category == "math"
        ) and args.min_math_tps > 0 and res.decode_tps < args.min_math_tps:
            res.passed = False
            res.divergence_reason.append(
                f"Severe speed regression: Math TPS {res.decode_tps:.1f} t/s < threshold {args.min_math_tps:.1f} t/s"
            )

        results.append(res)

        if not res.passed:
            failures += 1
            status_badge = "❌ SLOW / REGRESSED" if any("speed regression" in r for r in res.divergence_reason) else "❌ DIVERGED"
        else:
            status_badge = "✅ PASS"

        tok_str = f"{res.actual_tokens}/{test.golden_tokens}"
        speed_str = f"{res.decode_tps:>6.1f} t/s"

        if not args.quiet:
            print(f"| {test.id:<22} | {test.category:<10} | {status_badge:<14} | {tok_str:>11} | {speed_str:>10} |")

        if args.verbose:
            print(f"\n--- Output for {test.id} ---")
            print(res.actual_text)
            print("--- End Output ---\n")

        if not res.passed and args.fail_fast:
            if not args.quiet:
                print(sep)
                print(f"\n[FAIL-FAST] Aborting immediately on discrepancy in '{test.id}'.")
            break

    if not args.quiet:
        print(sep + "\n")

    # Detailed Failure Inspection
    if failures > 0 and not args.quiet:
        print("❌ TIER 1 DISCREPANCY & REGRESSION AUDIT:")
        for res in results:
            if not res.passed:
                print(f"\n[PROMPT FAILURE] {res.prompt_id} ({res.category})")
                for reason in res.divergence_reason:
                    print(f"   • {reason}")
                matching_golden = next((g for g in tests if g.id == res.prompt_id), None)
                if matching_golden and matching_golden.golden_text and res.actual_text:
                    diff = difflib.unified_diff(
                        matching_golden.golden_text.splitlines(),
                        res.actual_text.splitlines(),
                        fromfile="golden_expected",
                        tofile="actual_received",
                        lineterm="",
                    )
                    diff_str = "\n".join(list(diff)[:15])
                    if diff_str:
                        print("   • Unified Text Diff (First 15 lines):")
                        print("     " + "\n     ".join(diff_str.splitlines()))

    # Dump JSON Report
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "suite": args.suite,
            "passed": failures == 0,
            "total_prompts": len(tests),
            "passed_prompts": len(tests) - failures,
            "failed_prompts": failures,
            "min_code_tps": args.min_code_tps,
            "min_reasoning_tps": args.min_reasoning_tps,
            "min_math_tps": args.min_math_tps,
            "results": [dataclasses.asdict(r) for r in results],
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        if not args.quiet:
            print(f"Report written to: {args.json_out}")

    if failures == 0:
        if not args.quiet:
            print("======================================================================")
            print(" ✅ TIER 1 PARITY & SPEED GATE PASSED: Bit-exact parity & speed confirmed!")
            print("======================================================================")
        return 0
    else:
        if not args.quiet:
            print("======================================================================")
            print(f" ❌ TIER 1 GATE FAILED: {failures} prompt(s) diverged or regressed below floor.")
            print("======================================================================")
        return 2


if __name__ == "__main__":
    sys.exit(main())
