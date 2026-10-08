# Upstream PR #18: deploy/grafana: a dashboard for /metrics, on Prometheus or VictoriaMetrics

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/18  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_18_deploygrafana_a_dashboard_for_metrics_on`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `drafter`
- **RDNA4 Hardware Violation Risk**: `0.04` (lower is safer)
- **Feasibility Score**: `2.83 / 4.00`
- **Expected Performance ROI**: `0.69 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (5)
- `deploy/grafana/README.md`
- `deploy/grafana/radiance.json`
- `docs/GUIDE.md`
- `deploy/grafana/dashboard.png`
- `deploy/grafana/overview.png`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_18

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_18
git apply ../../candidates/upstream/pr_18_deploygrafana_a_dashboard_for_metrics_on/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
