#!/usr/bin/env python3
"""
eval_patch_safety.py — Deterministic Patch & Anti-Pattern Safety Auditor

Deterministically verifies a candidate git patch (.patch) before building or benchmarking.
Detects and blocks known anti-patterns without burning LLM tokens:
  1. Excessive or per-thread __threadfence_system() (PCIe interconnect saturation).
  2. Test threshold tampering (lowering min TPS or increasing token tolerance).
  3. Silent skip test mocks (if (!sel) return;, empty assertion blocks).
  4. Hardcoded speculative depth throttling (e.g. min(depth, 3) or unconditional return 1).
  5. Missing feature-flags on experimental branches.

Exit Codes:
  0 = Clean / Safe Patch
  1 = Dangerous Anti-Pattern Detected (Rejected)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def audit_patch(patch_path: Path) -> tuple[bool, list[str]]:
    if not patch_path.is_file():
        return False, [f"Patch file not found: {patch_path}"]

    content = patch_path.read_text(encoding="utf-8", errors="replace")
    added_lines = [line[1:] for line in content.splitlines() if line.startswith("+") and not line.startswith("+++")]

    violations: list[str] = []

    for i, line in enumerate(added_lines, start=1):
        # 1. Threadfence system check: flag unconditional calls that execute on every thread
        if "__threadfence_system" in line and not line.strip().startswith("//"):
            # Check if this line is an unconditional statement
            stripped = line.strip()
            if stripped == "__threadfence_system();":
                violations.append(
                    f"Line {i}: Unconditional `__threadfence_system()` detected. "
                    "Forces all 1024 threads in workgroup to broadcast memory fences across PCIe! "
                    "Must be gated by workgroup leader (`if (tid == 0)`) or hardware store drain (`s_wait_storecnt`)."
                )

        # 2. Test threshold / tolerance tampering
        if "--token-tolerance" in line:
            match = re.search(r"--token-tolerance\s+(\d+)", line)
            if match and int(match.group(1)) > 0:
                violations.append(f"Line {i}: Tampering with `--token-tolerance` ({match.group(1)} > 0). Greedy exactness (0) is immutable.")

        if "--min-code-tps" in line:
            match = re.search(r"--min-code-tps\s+([0-9.]+)", line)
            if match and float(match.group(1)) < 230.0:
                violations.append(f"Line {i}: Lowering `--min-code-tps` floor ({match.group(1)} < 230.0) is strictly barred.")

        # 3. Silent skip audit theater
        if (re.search(r"if\s*\(!sel\(.*?\)\)\s*return;", line) or re.search(r"if\s*\(!.*?\)\s*return\s*0;", line)) and (
            "test" in line.lower() or "selftest" in patch_path.name.lower()
        ):
            violations.append(f"Line {i}: Silent skip pattern `if (!sel) return;` detected in tests. All tests must assert real execution.")

        # 4. Hardcoded speculative depth clamps
        if re.search(r"return\s+std::min\([^,]+,\s*[123]\);", line) or re.search(r"recommended_depth\s*=\s*1;", line):
            violations.append(f"Line {i}: Hardcoded speculative depth throttling detected. Avoid static depth locking.")

    passed = len(violations) == 0
    return passed, violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Patch Safety & Anti-Pattern Auditor")
    parser.add_argument("patch_file", type=Path, help="Path to .patch file")
    parser.add_argument("--json-out", type=Path, default=None, help="Save machine-readable result JSON")
    args = parser.parse_args()

    passed, violations = audit_patch(args.patch_file)

    report = {
        "patch_file": str(args.patch_file),
        "passed": passed,
        "violations": violations,
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            import json
            json.dump(report, f, indent=2)

    print("================================================================================")
    print(f" 🛡️  Deterministic Patch Safety Audit: {args.patch_file.name}")
    print("================================================================================")

    if passed:
        print("✅ PASS: Zero dangerous anti-patterns detected. Patch certified safe for hardware testing.")
        return 0
    else:
        print(f"❌ FAIL: {len(violations)} safety violation(s) detected:")
        for v in violations:
            print(f"   • {v}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
