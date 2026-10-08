# Upstream PR #35: MoE prefill: wide gather, parallel scan and map prefix, early weight loads

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/35  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_35_moe_prefill_wide_gather_parallel_scan_an`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `moe`
- **RDNA4 Hardware Violation Risk**: `0.23` (lower is safer)
- **Feasibility Score**: `2.03 / 4.00`
- **Expected Performance ROI**: `2.64 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (6)
- `libr4d/r4d.h`
- `libr4d/r4d_moe.hip`
- `libr4d/r4d_selftest.cpp`
- `libr4d/r4d_moe.hip`
- `libr4d/r4d_selftest.cpp`
- `libr4d/r4d_selftest.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_35

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_35
git apply ../../candidates/upstream/pr_35_moe_prefill_wide_gather_parallel_scan_an/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
