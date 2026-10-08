# Upstream PR #56: scripts/cardclock.py: what holds each card's clock under load, and which card the TP step waits for

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/56  
**Status**: `DOCS_OR_TOOLING`  
**Candidate Directory**: `candidates/upstream/pr_56_scriptscardclockpy_what_holds_each_cards`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `tooling`
- **RDNA4 Hardware Violation Risk**: `0.05` (lower is safer)
- **Feasibility Score**: `2.77 / 4.00`
- **Expected Performance ROI**: `0.93 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (3)
- `docs/TOOLS.md`
- `scripts/README.md`
- `scripts/cardclock.py`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_56

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_56
git apply ../../candidates/upstream/pr_56_scriptscardclockpy_what_holds_each_cards/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
