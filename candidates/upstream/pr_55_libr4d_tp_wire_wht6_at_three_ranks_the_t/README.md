# Upstream PR #55: libr4d: --tp-wire wht6 at three ranks, the tiered-int8 wire over the uneven two-shot (#46)

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/55  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_55_libr4d_tp_wire_wht6_at_three_ranks_the_t`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `interconnect`
- **RDNA4 Hardware Violation Risk**: `0.11` (lower is safer)
- **Feasibility Score**: `1.82 / 4.00`
- **Expected Performance ROI**: `1.56 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (18)
- `docs/TP3.md`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_ar_twoshot_Nrank_exact.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `README.md`
- `core/config.cpp`
- `core/engine_bringup.cpp`
- `docs/GUIDE.md`
- `docs/TP3.md`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_ar_twoshot_Nrank_ti8.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_55

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_55
git apply ../../candidates/upstream/pr_55_libr4d_tp_wire_wht6_at_three_ranks_the_t/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
