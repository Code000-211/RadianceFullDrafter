# Upstream PR #17: placement: --host-weights keeps an embedding table in the pinned host pool, read in place

**Author**: @mechkbfan  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/17  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_17_placement_host_weights_keeps_an_embeddin`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `general`
- **RDNA4 Hardware Violation Risk**: `0.11` (lower is safer)
- **Feasibility Score**: `1.64 / 4.00`
- **Expected Performance ROI**: `2.47 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (8)
- `core/config.cpp`
- `core/engine.cpp`
- `core/engine_bringup.cpp`
- `core/place/planner.cpp`
- `core/place/planner.h`
- `core/rad_core.h`
- `docs/GUIDE.md`
- `tests/place_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_17

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_17
git apply ../../candidates/upstream/pr_17_placement_host_weights_keeps_an_embeddin/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
