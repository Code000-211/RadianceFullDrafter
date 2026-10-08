#!/usr/bin/env python3
"""isa_diff.py — Tier 3: what the candidate changed in register use and spills, kernel by kernel.

Absolute ISA rules do not gate anything (the baseline itself spills in 54 kernels); speed
is decided by the A/B benchmark. This report shows which kernels got more VGPRs, lower
occupancy or new scratch spills, so a speed regression can be traced to a kernel.

Exit codes: 0 report written, 1 a build could not be analysed, 2 a hot-path waterfall
loop appeared (the one hard ISA rule check_isa_compliance.py enforces).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def analyse(build_dir: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "check_isa_compliance.py"), str(build_dir), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"ISA analysis of {build_dir} failed (rc={proc.returncode}): {proc.stderr.strip()[-500:]}")


def kernel_key(k: dict) -> str:
    return f"{k['tu']}::{k['kernel']}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-kernel VGPR/spill diff between baseline and candidate builds")
    parser.add_argument("baseline_build", type=Path)
    parser.add_argument("candidate_build", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    try:
        base = analyse(args.baseline_build)
        cand = analyse(args.candidate_build)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    base_k = {kernel_key(k): k for k in base["kernels"]}
    cand_k = {kernel_key(k): k for k in cand["kernels"]}
    changed = []
    for key, c in cand_k.items():
        b = base_k.get(key)
        if b is None:
            changed.append({"kernel": key, "change": "new", "candidate": c})
        elif any(b[f] != c[f] for f in ("vgpr", "scratch", "vgpr_spills", "sgpr_spills", "waves")):
            changed.append({"kernel": key, "change": "modified", "baseline": b, "candidate": c})
    removed = sorted(set(base_k) - set(cand_k))
    new_waterfalls = len(cand["hot_waterfalls"]) > len(base["hot_waterfalls"])

    print(f"Tier 3 ISA diff: {len(base_k)} baseline kernels, {len(cand_k)} candidate kernels")
    print(f"  changed/new: {len(changed)}, removed: {len(removed)}")
    for ch in changed[:40]:
        c = ch["candidate"]
        if ch["change"] == "new":
            print(f"  + {ch['kernel'][:90]}  vgpr={c['vgpr']} waves={c['waves']} scratch={c['scratch']}")
        else:
            b = ch["baseline"]
            print(
                f"  ~ {ch['kernel'][:90]}  vgpr {b['vgpr']}->{c['vgpr']} waves {b['waves']}->{c['waves']} "
                f"scratch {b['scratch']}->{c['scratch']} spills {b['vgpr_spills']}->{c['vgpr_spills']}"
            )
    if len(changed) > 40:
        print(f"  ... {len(changed) - 40} more")

    if args.json_out:
        args.json_out.write_text(json.dumps({"changed": changed, "removed": removed, "new_hot_waterfalls": new_waterfalls}, indent=2))

    if new_waterfalls:
        print("❌ Candidate adds v_movrel waterfall loops on a hot path.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
