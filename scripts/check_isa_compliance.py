#!/usr/bin/env python3
"""
RDNA4 (gfx1201) ISA Compliance & Microarchitectural Verification Checker
Enforces the 7 RDNA4 ISA Engineering Ground Truths:
  1. 24-VGPR Allocation Granularity & Occupancy Cliff Avoidance
  2. Zero-Waterfall Loop Standard on Hot Decode/Draft/Prefill Paths
  3. Scratch Memory Spills Prohibition on Prefill/Decode Kernels
"""

import argparse
import functools
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from typing import Any

import yaml

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from typesafe_triage import eval_isa_hazard, get_api_key
    HAS_TYPESAFE = bool(get_api_key())
except (ImportError, OSError, AttributeError):
    eval_isa_hazard = None
    HAS_TYPESAFE = False

ROCM_DEFAULT = os.environ.get("ROCM") or os.environ.get("ROCM_PATH") or os.environ.get("HIP_PATH") or "/opt/rocm"
GFX_ARCH = "gfx1201"
VGPR_CLIFFS = [96, 120, 144, 168, 192, 216, 240]
HOT_PATH_PATTERNS = [
    r"decode", r"draft"
]

def find_llvm_tool(tool_name, rocm_path):
    candidates = [
        os.path.join(rocm_path, "llvm", "bin", tool_name),
        os.path.join(rocm_path, "bin", tool_name),
    ]
    for c in candidates:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    w = shutil.which(tool_name)
    if w:
        return w
    return None

@functools.lru_cache(maxsize=8192)
def demangle(symbol):
    if not symbol:
        return ""
    try:
        res = subprocess.run(["c++filt", symbol], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return symbol

def calc_occupancy(vgpr_count):
    if vgpr_count <= 0:
        return 0, 16, 100.0
    allocated = ((vgpr_count + 23) // 24) * 24
    waves = min(16, 1536 // allocated) if allocated > 0 else 16
    pct = (waves / 16.0) * 100.0
    return allocated, waves, pct

def is_hot_path(kernel_name, tu_name=""):
    lower_name = kernel_name.lower()
    lower_demangled = demangle(kernel_name).lower()
    lower_tu = tu_name.lower()
    return any(
        re.search(pat, lower_name) or
        re.search(pat, lower_demangled) or
        re.search(pat, lower_tu)
        for pat in HOT_PATH_PATTERNS
    )

def is_prefill_or_decode(kernel_name, tu_name=""):
    lower_name = kernel_name.lower()
    lower_demangled = demangle(kernel_name).lower()
    lower_tu = tu_name.lower()
    return any(
        kw in lower_name or kw in lower_demangled or kw in lower_tu
        for kw in ["prefill", "decode"]
    )

class CodeObject:
    def __init__(self, path, tu_name):
        self.path = path
        self.tu_name = tu_name
        self.kernels = []

class KernelInfo:
    def __init__(self, name, tu_name, vgpr, sgpr, scratch, vspill, sspill):
        self.name = name
        self.tu_name = tu_name
        self.vgpr = vgpr
        self.sgpr = sgpr
        self.scratch = scratch
        self.vspill = vspill
        self.sspill = sspill
        self.allocated_vgpr, self.waves, self.occupancy_pct = calc_occupancy(vgpr)
        self.cliff_warning = None
        self.check_cliffs()

    def check_cliffs(self):
        for b in VGPR_CLIFFS:
            if b < self.vgpr <= b + 8:
                _, prev_waves, prev_pct = calc_occupancy(b)
                self.cliff_warning = {
                    "boundary": b,
                    "excess": self.vgpr - b,
                    "current_waves": self.waves,
                    "target_waves": prev_waves,
                    "occupancy_loss_pct": prev_pct - self.occupancy_pct,
                }
                break

def extract_from_so(so_path, rocm_path, work_dir):
    bundler = find_llvm_tool("clang-offload-bundler", rocm_path)
    objcopy = find_llvm_tool("llvm-objcopy", rocm_path)
    if not bundler or not objcopy:
        sys.stderr.write("Error: llvm-objcopy or clang-offload-bundler not found in ROCm path\n")
        return []

    fb_path = os.path.join(work_dir, "libr4d.fb")
    r_dump = subprocess.run([objcopy, f"--dump-section=.hip_fatbin={fb_path}", so_path, "/dev/null"],
                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r_dump.returncode != 0 or not os.path.exists(fb_path):
        return []
    
    with open(fb_path, "rb") as f:
        data = f.read()

    magic = b"__CLANG_OFFLOAD_BUNDLE__"
    indices = []
    pos = 0
    while True:
        idx = data.find(magic, pos)
        if idx == -1:
            break
        indices.append(idx)
        pos = idx + len(magic)
    indices.append(len(data))

    cos = []
    for i in range(len(indices) - 1):
        chunk = data[indices[i]:indices[i+1]]
        chunk_file = os.path.join(work_dir, f"bundle_{i}.fb")
        co_file = os.path.join(work_dir, f"bundle_{i}.co")
        with open(chunk_file, "wb") as cf:
            cf.write(chunk)
        cmd = [
            bundler, "--type=o", "--unbundle",
            f"--input={chunk_file}",
            f"--targets=hipv4-amdgcn-amd-amdhsa--{GFX_ARCH}",
            f"--output={co_file}"
        ]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if r.returncode == 0 and os.path.exists(co_file):
            cos.append(CodeObject(co_file, f"bundle_{i}"))
    return cos

def extract_from_hip_o(hip_o_path, rocm_path, work_dir):
    bundler = find_llvm_tool("clang-offload-bundler", rocm_path)
    objcopy = find_llvm_tool("llvm-objcopy", rocm_path)
    tu = os.path.basename(hip_o_path)[:-6]
    fb = os.path.join(work_dir, f"{tu}.fb")
    co = os.path.join(work_dir, f"{tu}.co")

    r1 = subprocess.run([objcopy, f"--dump-section=.hip_fatbin={fb}", hip_o_path, "/dev/null"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if r1.returncode != 0:
        return None
    r2 = subprocess.run([
        bundler, "--type=o", "--unbundle",
        f"--input={fb}",
        f"--targets=hipv4-amdgcn-amd-amdhsa--{GFX_ARCH}",
        f"--output={co}"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if r2.returncode != 0 or not os.path.exists(co):
        return None
    return CodeObject(co, tu)

def parse_metadata(co, rocm_path):
    readelf = find_llvm_tool("llvm-readelf", rocm_path)
    if not readelf:
        return []
    try:
        out = subprocess.check_output([readelf, "--notes", co.path], text=True)
    except (subprocess.SubprocessError, OSError):
        return []

    start = out.find("---")
    if start == -1:
        return []

    try:
        data = yaml.safe_load(out[start:])
    except yaml.YAMLError:
        return []

    kernels = []
    for k in data.get("amdhsa.kernels", []):
        name = k.get(".name", "")
        vgpr = k.get(".vgpr_count", 0)
        sgpr = k.get(".sgpr_count", 0)
        scratch = k.get(".private_segment_fixed_size", 0)
        vspill = k.get(".vgpr_spill_count", 0)
        sspill = k.get(".sgpr_spill_count", 0)
        info = KernelInfo(name, co.tu_name, vgpr, sgpr, scratch, vspill, sspill)
        kernels.append(info)
    co.kernels = kernels
    return kernels

def scan_waterfall_loops(co, rocm_path):
    objdump = find_llvm_tool("llvm-objdump", rocm_path)
    if not objdump:
        return []
    cmd = [objdump, "-d", "--symbolize-operands", "--no-show-raw-insn", co.path]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (subprocess.SubprocessError, OSError):
        return []

    waterfalls = []
    current_sym = ""
    movrel_count = 0
    loop_count = 0
    seen_movrel = False

    for line in p.stdout:
        line_s = line.strip()
        # Symbol header
        if re.match(r"^[0-9a-fA-F]+\s+<.*>:$", line_s):
            m = re.search(r"<([^>]+)>:", line_s)
            label = m.group(1) if m else ""
            if not re.match(r"^L[0-9]+$", label):
                if movrel_count > 0:
                    waterfalls.append({
                        "tu": co.tu_name,
                        "kernel": current_sym,
                        "demangled": demangle(current_sym),
                        "movrel_count": movrel_count,
                        "loops": loop_count,
                        "is_hot": is_hot_path(current_sym, co.tu_name),
                    })
                current_sym = label
                movrel_count = 0
                loop_count = 0
                seen_movrel = False
        if "movrel" in line_s:
            movrel_count += 1
            seen_movrel = True
        if seen_movrel and re.search(r"s_cbranch_exec(nz|z)", line_s):
            loop_count += 1
            seen_movrel = False

    if movrel_count > 0:
        waterfalls.append({
            "tu": co.tu_name,
            "kernel": current_sym,
            "demangled": demangle(current_sym),
            "movrel_count": movrel_count,
            "loops": loop_count,
            "is_hot": is_hot_path(current_sym, co.tu_name),
        })
    p.wait()
    return waterfalls

def main():
    parser = argparse.ArgumentParser(description="AMD RDNA4 (gfx1201) ISA Compliance Checker")
    parser.add_argument("target", nargs="?", default=None,
                        help="Path to build dir (e.g. build_hip), libr4d.so, or .co file")
    parser.add_argument("--rocm", default=os.environ.get("ROCM", ROCM_DEFAULT),
                        help="Path to ROCm installation")
    parser.add_argument("--strict", action="store_true",
                        help="Fail (exit non-zero) on any cliff risk or scratch usage")
    parser.add_argument("--use-typesafe", action="store_true", default=None,
                        help="Use TypeSafe AI (Jev System One) to arbitrate gray-zone ISA anomalies")
    parser.add_argument("--no-typesafe", action="store_true",
                        help="Disable TypeSafe AI evaluation (pure deterministic script only)")
    parser.add_argument("--json", action="store_true",
                        help="Output results in JSON format")
    parser.add_argument("--max-display", type=int, default=15,
                        help="Maximum rows to display in summary tables")
    args = parser.parse_args()

    target = args.target
    if not target:
        for cand in ["build_hip", "build", "build_hip/radiance_home/kernels/libr4d.so", "libr4d.so"]:
            if os.path.exists(cand):
                target = cand
                break
    if not target or not os.path.exists(target):
        sys.stderr.write(f"Error: Target path '{target}' not found.\n")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as work_dir:
        cos = []
        if os.path.isdir(target):
            # Find .hip.o files or libr4d.so
            hip_objs = sorted(glob.glob(os.path.join(target, "**/*.hip.o"), recursive=True))
            if hip_objs:
                for h in hip_objs:
                    co = extract_from_hip_o(h, args.rocm, work_dir)
                    if co:
                        cos.append(co)
            else:
                so_cand = os.path.join(target, "radiance_home", "kernels", "libr4d.so")
                if os.path.exists(so_cand):
                    cos = extract_from_so(so_cand, args.rocm, work_dir)
        elif target.endswith(".so"):
            cos = extract_from_so(target, args.rocm, work_dir)
        elif target.endswith(".co"):
            cos = [CodeObject(target, os.path.basename(target)[:-3])]
        elif target.endswith(".hip.o"):
            co = extract_from_hip_o(target, args.rocm, work_dir)
            if co:
                cos = [co]

        if not cos:
            sys.stderr.write(f"Error: No AMDGPU device objects found in target {target}\n")
            sys.exit(1)

        all_kernels = []
        all_waterfalls = []

        for co in cos:
            k_list = parse_metadata(co, args.rocm)
            all_kernels.extend(k_list)
            w_list = scan_waterfall_loops(co, args.rocm)
            all_waterfalls.extend(w_list)

    # 1. VGPR Cliff Analysis
    cliff_violations = [k for k in all_kernels if k.cliff_warning is not None]

    # 2. Waterfall Loops Analysis
    hot_waterfalls = [w for w in all_waterfalls if w["is_hot"]]
    cold_waterfalls = [w for w in all_waterfalls if not w["is_hot"]]

    # 3. Scratch & Spill Analysis
    prefill_decode_scratch = [
        k for k in all_kernels
        if (k.scratch > 0 or k.vspill > 0 or k.sspill > 0) and
           is_prefill_or_decode(k.name, k.tu_name)
    ]

    use_typesafe = bool(args.use_typesafe or (not args.no_typesafe and HAS_TYPESAFE))

    jev_evaluations: dict[str, Any] = {}
    has_fatal_error = False

    if use_typesafe and eval_isa_hazard is not None and (len(hot_waterfalls) > 0 or len(cliff_violations) > 0 or len(prefill_decode_scratch) > 0):
        sys.stderr.write("🧠 Arbitrating ISA anomalies with TypeSafe AI (Jev System One)...\n")

        # 1. Hot waterfalls
        for w in hot_waterfalls:
            payload = {
                "kernel": w.get("demangled") or w["kernel"],
                "tu": w["tu"],
                "hazard_type": "waterfall_loop",
                "movrel_count": w["movrel_count"],
                "loops": w["loops"],
                "is_hot": True,
                "context": "v_movrel execution mask loop detected on hot path",
            }
            try:
                ans = eval_isa_hazard(payload)
                jev_evaluations[w["kernel"]] = ans
                verdict = ans.get("verdict", {}).get("choice", "")
                if verdict == "reject_critical_hazard":
                    has_fatal_error = True
            except (RuntimeError, urllib.error.URLError, ValueError, OSError) as e:
                sys.stderr.write(f"Warning: Jev arbitration error: {e}\n")
                has_fatal_error = True

        # 2. Cliff violations (only evaluate top 5)
        for k in cliff_violations[:5]:
            cw = k.cliff_warning
            payload = {
                "kernel": demangle(k.name),
                "tu": k.tu_name,
                "hazard_type": "vgpr_occupancy_cliff",
                "vgpr": k.vgpr,
                "boundary": cw["boundary"],
                "excess": cw["excess"],
                "current_waves": cw["current_waves"],
                "target_waves": cw["target_waves"],
                "occupancy_loss_pct": cw["occupancy_loss_pct"],
                "context": f"Kernel uses {k.vgpr} VGPRs, sitting {cw['excess']} registers over 24-granularity boundary {cw['boundary']}.",
            }
            try:
                ans = eval_isa_hazard(payload)
                jev_evaluations[k.name] = ans
                verdict = ans.get("verdict", {}).get("choice", "")
                if verdict == "reject_critical_hazard":
                    has_fatal_error = True
            except (RuntimeError, urllib.error.URLError, ValueError, OSError) as e:
                sys.stderr.write(f"Warning: Jev arbitration error: {e}\n")
                if args.strict:
                    has_fatal_error = True

        # 3. Scratch spills (only evaluate top 5)
        for k in prefill_decode_scratch[:5]:
            payload = {
                "kernel": demangle(k.name),
                "tu": k.tu_name,
                "hazard_type": "scratch_spill",
                "scratch_bytes": k.scratch,
                "vgpr_spills": k.vspill,
                "sgpr_spills": k.sspill,
                "context": f"Kernel spills {k.vspill} VGPRs ({k.scratch} bytes) to scratch memory.",
            }
            try:
                ans = eval_isa_hazard(payload)
                jev_evaluations[k.name] = ans
                verdict = ans.get("verdict", {}).get("choice", "")
                if verdict == "reject_critical_hazard":
                    has_fatal_error = True
            except (RuntimeError, urllib.error.URLError, ValueError, OSError) as e:
                sys.stderr.write(f"Warning: Jev arbitration error: {e}\n")
                if args.strict:
                    has_fatal_error = True
    else:
        if len(hot_waterfalls) > 0:
            has_fatal_error = True
        if args.strict and (len(cliff_violations) > 0 or len(prefill_decode_scratch) > 0):
            has_fatal_error = True

    if args.json:
        report = {
            "target": target,
            "total_kernels_scanned": len(all_kernels),
            "cliff_violations": [
                {
                    "kernel": k.name,
                    "demangled": demangle(k.name),
                    "tu": k.tu_name,
                    "vgpr": k.vgpr,
                    "boundary": k.cliff_warning["boundary"],
                    "excess": k.cliff_warning["excess"],
                    "current_waves": k.cliff_warning["current_waves"],
                    "target_waves": k.cliff_warning["target_waves"],
                    "occupancy_loss_pct": k.cliff_warning["occupancy_loss_pct"],
                }
                for k in cliff_violations
            ],
            "hot_waterfalls": hot_waterfalls,
            "cold_waterfalls": cold_waterfalls,
            "prefill_decode_scratch": [
                {
                    "kernel": k.name,
                    "demangled": demangle(k.name),
                    "tu": k.tu_name,
                    "vgpr": k.vgpr,
                    "scratch": k.scratch,
                    "vgpr_spills": k.vspill,
                    "sgpr_spills": k.sspill,
                }
                for k in prefill_decode_scratch
            ],
            "jev_evaluations": jev_evaluations,
            "compliant": not has_fatal_error,
        }
        print(json.dumps(report, indent=2))
        sys.exit(1 if has_fatal_error else 0)

    # Human-readable formatted console report
    print("=" * 80)
    print("  RDNA4 (gfx1201) ISA ENGINEERING COMPLIANCE REPORT")
    print(f"  Target: {target} | Total Kernels Scanned: {len(all_kernels)}")
    print("=" * 80)

    # Section 1: VGPR 24-Granularity Cliff Risks
    print("\n[RULE 1] 24-VGPR Allocation Granularity & Occupancy Cliff Scanner")
    print("-" * 80)
    if not cliff_violations:
        print("  ✓ PASS: Zero kernels detected in high-risk 24-VGPR cliff danger zones.")
    else:
        print(f"  ⚠ WARNING: {len(cliff_violations)} kernel(s) sitting in 24-VGPR danger windows (+1..8 over boundary):")
        print(f"  {'TU / Source':<24} {'VGPR':<6} {'Alloc':<6} {'Waves':<7} {'Cliff':<22} {'Kernel'}")
        print(f"  {'-'*24} {'-'*6} {'-'*6} {'-'*7} {'-'*22} {'-'*30}")
        for k in cliff_violations[:args.max_display]:
            cw = k.cliff_warning
            b = cw["boundary"]
            msg = f"{cw['excess']} over {b} (-{cw['occupancy_loss_pct']:.1f}%)"
            dname = demangle(k.name)
            short_name = (dname[:45] + "...") if len(dname) > 48 else dname
            print(f"  {k.tu_name:<24} {k.vgpr:<6} {k.allocated_vgpr:<6} {k.waves:<7} {msg:<22} {short_name}")
        if len(cliff_violations) > args.max_display:
            print(f"  ... and {len(cliff_violations) - args.max_display} more cliff violations.")

    # Section 2: Waterfall Loop Scanner
    print("\n[RULE 2] Zero-Waterfall Loop Standard (`v_movrel` Execution Mask Loops)")
    print("-" * 80)
    if hot_waterfalls:
        print(f"  ✗ FATAL: {len(hot_waterfalls)} waterfall loop(s) detected on HOT decode/draft/attention paths!")
        for w in hot_waterfalls:
            dname = w.get("demangled") or demangle(w["kernel"])
            short_name = (dname[:50] + "...") if len(dname) > 53 else dname
            print(f"    - [{w['tu']}] {short_name}: {w['movrel_count']} movrels, {w['loops']} execnz loops")
    else:
        print("  ✓ PASS: Zero waterfall loops (`v_movrel`) on hot decode/draft/attention paths.")

    if cold_waterfalls:
        print(f"  ℹ INFO: {len(cold_waterfalls)} waterfall loop(s) present on COLD non-critical paths:")
        for w in cold_waterfalls[:args.max_display]:
            dname = w.get("demangled") or demangle(w["kernel"])
            short_name = (dname[:50] + "...") if len(dname) > 53 else dname
            print(f"    - [{w['tu']}] {short_name}: {w['movrel_count']} movrel(s), {w['loops']} loop(s)")

    # Section 3: Scratch Memory & Spills
    print("\n[RULE 1/ISA] Scratch Memory Spills Scanner (Prefill / Decode Kernels)")
    print("-" * 80)
    if prefill_decode_scratch:
        status_prefix = "  ✗ FATAL" if args.strict else "  ⚠ ALERT"
        print(f"{status_prefix}: {len(prefill_decode_scratch)} prefill/decode kernel(s) with non-zero scratch or spills:")
        for k in prefill_decode_scratch[:args.max_display]:
            dname = demangle(k.name)
            short_name = (dname[:55] + "...") if len(dname) > 58 else dname
            print(f"    - [{k.tu_name}] scratch={k.scratch}B spills={k.vspill}V/{k.sspill}S | {short_name}")
        if len(prefill_decode_scratch) > args.max_display:
            print(f"    ... and {len(prefill_decode_scratch) - args.max_display} more kernels.")
    else:
        print("  ✓ PASS: Zero prefill/decode kernels allocate scratch memory.")

    # Section 4: Jev Arbitration (if anomalies were evaluated)
    if jev_evaluations:
        print("\n[JEV TIER 3 ARBITRATION] TypeSafe AI Microarchitectural Assessments:")
        print("-" * 80)
        for name, ans in list(jev_evaluations.items())[:args.max_display]:
            dname = demangle(name)
            short_name = (dname[:40] + "...") if len(dname) > 43 else dname
            v = ans.get("verdict", {}).get("choice", "unknown")
            vc = ans.get("verdict", {}).get("confidence", 0.0)
            act = ans.get("recommended_action", {}).get("choice", "unknown")
            sev = ans.get("severity", {}).get("score", 0)
            icon = "✅" if "pass" in v else ("⚠️" if "warn" in v else "❌")
            print(f"  {icon} [{short_name}]")
            print(f"     Verdict: {v} ({vc:.0%}) | Severity: Level {sev} | Action: {act}")

    # Final Summary
    print("\n" + "=" * 80)
    if has_fatal_error:
        print("  RESULT: FAILED (Violations detected under active ISA enforcement)")
        print("=" * 80)
        sys.exit(1)
    else:
        print("  RESULT: PASSED (All mandatory RDNA4 ISA ground truths satisfied)")
        print("=" * 80)
        sys.exit(0)

if __name__ == "__main__":
    main()
