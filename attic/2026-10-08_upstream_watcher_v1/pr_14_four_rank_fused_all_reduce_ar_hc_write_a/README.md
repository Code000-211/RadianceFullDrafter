# Upstream PR #14: four-rank fused all-reduce: ar_hc_write and ar_gather_hc_write at tp 4

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/14  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_14_four_rank_fused_all_reduce_ar_hc_write_a`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `interconnect`
- **RDNA4 Hardware Violation Risk**: `0.13` (lower is safer)
- **Feasibility Score**: `2.91 / 4.00`
- **Expected Performance ROI**: `3.37 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (22)
- `arch/common/rad_block_hc.h`
- `arch/common/rad_fp8.h`
- `docs/ARCHITECTURES.md`
- `docs/OPS.md`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_ar_oneshot_Nrank_exact.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `tests/arch_test.cpp`
- `arch/common/rad_block_hc.h`
- `arch/common/rad_fp8.h`
- `docs/ARCHITECTURES.md`
- `docs/OPS.md`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_ar_oneshot_2rank_exact.hip`
- `libr4d/r4d_ar_oneshot_Nrank_exact.hip`
- `libr4d/r4d_fuse.cpp`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `tests/arch_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_14

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_14
git apply ../../candidates/upstream/pr_14_four_rank_fused_all_reduce_ar_hc_write_a/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
