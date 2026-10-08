# Upstream PR #16: four-rank Flash-Next: routed experts in four classes

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/16  
**Status**: `REJECTED_UNFEASIBLE`  
**Candidate Directory**: `candidates/upstream/pr_16_four_rank_flash_next_routed_experts_in_f`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `moe`
- **RDNA4 Hardware Violation Risk**: `0.12` (lower is safer)
- **Feasibility Score**: `1.41 / 4.00`
- **Expected Performance ROI**: `2.21 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (34)
- `arch/common/rad_block_moe_fp8.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `docs/ARCHITECTURES.md`
- `tests/arch_test.cpp`
- `core/build/rad_builder.cpp`
- `docs/OPS.md`
- `libavx/avx_cases.cpp`
- `libavx/avx_isa.h`
- `libavx/avx_moe.cpp`
- `libavx/avx_registry.cpp`
- `libr4d/r4d_layout.cpp`
- `libr4d/r4d_moe.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `libr4d/r4d_shapes.cpp`
- `libref/ref_moe.cpp`
- `libref/ref_ops.h`
- `libref/ref_registry.cpp`
- `libref/ref_shapes.cpp`
- `tests/ref_test.cpp`
- `arch/common/rad_block_moe_fp8.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `docs/ARCHITECTURES.md`
- `tests/arch_test.cpp`
- `libr4d/r4d_selftest.cpp`
- `core/format/encoding.cpp`
- `core/format/encoding.h`
- `docs/MOE-W4.md`
- `libref/ref_shapes.cpp`
- `scripts/oracle.sh`
- `tests/fixture_test.cpp`
- `tests/ref_test.cpp`
- `tests/relayout_parity_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_16

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_16
git apply ../../candidates/upstream/pr_16_four_rank_flash_next_routed_experts_in_f/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
