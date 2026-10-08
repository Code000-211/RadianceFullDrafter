# Upstream PR #24: draft: an adaptive draft window per sequence, with a cap under load

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/24  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_24_draft_an_adaptive_draft_window_per_seque`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `drafter`
- **RDNA4 Hardware Violation Risk**: `0.05` (lower is safer)
- **Feasibility Score**: `2.25 / 4.00`
- **Expected Performance ROI**: `1.97 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (27)
- `core/sched/draft.cpp`
- `core/sched/draft.h`
- `core/sched/metrics.h`
- `core/sched/scheduler.cpp`
- `core/sched/scheduler.h`
- `core/server/adapters.h`
- `core/server/iface.h`
- `core/server/metrics.cpp`
- `core/server/metrics.h`
- `tests/sched_test.cpp`
- `tests/server_test.cpp`
- `core/sched/draft.cpp`
- `core/sched/draft.h`
- `core/sched/scheduler.cpp`
- `core/sched/scheduler.h`
- `tests/sched_test.cpp`
- `core/engine.cpp`
- `core/sched/scheduler.cpp`
- `core/sched/scheduler.h`
- `tests/sched_test.cpp`
- `docs/GUIDE.md`
- `core/server/metrics.cpp`
- `core/server/metrics.h`
- `docs/GUIDE.md`
- `tests/server_test.cpp`
- `deploy/grafana/README.md`
- `deploy/grafana/radiance.json`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_24

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_24
git apply ../../candidates/upstream/pr_24_draft_an_adaptive_draft_window_per_seque/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
