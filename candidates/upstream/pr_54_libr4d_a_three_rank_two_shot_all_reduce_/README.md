# Upstream PR #54: libr4d: a three-rank two-shot all-reduce, with shards one word uneven

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/54  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_54_libr4d_a_three_rank_two_shot_all_reduce_`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `interconnect`
- **RDNA4 Hardware Violation Risk**: `0.12` (lower is safer)
- **Feasibility Score**: `2.20 / 4.00`
- **Expected Performance ROI**: `2.42 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (7)
- `docs/TP3.md`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_ar_twoshot_Nrank_exact.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_54

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_54
git apply ../../candidates/upstream/pr_54_libr4d_a_three_rank_two_shot_all_reduce_/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
