# Upstream PR #36: budget: an uneven world's cheaper rank pages the common tokens and keeps its experts

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/36  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_36_budget_an_uneven_worlds_cheaper_rank_pag`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `qsa`
- **RDNA4 Hardware Violation Risk**: `0.10` (lower is safer)
- **Feasibility Score**: `2.43 / 4.00`
- **Expected Performance ROI**: `2.36 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (10)
- `core/engine.h`
- `core/engine_bringup.cpp`
- `core/mem/kv.cpp`
- `core/mem/kv.h`
- `core/mem/vram_budget.cpp`
- `core/mem/vram_budget.h`
- `core/rad_core.h`
- `docs/GUIDE.md`
- `docs/TP3.md`
- `tests/mem_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_36

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_36
git apply ../../candidates/upstream/pr_36_budget_an_uneven_worlds_cheaper_rank_pag/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
