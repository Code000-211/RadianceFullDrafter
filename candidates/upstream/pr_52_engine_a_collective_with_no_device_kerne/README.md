# Upstream PR #52: engine: a collective with no device kernel for a message size refuses at startup (#46)

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/52  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_52_engine_a_collective_with_no_device_kerne`  
- **GitHub Issue**: [Issue Link](https://github.com/OoguroRyuuya/RadianceMine/issues/9)

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `interconnect`
- **RDNA4 Hardware Violation Risk**: `0.09` (lower is safer)
- **Feasibility Score**: `2.68 / 4.00`
- **Expected Performance ROI**: `0.73 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.
- **Clean Mergeability (`git apply --check`)**: `CONFLICT (Requires rebase)`

---

## 3. Modified Files (4)
- `README.md`
- `core/config.cpp`
- `core/engine_bringup.cpp`
- `docs/GUIDE.md`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_52

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_52
git apply ../../candidates/upstream/pr_52_engine_a_collective_with_no_device_kerne/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
