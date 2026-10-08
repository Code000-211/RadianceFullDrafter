# Upstream PR #12: Three ranks for Qwen3.8-Flash-Next: pad the checkpoint, exactly; all-reduce, all-gather, the vocab and expert-width splits at world 3

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/12  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_12_three_ranks_for_qwen38_flash_next_pad_th`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `interconnect`
- **RDNA4 Hardware Violation Risk**: `0.19` (lower is safer)
- **Feasibility Score**: `1.61 / 4.00`
- **Expected Performance ROI**: `1.11 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (17)
- `docs/OPS.md`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_ar_gather_Nrank.hip`
- `libr4d/r4d_ar_oneshot_Nrank_exact.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `arch/common/rad_arch.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `core/engine.cpp`
- `README.md`
- `docs/TP3.md`
- `tools/pad_tp.py`
- `tools/pad_verify.py`
- `arch/common/rad_arch.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_12

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_12
git apply ../../candidates/upstream/pr_12_three_ranks_for_qwen38_flash_next_pad_th/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
