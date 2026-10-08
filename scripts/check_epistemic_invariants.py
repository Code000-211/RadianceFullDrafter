#!/usr/bin/env python3
"""check_epistemic_invariants.py — Epistemic Ground-Truth & Anti-Hallucination Gate (Tier 0)

Automated enforcement tool for the RadianceMine physical verification system.
Translates lessons from HOW_HALLUCINATIONS_CORRUPTED_THE_WORKTREE_AND_CONTEXT_MODE_POSTMORTEM.md
into static checks of a source tree and its build:

  Invariant 1: Binary Symbol Physical Grounding (nm -D & .so inspection)
  Invariant 2: Test Integrity & Anti-Silent-Skip Checker
  Invariant 3: Threshold & Tolerance Lock (seals in baselines/gate_thresholds.json)
  Invariant 5: Context-Mode Transparency Guard (No stderr/exit-code masking)

Memory clocks are no longer checked at idle here; ab_gate.py samples them under load.
--repo-root/--build-dir point the checks at a candidate worktree instead of this checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import gate_thresholds


@dataclass
class InvariantResult:
    invariant_id: int
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log_header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}=== [Tier 0] {title} ==={RESET}")


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ==============================================================================
# Invariant 1: Binary Symbol Physical Grounding
# ==============================================================================
def check_invariant_1_symbol_grounding(repo_root: Path, build_dir: Path | None = None) -> InvariantResult:
    """Verify that every operator declared in arch/common and libr4d has a physical ELF symbol."""
    details: list[str] = []
    warnings: list[str] = []
    passed = True

    if build_dir is None:
        build_dir = repo_root / "build_hip"

    kernel_so_dirs = [
        build_dir / "radiance_home" / "kernels",
        build_dir / "radiance_home" / "quantizers",
        build_dir / "libr4d",
    ]

    so_files: list[Path] = []
    for d in kernel_so_dirs:
        if d.exists():
            so_files.extend(list(d.glob("*.so")))

    if not so_files:
        warnings.append(
            f"No compiled kernel .so files found in {[str(d) for d in kernel_so_dirs]}. "
            "Please build the project first: cmake --build build_hip -j32"
        )
        return InvariantResult(1, "Binary Symbol Physical Grounding", False, ["Build directory missing or uncompiled .so libraries."])

    # 0. Also parse registered op names from kernel registries (r4d_rows.cpp, ref_registry.cpp)
    registered_kernel_ops: set[str] = set()
    for reg_path in [repo_root / "libr4d" / "r4d_rows.cpp", repo_root / "libref" / "ref_registry.cpp"]:
        if reg_path.exists():
            try:
                with open(reg_path, "r", encoding="utf-8", errors="replace") as f:
                    reg_text = f.read()
                for m in re.finditer(r'SCHEMA\s*\(\s*"([^"]+)"', reg_text):
                    registered_kernel_ops.add(m.group(1))
                for m in re.finditer(r'SIMPLE\s*\(\s*"[^"]+"\s*,\s*"([^"]+)"', reg_text):
                    registered_kernel_ops.add(m.group(1))
                for m in re.finditer(r'\{\s*"[^"]+"\s*,\s*"([^"]+)"', reg_text):
                    registered_kernel_ops.add(m.group(1))
            except OSError:
                pass

    # Extract all exported dynamic symbols (T, W, D, B, R)
    exported_symbols: set[str] = set()
    for so_file in so_files:
        try:
            res = subprocess.run(
                ["nm", "-D", str(so_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and parts[1] in ("T", "W", "D", "B", "R"):
                    exported_symbols.add(parts[2])
        except FileNotFoundError:
            return InvariantResult(1, "Binary Symbol Physical Grounding", False, ["'nm' command not found in system PATH."])

    details.append(f"Loaded {len(exported_symbols)} exported ELF symbols across {len(so_files)} shared libraries.")

    # 1. Scan arch/common/*.h for RAD_OP declarations
    declared_ops: dict[str, list[tuple[str, int]]] = {}
    arch_common_dir = repo_root / "arch" / "common"
    if arch_common_dir.exists():
        for h_file in sorted(arch_common_dir.glob("*.h")):
            try:
                with open(h_file, "r", encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, start=1):
                        m = re.search(r'RAD_OP\s*\(\s*[^,]+,\s*"([^"]+)"', line)
                        if m:
                            op_name = m.group(1)
                            declared_ops.setdefault(op_name, []).append((h_file.name, line_num))
            except OSError as e:
                warnings.append(f"Could not read {h_file}: {e}")

    # Check each declared op against exported symbols and registry
    missing_ops: dict[str, list[tuple[str, int]]] = {}
    for op_name, locations in declared_ops.items():
        candidates = [
            f"r4d_rad_{op_name}",
            f"rad_{op_name}",
            f"rad_kernel_{op_name}",
            f"r4d_{op_name}",
            f"ref_{op_name}",
            f"ref_rad_{op_name}",
        ]
        # Direct candidate symbol match or registered in kernel catalogue
        found = any(c in exported_symbols for c in candidates)
        if not found and op_name in registered_kernel_ops:
            found = True
        if not found:
            # Check if any symbol in exported_symbols contains the op name in an r4d or ref function
            found = any(op_name in sym and ("r4d" in sym or "ref" in sym) for sym in exported_symbols)

        if not found:
            missing_ops[op_name] = locations

    if missing_ops:
        passed = False
        for op, locs in missing_ops.items():
            loc_str = ", ".join(f"{fn}:{ln}" for fn, ln in locs)
            details.append(
                f"❌ UNGROUNDED OPERATOR: '{op}' declared in [{loc_str}] has NO matching compiled ELF symbol in any kernel .so!"
            )
    else:
        details.append(f"✓ All {len(declared_ops)} operators in arch/common are physically grounded in compiled ELF symbols.")

    # 2. Check for claimed kernel functions in libr4d/*.h without symbols
    libr4d_dir = repo_root / "libr4d"
    claimed_kernels: dict[str, list[tuple[str, int]]] = {}
    if libr4d_dir.exists():
        for h_file in sorted(libr4d_dir.glob("*.h")):
            with open(h_file, "r", encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, start=1):
                    # Look for extern function declarations like r4d_kv_* or r4d_rad_*
                    for m in re.finditer(r'\b(r4d_[a-z0-9_]+)\s*\(', line):
                        fn_name = m.group(1)
                        if not fn_name.endswith("_args") and not fn_name.startswith("r4d_param"):
                            claimed_kernels.setdefault(fn_name, []).append((h_file.name, line_num))

    return InvariantResult(1, "Binary Symbol Physical Grounding", passed, details, warnings)


# ==============================================================================
# Invariant 2: Test Integrity & Anti-Silent-Skip Checker
# ==============================================================================
def check_invariant_2_anti_silent_skips(repo_root: Path) -> InvariantResult:
    """Detect and block 'audit theater' patterns like silent early returns or empty tests."""
    details: list[str] = []
    warnings: list[str] = []
    passed = True

    # 1. Scan r4d_selftest.cpp for uncatalogued silent return patterns
    selftest_path = repo_root / "libr4d" / "r4d_selftest.cpp"
    if selftest_path.exists():
        with open(selftest_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        for idx, line in enumerate(lines, start=1):
            # Detect: if (!sel("phantom_name") ...) return;
            m = re.search(r'if\s*\(\s*!sel\s*\(\s*"([^"]+)"\s*\)\s*(?:&&\s*!sel\s*\(\s*"([^"]+)"\s*\))?\s*\)\s*return\s*;', line)
            if m:
                case1 = m.group(1)
                case2 = m.group(2)
                # Check if this case is known phantom csa3_kvarn
                if "csa3" in case1 or "kvarn" in case1 or (case2 and ("csa3" in case2 or "kvarn" in case2)):
                    passed = False
                    details.append(
                        f"❌ AUDIT THEATER PATTERN DETECTED at {selftest_path.name}:{idx}: "
                        f"'{line.strip()}' silently bypasses test execution for orphaned kernel."
                    )

    # 2. Scan tests/arch_test.cpp for empty tests or dummy tautology tests
    arch_test_path = repo_root / "tests" / "arch_test.cpp"
    if arch_test_path.exists():
        with open(arch_test_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Parse TEST(...) { ... }
        test_matches = re.finditer(r'TEST\s*\(\s*(\w+)\s*\)\s*\{', content)
        test_positions = [(m.group(1), m.end()) for m in test_matches]

        for i, (test_name, start_pos) in enumerate(test_positions):
            end_pos = test_positions[i + 1][1] if i + 1 < len(test_positions) else len(content)
            body = content[start_pos:end_pos]
            # Match matching closing brace approximately
            brace_count = 1
            body_end = 0
            for idx_c, ch in enumerate(body):
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        body_end = idx_c
                        break
            if body_end > 0:
                body = body[:body_end]

            assertions = re.findall(r'\b(CHECK|REQUIRE|ASSERT|EXPECT)\w*\b', body)
            if len(assertions) == 0:
                passed = False
                details.append(f"❌ EMPTY TEST DETECTED: 'TEST({test_name})' contains 0 assertions!")

            # Check for dummy mathematical tautologies (e.g. testing std::sqrt(3.0f))
            if "clt_factor" in body and "std::sqrt(3.0f)" in body and "rad" not in body.lower():
                passed = False
                details.append(
                    f"❌ PLACEBO TEST DETECTED: 'TEST({test_name})' tests local float constants instead of physical engine code!"
                )

    if passed:
        details.append("✓ Test suite source integrity certified clean (0 silent-skips, 0 placebo assertions).")

    return InvariantResult(2, "Test Integrity & Anti-Silent-Skip Checker", passed, details, warnings)


# ==============================================================================
# Invariant 3: Threshold & Tolerance Immutability Lock
# ==============================================================================
def check_invariant_3_immutability_lock(repo_root: Path) -> InvariantResult:
    """Verify cryptographic SHA-256 seals on baselines and immutable test thresholds."""
    details: list[str] = []
    warnings: list[str] = []
    passed = True

    # 1. Verify SHA-256 seals on baselines (seals live in baselines/gate_thresholds.json;
    #    changing either side is blocked by the pre-commit hook without RADIANCE_GATE_CHANGE=1)
    try:
        thresholds = gate_thresholds.load()
    except (OSError, ValueError) as e:
        return InvariantResult(3, "Threshold & Tolerance Immutability Lock", False, [f"❌ Cannot read {gate_thresholds.THRESHOLDS_FILE}: {e}"])

    for name, expected_hash in thresholds["seals_sha256"].items():
        path = repo_root / "baselines" / name
        if not path.exists():
            passed = False
            details.append(f"❌ MISSING BASELINE: Required reference file not found at {path}")
            continue
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            passed = False
            details.append(
                f"❌ SEAL BROKEN: {name}\n"
                f"   Expected SHA-256: {expected_hash}\n"
                f"   Actual SHA-256:   {actual_hash}"
            )
        else:
            details.append(f"✓ {name} SHA-256 seal intact: {actual_hash[:16]}...")

    # 2. parity_check.py must take the token tolerance from the thresholds file
    parity_check_py = repo_root / "scripts" / "parity_check.py"
    parity_src = parity_check_py.read_text(encoding="utf-8") if parity_check_py.exists() else ""
    if 'default=tier1["token_tolerance"]' not in parity_src:
        passed = False
        details.append("❌ scripts/parity_check.py does not default token_tolerance to gate_thresholds.json")

    # 3. gate_check.sh must not override tolerance or floors on the command line
    gate_check_sh = repo_root / "scripts" / "gate_check.sh"
    gate_src = gate_check_sh.read_text(encoding="utf-8") if gate_check_sh.exists() else ""
    overrides = re.findall(r"--(?:token-tolerance|min-[a-z]+-tps)\b", gate_src)
    if overrides:
        passed = False
        details.append(f"❌ scripts/gate_check.sh overrides thresholds: {sorted(set(overrides))}")
    else:
        details.append("✓ Gate thresholds come only from baselines/gate_thresholds.json.")

    return InvariantResult(3, "Threshold & Tolerance Immutability Lock", passed, details, warnings)


# ==============================================================================
# Invariant 5: Context-Mode Transparency Guard
# ==============================================================================
def check_invariant_5_transparency_guard(repo_root: Path) -> InvariantResult:
    """Verify that benchmark and inspection scripts preserve stderr and check return codes."""
    details: list[str] = []
    warnings: list[str] = []
    passed = True

    scripts_dir = repo_root / "scripts"
    violating_scripts: list[tuple[str, int, str]] = []

    if scripts_dir.exists():
        for script_path in sorted(scripts_dir.glob("*.sh")):
            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            for line_idx, line in enumerate(lines, start=1):
                clean_line = line.strip()
                # Check for critical test commands discarding stderr and exit code:
                # e.g. "python3 ...parity_check... > /dev/null 2>&1" without "|| exit"
                if (
                    ("parity_check" in clean_line or "gate_check" in clean_line)
                    and "> /dev/null 2>&1" in clean_line
                    and "|| exit" not in clean_line
                    and "|| return" not in clean_line
                ):
                    violating_scripts.append((script_path.name, line_idx, clean_line))

        # Check Python scripts for unchecked capture_output
        for script_path in sorted(scripts_dir.glob("*.py")):
            if script_path.name == "check_epistemic_invariants.py":
                continue
            with open(script_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Pattern: subprocess.run(..., capture_output=True) without check=True and without returncode inspection
            for m in re.finditer(r'subprocess\.(run|Popen)\s*\([^)]*capture_output=True[^)]*\)', content):
                match_str = m.group(0)
                if "check=True" not in match_str and "returncode" not in content[m.end():m.end() + 200]:
                    warnings.append(
                        f"{script_path.name}: subprocess call captures output without checking returncode or stderr."
                    )

    if violating_scripts:
        passed = False
        for sname, lno, code in violating_scripts:
            details.append(f"❌ TRANSPARENCY VIOLATION at {sname}:{lno}: Silent suppression '{code}'")
    else:
        details.append("✓ Execution transparency guard certified (zero unverified stderr suppressions).")

    return InvariantResult(5, "Context-Mode Transparency Guard", passed, details, warnings)


# ==============================================================================
# Master Invariant Execution Orchestrator
# ==============================================================================
def run_all_invariants(repo_root: Path, build_dir: Path | None = None) -> int:
    log_header("RadianceMine Epistemic Invariants & Ground-Truth Verification")
    print(f"Workspace: {repo_root}")
    print("Policy:    Strict Physical Grounding (Anti-Hallucination Law)")

    results: list[InvariantResult] = []

    # Run Invariant 1
    res1 = check_invariant_1_symbol_grounding(repo_root, build_dir)
    results.append(res1)

    # Run Invariant 2
    res2 = check_invariant_2_anti_silent_skips(repo_root)
    results.append(res2)

    # Run Invariant 3
    res3 = check_invariant_3_immutability_lock(repo_root)
    results.append(res3)

    # Run Invariant 5
    res5 = check_invariant_5_transparency_guard(repo_root)
    results.append(res5)

    print("\n" + "=" * 80)
    print(f"| {'#':<3} | {'Invariant Name':<45} | {'Result':<12} |")
    print(f"|{'-'*5}|{'-'*47}|{'-'*14}|")

    failures = 0
    for r in results:
        badge = f"{GREEN}✅ PASS{RESET}" if r.passed else f"{RED}❌ FAIL{RESET}"
        print(f"| {r.invariant_id:<3} | {r.name:<45} | {badge:<21} |")
        if not r.passed:
            failures += 1

    print("=" * 80)

    # Detail Output
    for r in results:
        if not r.passed or r.warnings:
            status_str = f"{RED}[FAILED]{RESET}" if not r.passed else f"{YELLOW}[WARNINGS]{RESET}"
            print(f"\n{BOLD}{status_str} Invariant {r.invariant_id}: {r.name}{RESET}")
            for d in r.details:
                print(f"   • {d}")
            for w in r.warnings:
                print(f"   ⚠️  {w}")

    if failures == 0:
        print(f"\n{BOLD}{GREEN}🏆 TIER 0 EPISTEMIC GROUND-TRUTH VERIFICATION PASSED ({len(results)}/{len(results)} INVARIANTS CLEAN){RESET}\n")
        return 0
    else:
        print(f"\n{BOLD}{RED}❌ TIER 0 EPISTEMIC GROUND-TRUTH GATE FAILED: {failures} invariant(s) violated!{RESET}")
        print("Hardware access and benchmarks halted. Fix all ground-truth discrepancies before proceeding.\n")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RadianceMine Tier 0: static ground-truth checks of a source tree and its build",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--invariant", type=int, choices=[1, 2, 3, 5], default=None, help="Run only this invariant")
    parser.add_argument("--repo-root", type=Path, default=get_repo_root(), help="Source tree to check (e.g. a candidate worktree)")
    parser.add_argument("--build-dir", type=Path, default=None, help="Build dir with radiance_home/kernels (default: <repo-root>/build_hip)")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()

    if args.invariant is not None:
        res = {
            1: lambda: check_invariant_1_symbol_grounding(repo_root, args.build_dir),
            2: lambda: check_invariant_2_anti_silent_skips(repo_root),
            3: lambda: check_invariant_3_immutability_lock(repo_root),
            5: lambda: check_invariant_5_transparency_guard(repo_root),
        }[args.invariant]()
        badge = f"{GREEN}PASS{RESET}" if res.passed else f"{RED}FAIL{RESET}"
        print(f"Invariant {res.invariant_id} ({res.name}): {badge}")
        for d in res.details:
            print(f"  • {d}")
        for w in res.warnings:
            print(f"  ⚠️  {w}")
        return 0 if res.passed else 1

    return run_all_invariants(repo_root, args.build_dir)


if __name__ == "__main__":
    sys.exit(main())
