# Upstream PR #48: checkpoint: import an NVFP4 release as its codes beside the e4m3 table over the tensor's f32 global, and per-channel FP8 by its row scale

**Author**: @devmilan  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/48  
**Status**: `REJECTED_UNFEASIBLE`  
**Candidate Directory**: `candidates/upstream/pr_48_checkpoint_import_an_nvfp4_release_as_it`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `gemm`
- **RDNA4 Hardware Violation Risk**: `0.15` (lower is safer)
- **Feasibility Score**: `0.81 / 4.00`
- **Expected Performance ROI**: `0.59 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (8)
- `README.md`
- `core/format/checkpoint.cpp`
- `core/format/checkpoint.h`
- `data/recipes/q38-27b-nvfp4-df2.recipe`
- `docs/GUIDE.md`
- `tests/CMakeLists.txt`
- `tests/checkpoint_test.cpp`
- `tests/recipe_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_48

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_48
git apply ../../candidates/upstream/pr_48_checkpoint_import_an_nvfp4_release_as_it/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
