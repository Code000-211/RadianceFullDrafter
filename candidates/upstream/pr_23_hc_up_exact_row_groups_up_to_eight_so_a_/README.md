# Upstream PR #23: hc_up: exact row groups up to eight, so a five- or six-row verify reads W_up once

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/23  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_23_hc_up_exact_row_groups_up_to_eight_so_a_`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `gemm`
- **RDNA4 Hardware Violation Risk**: `0.09` (lower is safer)
- **Feasibility Score**: `3.04 / 4.00`
- **Expected Performance ROI**: `2.96 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (1)
- `libr4d/r4d_hc_bf16.hip`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_23

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_23
git apply ../../candidates/upstream/pr_23_hc_up_exact_row_groups_up_to_eight_so_a_/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
