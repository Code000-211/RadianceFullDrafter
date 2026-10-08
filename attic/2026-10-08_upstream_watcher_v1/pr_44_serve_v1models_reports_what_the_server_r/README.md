# Upstream PR #44: serve: /v1/models reports what the server runs with; /v1/models/:id answers the entry itself

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/44  
**Status**: `SERVING_ENDPOINT`  
**Candidate Directory**: `candidates/upstream/pr_44_serve_v1models_reports_what_the_server_r`  
- **GitHub Issue**: [Issue Link](https://github.com/OoguroRyuuya/RadianceMine/issues/14)

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `serving`
- **RDNA4 Hardware Violation Risk**: `0.04` (lower is safer)
- **Feasibility Score**: `2.33 / 4.00`
- **Expected Performance ROI**: `0.34 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.
- **Clean Mergeability (`git apply --check`)**: `CONFLICT (Requires rebase)`

---

## 3. Modified Files (28)
- `core/server/oai.cpp`
- `core/server/oai.h`
- `core/server/server.cpp`
- `docs/GUIDE.md`
- `tests/server_test.cpp`
- `tests/wire_test.cpp`
- `core/server/oai.cpp`
- `core/server/oai.h`
- `core/server/server.cpp`
- `docs/GUIDE.md`
- `tests/server_test.cpp`
- `tests/wire_test.cpp`
- `core/engine.cpp`
- `core/server/oai.cpp`
- `core/server/oai.h`
- `core/server/server.cpp`
- `core/server/server.h`
- `docs/GUIDE.md`
- `tests/server_test.cpp`
- `tests/wire_test.cpp`
- `core/server/admin.cpp`
- `core/server/oai.cpp`
- `core/server/oai.h`
- `core/server/server.cpp`
- `core/server/server.h`
- `docs/GUIDE.md`
- `tests/server_test.cpp`
- `tests/wire_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_44

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_44
git apply ../../candidates/upstream/pr_44_serve_v1models_reports_what_the_server_r/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
