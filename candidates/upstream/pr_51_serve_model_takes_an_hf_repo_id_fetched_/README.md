# Upstream PR #51: serve: --model takes an HF repo id, fetched to $RADIANCE_HOME/hf via hfget.sh

**Author**: @redxherring  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/51  
**Status**: `SERVING_ENDPOINT`  
**Candidate Directory**: `candidates/upstream/pr_51_serve_model_takes_an_hf_repo_id_fetched_`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `serving`
- **RDNA4 Hardware Violation Risk**: `0.07` (lower is safer)
- **Feasibility Score**: `2.21 / 4.00`
- **Expected Performance ROI**: `0.19 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (5)
- `core/hf_model.cpp`
- `core/main.cpp`
- `core/rad_core.h`
- `scripts/hfget.sh`
- `core/config.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_51

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_51
git apply ../../candidates/upstream/pr_51_serve_model_takes_an_hf_repo_id_fetched_/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
