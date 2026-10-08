# Upstream PR #45: serve: /props answers what llama-server clients read

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/45  
**Status**: `SERVING_ENDPOINT`  
**Candidate Directory**: `candidates/upstream/pr_45_serve_props_answers_what_llama_server_cl`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `serving`
- **RDNA4 Hardware Violation Risk**: `0.05` (lower is safer)
- **Feasibility Score**: `2.79 / 4.00`
- **Expected Performance ROI**: `0.08 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (5)
- `core/server/admin.cpp`
- `core/server/server.cpp`
- `core/server/server.h`
- `docs/GUIDE.md`
- `tests/server_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_45

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_45
git apply ../../candidates/upstream/pr_45_serve_props_answers_what_llama_server_cl/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
