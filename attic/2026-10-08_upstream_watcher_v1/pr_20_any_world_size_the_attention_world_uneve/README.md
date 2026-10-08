# Upstream PR #20: any world size: the attention world, uneven delta-net heads, nothing padded

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/20  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_20_any_world_size_the_attention_world_uneve`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `gdn`
- **RDNA4 Hardware Violation Risk**: `0.16` (lower is safer)
- **Feasibility Score**: `1.86 / 4.00`
- **Expected Performance ROI**: `1.32 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (51)
- `abi/rad_builder.h`
- `core/build/rad_build.h`
- `core/build/rad_builder.cpp`
- `core/engine_bringup.cpp`
- `core/format/share.cpp`
- `core/format/share.h`
- `core/rad_core.h`
- `tests/build_test.cpp`
- `tests/share_test.cpp`
- `arch/common/rad_arch.h`
- `arch/common/rad_block_attn_gated_fp8.h`
- `arch/common/rad_block_gdn_fp8.h`
- `arch/common/rad_fp8.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `docs/TP3.md`
- `tests/arch_test.cpp`
- `core/engine_bringup.cpp`
- `core/mem/kv.cpp`
- `core/mem/kv.h`
- `tests/mem_test.cpp`
- `core/device/dispatch.cpp`
- `core/engine_bringup.cpp`
- `docs/TP3.md`
- `libr4d/r4d.h`
- `libr4d/r4d_model_bf16.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `libr4d/r4d_shapes.cpp`
- `arch/common/rad_block_attn_gated_fp8.h`
- `abi/rad_builder.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `core/build/rad_build.h`
- `core/build/rad_builder.cpp`
- `core/mem/kv.cpp`
- `core/mem/kv.h`
- `core/rad_core.h`
- `core/runtime/issue.cpp`
- `tests/arch_test.cpp`
- `core/engine.h`
- `core/engine_bringup.cpp`
- `arch/common/rad_arch.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `tests/arch_test.cpp`
- `docs/OPS.md`
- `core/engine.cpp`
- `core/engine_bringup.cpp`
- `arch/common/rad_arch.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `core/engine.h`
- `core/engine_bringup.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_20

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_20
git apply ../../candidates/upstream/pr_20_any_world_size_the_attention_world_uneve/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
