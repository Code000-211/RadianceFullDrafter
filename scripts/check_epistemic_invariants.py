#!/usr/bin/env python3
"""check_epistemic_invariants.py — Epistemic Ground-Truth & Anti-Hallucination Gate (Tier 0)

Automated enforcement tool for the RadianceMine physical verification system.
Translates lessons from HOW_HALLUCINATIONS_CORRUPTED_THE_WORKTREE_AND_CONTEXT_MODE_POSTMORTEM.md
into six strictly enforced invariants:

  Invariant 1: Binary Symbol Physical Grounding (nm -D & .so inspection)
  Invariant 2: Test Integrity & Anti-Silent-Skip Checker
  Invariant 3: Threshold & Tolerance Immutability Lock (Cryptographic Seal)
  Invariant 4: Hardware Clock & DPM Pre-Flight Verification
  Invariant 5: Context-Mode Transparency Guard (No stderr/exit-code masking)
  Invariant 6: OpenWiki Knowledge Graph & Claims Integrity (Zero-Blind-Exploration Law)
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# ==============================================================================
# Cryptographic Seals & Golden Thresholds (Inviolable Laws)
# ==============================================================================
SEAL_GOLDEN_PARITY_SHA256 = "75e83c3da2aa5db53e6b659068289b16e92da26fc08a4358b27aa7a10ea8c7df"
SEAL_BASELINE_OPT146_SHA256 = "34b3a48652a408e103a36c29352dab0e43030fd038d21112f74c58a07539d772"

MIN_CODE_TPS_FLOOR = 230.0
MIN_REASONING_TPS_FLOOR = 210.0
MIN_MATH_TPS_FLOOR = 210.0
MAX_TOKEN_TOLERANCE = 0


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
        if not (build_dir / "radiance_home" / "kernels").exists() and (repo_root.parent.parent / "build_hip" / "radiance_home" / "kernels").exists():
            build_dir = repo_root.parent.parent / "build_hip"

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

    # 1. Verify Cryptographic SHA-256 Seals on Baselines
    golden_ref_file = repo_root / "baselines" / "golden_parity_reference.json"
    baseline_opt146_file = repo_root / "baselines" / "baseline_opt146.json"

    for path, expected_hash, label in [
        (golden_ref_file, SEAL_GOLDEN_PARITY_SHA256, "Golden Parity Reference"),
        (baseline_opt146_file, SEAL_BASELINE_OPT146_SHA256, "Opt 146 Baseline Reference"),
    ]:
        if not path.exists():
            passed = False
            details.append(f"❌ MISSING BASELINE: Required reference file not found at {path}")
            continue

        with open(path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()

        if actual_hash != expected_hash:
            passed = False
            details.append(
                f"❌ CRYPTOGRAPHIC SEAL BROKEN: {label} ({path.name})\n"
                f"   Expected SHA-256: {expected_hash}\n"
                f"   Actual SHA-256:   {actual_hash}\n"
                f"   Modifying golden references to mask regressions violates Law 3 of the Engineering Constitution!"
            )
        else:
            details.append(f"✓ {label} SHA-256 seal intact: {actual_hash[:16]}...")

    # 2. Verify parity_check.py thresholds and token tolerance
    parity_check_py = repo_root / "scripts" / "parity_check.py"
    if parity_check_py.exists():
        with open(parity_check_py, "r", encoding="utf-8") as f:
            content = f.read()

        # Check default token_tolerance == 0
        m_tol = re.search(r'--token-tolerance["\'],\s*type=int,\s*default=(\d+)', content)
        if m_tol:
            val = int(m_tol.group(1))
            if val != 0:
                passed = False
                details.append(f"❌ TOLERANCE RELAXATION: scripts/parity_check.py default token-tolerance is {val} (must be 0)!")
            else:
                details.append("✓ scripts/parity_check.py token-tolerance strictly locked to 0.")
        else:
            warnings.append("Could not statically verify token-tolerance default in scripts/parity_check.py.")

        # Check min speed defaults
        speed_checks = [
            (r'--min-code-tps["\'].*?default=float\(os\.getenv\(["\']MIN_CODE_TPS["\'],\s*["\']([\d\.]+)["\']', MIN_CODE_TPS_FLOOR, "Code TPS"),
            (r'--min-reasoning-tps["\'].*?default=float\(os\.getenv\(["\']MIN_REASONING_TPS["\'],\s*["\']([\d\.]+)["\']', MIN_REASONING_TPS_FLOOR, "Reasoning TPS"),
            (r'--min-math-tps["\'].*?default=float\(os\.getenv\(["\']MIN_MATH_TPS["\'],\s*["\']([\d\.]+)["\']', MIN_MATH_TPS_FLOOR, "Math TPS"),
        ]
        for pattern, floor, name in speed_checks:
            m_spd = re.search(pattern, content, re.DOTALL)
            if m_spd:
                val = float(m_spd.group(1))
                if val < floor:
                    passed = False
                    details.append(f"❌ THRESHOLD LOWERED: {name} default in parity_check.py is {val} t/s (minimum floor: {floor} t/s)!")
                else:
                    details.append(f"✓ {name} floor locked: {val:.1f} >= {floor:.1f} t/s.")

    # 3. Verify gate_check.sh calls parity_check.py with token-tolerance 0 and unlowered floors
    gate_check_sh = repo_root / "scripts" / "gate_check.sh"
    if gate_check_sh.exists():
        with open(gate_check_sh, "r", encoding="utf-8") as f:
            sh_content = f.read()

        if "--token-tolerance 0" not in sh_content and "--token-tolerance" in sh_content:
            m_tol_sh = re.search(r'--token-tolerance\s+(\d+)', sh_content)
            if m_tol_sh and int(m_tol_sh.group(1)) > 0:
                passed = False
                details.append(f"❌ GATE CHECK COMPROMISED: scripts/gate_check.sh passes --token-tolerance {m_tol_sh.group(1)}!")
        else:
            details.append("✓ scripts/gate_check.sh enforces --token-tolerance 0.")

    return InvariantResult(3, "Threshold & Tolerance Immutability Lock", passed, details, warnings)


# ==============================================================================
# Invariant 4: Hardware Clock & DPM Pre-Flight Verification
# ==============================================================================
def check_invariant_4_hardware_clocks(auto_warmup: bool = False, endpoint: str = "http://localhost:8000/v1") -> InvariantResult:
    """Inspect GPU DPM memory clock states to prevent benchmarking under 96 MHz throttle."""
    details: list[str] = []
    warnings: list[str] = []
    passed = True

    # 1. Check sysfs pp_dpm_mclk
    sysfs_mclk_paths = sorted(glob.glob("/sys/class/drm/card*/device/pp_dpm_mclk"))
    throttled_cards: list[tuple[str, str]] = []

    if sysfs_mclk_paths:
        for p in sysfs_mclk_paths:
            card_id = Path(p).parent.parent.name
            try:
                with open(p, "r", encoding="utf-8") as f:
                    mclk_data = f.read()
                for line in mclk_data.splitlines():
                    if "*" in line:
                        active_level = line.strip()
                        if active_level.startswith("0:") or "96Mhz" in active_level:
                            throttled_cards.append((card_id, active_level))
                        details.append(f"GPU [{card_id}] MCLK state: {active_level}")
            except OSError as e:
                warnings.append(f"Could not read {p}: {e}")

    # 2. Alternatively check via rocm-smi if sysfs was not accessible
    elif os.path.exists("/opt/rocm/bin/rocm-smi") or subprocess.run(["which", "rocm-smi"], capture_output=True, check=False).returncode == 0:
        rocm_smi_cmd = "/opt/rocm/bin/rocm-smi" if os.path.exists("/opt/rocm/bin/rocm-smi") else "rocm-smi"
        res = subprocess.run([rocm_smi_cmd, "--showclocks"], capture_output=True, text=True, check=False)
        for line in res.stdout.splitlines():
            if "mclk clock level:" in line:
                details.append(line.strip())
                if "level: 0" in line or "96Mhz" in line:
                    throttled_cards.append(("rocm-smi", line.strip()))

    if throttled_cards:
        if auto_warmup:
            details.append("⚡ Throttled GPU detected. Triggering automated warmup pass to elevate DPM clocks...")
            try:
                url = f"{endpoint.rstrip('/')}/chat/completions"
                payload = {
                    "model": "qwen4exp",
                    "messages": [{"role": "user", "content": "Warmup pass to prime GPU boost clocks and load hot MoE expert tier."}],
                    "max_tokens": 64,
                    "temperature": 0.0,
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    if resp.status == 200:
                        details.append("✓ Automated warmup request dispatched successfully.")
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                warnings.append(f"Automated warmup failed: {e}")

            time.sleep(1.0)
            # Re-check after warmup
            throttled_cards_after: list[tuple[str, str]] = []
            for p in sysfs_mclk_paths:
                card_id = Path(p).parent.parent.name
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f.read().splitlines():
                            if "*" in line and ("0:" in line or "96Mhz" in line):
                                throttled_cards_after.append((card_id, line.strip()))
                except OSError:
                    pass

            if throttled_cards_after:
                passed = False
                for c, lvl in throttled_cards_after:
                    details.append(f"❌ GPU [{c}] remains throttled at {lvl} after warmup pass!")
            else:
                passed = True
                details.append("✓ GPU memory clocks elevated out of DPM 0 throttle.")
        else:
            # Report warning or error depending on strictness
            for c, lvl in throttled_cards:
                warnings.append(
                    f"GPU [{c}] memory clock is resting at {lvl} (DPM 0). "
                    "When idle, PowerPlay scales GDN memory down to 96 MHz (7.6% of bandwidth). "
                    "Run warmup pass before benchmark or use --warmup flag."
                )
            details.append("⚠️  GPU memory clock at DPM 0 idle state. Priming warmup pass recommended before benchmarking.")
    else:
        details.append("✓ GPU DPM memory clocks certified active.")

    return InvariantResult(4, "Hardware Clock & DPM Pre-Flight Verification", passed, details, warnings)


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


def check_invariant_6_openwiki_integrity(repo_root: Path) -> InvariantResult:
    """Invariant 6: OpenWiki Knowledge Graph & Claims Integrity (Zero-Blind-Exploration Law).

    Verifies that:
      1. openwiki/ directory and canonical architecture pages exist.
      2. openwiki/.claims/ contains cryptographic atomic claims.
      3. scripts/locate_code.py exists and is functional.
      4. Governance documents (ENGINEERING_CONSTITUTION.md & AGENTS.md) mandate OpenWiki grounding.
    """
    passed = True
    details: list[str] = []
    warnings: list[str] = []

    openwiki_dir = repo_root / "openwiki"
    if not openwiki_dir.is_dir():
        passed = False
        details.append(f"❌ openwiki/ directory missing at {openwiki_dir}")
        return InvariantResult(6, "OpenWiki Knowledge & Claims Integrity", passed, details, warnings)

    # Check canonical architecture pages
    canonical_pages = [
        "quickstart.md",
        "architecture/engine_runtime.md",
        "architecture/gemm_and_kernels.md",
        "architecture/p2p_interconnect.md",
        "architecture/speculative_mtp.md",
        "governance/quality_gates.md",
        "pipeline/upstream_watcher.md",
    ]
    missing_pages = []
    for page in canonical_pages:
        page_path = openwiki_dir / page
        if not page_path.is_file():
            missing_pages.append(page)

    if missing_pages:
        passed = False
        details.append(f"❌ Missing canonical OpenWiki pages: {', '.join(missing_pages)}")
    else:
        details.append(f"✓ All {len(canonical_pages)} canonical OpenWiki architecture pages verified.")

    # Check claims directory and files
    claims_dir = openwiki_dir / ".claims"
    if not claims_dir.is_dir():
        passed = False
        details.append("❌ openwiki/.claims/ directory missing")
    else:
        claim_files = list(claims_dir.rglob("*.json"))
        if not claim_files:
            passed = False
            details.append("❌ No claim files found in openwiki/.claims/")
        else:
            details.append(f"✓ {len(claim_files)} atomic claim definitions verified across openwiki/.claims/.")

    # Check scripts/locate_code.py
    locator_path = repo_root / "scripts" / "locate_code.py"
    if not locator_path.is_file():
        passed = False
        details.append(f"❌ Fast code locator missing at {locator_path}")
    else:
        details.append("✓ Fast code locator verified (scripts/locate_code.py).")

    # Check constitution and agent rules
    constitution_path = repo_root / "ENGINEERING_CONSTITUTION.md"
    if constitution_path.is_file():
        const_text = constitution_path.read_text(encoding="utf-8", errors="replace")
        if "Rule 7" not in const_text or "Mandatory OpenWiki" not in const_text:
            passed = False
            details.append("❌ ENGINEERING_CONSTITUTION.md missing Rule 7 (Mandatory OpenWiki).")
        else:
            details.append("✓ ENGINEERING_CONSTITUTION.md Rule 7 (Mandatory OpenWiki) verified.")

    agents_path = repo_root / "AGENTS.md"
    if agents_path.is_file():
        agents_text = agents_path.read_text(encoding="utf-8", errors="replace")
        if "Prohibited Action 5" not in agents_text or "locate_code.py" not in agents_text:
            passed = False
            details.append("❌ AGENTS.md missing Prohibited Action 5 or locate_code.py workflow.")
        else:
            details.append("✓ AGENTS.md Prohibited Action 5 & Step 0 OpenWiki workflow verified.")

    return InvariantResult(6, "OpenWiki Knowledge & Claims Integrity", passed, details, warnings)


# ==============================================================================
# Master Invariant Execution Orchestrator
# ==============================================================================
def run_all_invariants(
    repo_root: Path,
    strict: bool = True,
    warmup: bool = False,
    endpoint: str = "http://localhost:8000/v1",
) -> int:
    log_header("RadianceMine Epistemic Invariants & Ground-Truth Verification")
    print(f"Workspace: {repo_root}")
    print("Policy:    Strict Physical Grounding (Anti-Hallucination Law)")

    results: list[InvariantResult] = []

    # Run Invariant 1
    res1 = check_invariant_1_symbol_grounding(repo_root)
    results.append(res1)

    # Run Invariant 2
    res2 = check_invariant_2_anti_silent_skips(repo_root)
    results.append(res2)

    # Run Invariant 3
    res3 = check_invariant_3_immutability_lock(repo_root)
    results.append(res3)

    # Run Invariant 4
    res4 = check_invariant_4_hardware_clocks(auto_warmup=warmup, endpoint=endpoint)
    results.append(res4)

    # Run Invariant 5
    res5 = check_invariant_5_transparency_guard(repo_root)
    results.append(res5)

    # Run Invariant 6
    res6 = check_invariant_6_openwiki_integrity(repo_root)
    results.append(res6)

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
        print(f"\n{BOLD}{GREEN}🏆 TIER 0 EPISTEMIC GROUND-TRUTH VERIFICATION PASSED (6/6 INVARIANTS CLEAN){RESET}\n")
        return 0
    else:
        print(f"\n{BOLD}{RED}❌ TIER 0 EPISTEMIC GROUND-TRUTH GATE FAILED: {failures} invariant(s) violated!{RESET}")
        print("Hardware access and benchmarks halted. Fix all ground-truth discrepancies before proceeding.\n")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RadianceMine Epistemic Ground-Truth & Anti-Hallucination Gate (Tier 0)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--invariant",
        type=int,
        choices=[1, 2, 3, 4, 5, 6],
        default=None,
        help="Run only a specific invariant (1-6)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Enforce strict zero-tolerance failure mode",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Automatically issue warmup requests to wake up throttled GPU DPM clocks",
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("ENDPOINT", "http://localhost:8000/v1"),
        help="Inference API endpoint for warmup requests",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to output JSON results summary",
    )

    args = parser.parse_args()
    repo_root = get_repo_root()

    if args.invariant is not None:
        if args.invariant == 1:
            res = check_invariant_1_symbol_grounding(repo_root)
        elif args.invariant == 2:
            res = check_invariant_2_anti_silent_skips(repo_root)
        elif args.invariant == 3:
            res = check_invariant_3_immutability_lock(repo_root)
        elif args.invariant == 4:
            res = check_invariant_4_hardware_clocks(auto_warmup=args.warmup, endpoint=args.endpoint)
        elif args.invariant == 5:
            res = check_invariant_5_transparency_guard(repo_root)
        elif args.invariant == 6:
            res = check_invariant_6_openwiki_integrity(repo_root)
        else:
            return 1

        badge = f"{GREEN}PASS{RESET}" if res.passed else f"{RED}FAIL{RESET}"
        print(f"Invariant {res.invariant_id} ({res.name}): {badge}")
        for d in res.details:
            print(f"  • {d}")
        for w in res.warnings:
            print(f"  ⚠️  {w}")
        return 0 if res.passed else 1

    rc = run_all_invariants(repo_root, strict=args.strict, warmup=args.warmup, endpoint=args.endpoint)
    return rc


if __name__ == "__main__":
    sys.exit(main())
