# Upstream PR #41: mx: native OCP-MX family (mxfp6/mxfp8/int5) + ParoQuant Path A + MX serving for qwen35

**Author**: @J-Nova  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/41  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_41_mx_native_ocp_mx_family_mxfp6mxfp8int5_p`  
- **GitHub Issue**: [Issue Link](https://github.com/OoguroRyuuya/RadianceMine/issues/15)

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `gemm`
- **RDNA4 Hardware Violation Risk**: `0.31` (lower is safer)
- **Feasibility Score**: `1.57 / 4.00`
- **Expected Performance ROI**: `1.73 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.
- **Clean Mergeability (`git apply --check`)**: `CONFLICT (Requires rebase)`

---

## 3. Modified Files (111)
- `README.md`
- `abi/rad_runtime.h`
- `arch/common/rad_arch.h`
- `arch/common/rad_block_attn_gated_mxfp4.h`
- `arch/common/rad_block_dflash2.h`
- `arch/common/rad_block_gdn_mxfp4.h`
- `arch/common/rad_block_mlp_mxfp4.h`
- `arch/common/rad_mx.h`
- `arch/qwen35_fp8/qwen35_fp8.cpp`
- `arch/qwen35_mxfp4/CMakeLists.txt`
- `arch/qwen35_mxfp4/qwen35_mxfp4.cpp`
- `arch/qwen35_mxfp6/CMakeLists.txt`
- `arch/qwen35_mxfp6/qwen35_mxfp6.cpp`
- `arch/qwen35_mxfp8/CMakeLists.txt`
- `arch/qwen35_mxfp8/qwen35_mxfp8.cpp`
- `arch/qwen35_paroquant/CMakeLists.txt`
- `arch/qwen35_paroquant/qwen35_paroquant.cpp`
- `core/device/aql.cpp`
- `core/engine.cpp`
- `core/format/checkpoint.cpp`
- `core/format/checkpoint.h`
- `core/format/encoding.cpp`
- `core/format/encoding.h`
- `core/kld.cpp`
- `core/runtime/ctx.cpp`
- `core/runtime/ctx.h`
- `core/sched/adaptive_k.cpp`
- `core/sched/adaptive_k.h`
- `core/sched/batch.cpp`
- `core/sched/lookup_draft.cpp`
- `core/sched/lookup_draft.h`
- `core/sched/metrics.h`
- `core/sched/scheduler.cpp`
- `core/sched/scheduler.h`
- `core/server/adapters.h`
- `core/server/dashboard.cpp`
- `core/server/iface.h`
- `core/server/liveview.h`
- `core/server/metrics.cpp`
- `core/server/metrics.h`
- `data/recipes/q35-9b-mxfp4.recipe`
- `data/recipes/q38-27b-mxfp4-df2mx.recipe`
- `data/recipes/q38-27b-mxfp4-i4head.recipe`
- `data/recipes/q38-27b-mxfp4.recipe`
- `data/recipes/q38-27b-mxfp6.recipe`
- `data/recipes/q38-27b-mxfp8.recipe`
- `data/recipes/q38-27b-paro-mxfp6.recipe`
- `deploy/compose/qwen3.8-27b-mxfp4.yaml`
- `docs/ARCHITECTURES.md`
- `docs/GUIDE.md`
- `docs/OPS.md`
- `libavx/avx_cases.cpp`
- `libavx/avx_common.h`
- `libavx/avx_gemm.cpp`
- `libavx/avx_harness.h`
- `libavx/avx_isa.h`
- `libavx/avx_quant.cpp`
- `libavx/avx_registry.cpp`
- `libavx/avx_sample.cpp`
- `libavx/avx_support.cpp`
- `libr4d/CMakeLists.txt`
- `libr4d/r4d.h`
- `libr4d/r4d_ar_entry.hip`
- `libr4d/r4d_dflash_select_bf16.hip`
- `libr4d/r4d_enc.h`
- `libr4d/r4d_fp8_layout.cpp`
- `libr4d/r4d_fp8_lm.h`
- `libr4d/r4d_fuse.cpp`
- `libr4d/r4d_fused_quant_fp8_row.hip`
- `libr4d/r4d_gdn_recurrent_update_k128_v128_bf16_fp32state.hip`
- `libr4d/r4d_gemm_args.h`
- `libr4d/r4d_gemm_fp8a16_nt_m1.hip`
- `libr4d/r4d_gemm_mxfp4a8_gated_nt_m64.hip`
- `libr4d/r4d_gemm_mxfp4a8_nt_m64.hip`
- `libr4d/r4d_gemm_mxfp4a8_tiled.hip`
- `libr4d/r4d_gemm_mxfp6a8_nt_m64.hip`
- `libr4d/r4d_gemm_mxfp8a8_nt_m64.hip`
- `libr4d/r4d_gemm_w5a8_nt_m64.hip`
- `libr4d/r4d_layout.cpp`
- `libr4d/r4d_paroquant_fused_row.hip`
- `libr4d/r4d_paroquant_quant_fp8_row.hip`
- `libr4d/r4d_paroquant_quant_fp8_row_multi.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_quant_act_fp8_row.hip`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_rowtopk_bf16.hip`
- `libr4d/r4d_selftest.cpp`
- `libr4d/r4d_shapes.cpp`
- `libref/ref_common.h`
- `libref/ref_gemm.cpp`
- `libref/ref_gemm.h`
- `libref/ref_ops.h`
- `libref/ref_quant.cpp`
- `libref/ref_registry.cpp`
- `libref/ref_shapes.cpp`
- `scripts/oracle.sh`
- `tests/checkpoint_test.cpp`
- `tests/data/lookup/copy-answer.ids`
- `tests/data/lookup/copy-prompt.ids`
- `tests/encoding_test.cpp`
- `tests/lookup_draft_test.cpp`
- `tests/r4d_bands_test.cpp`
- `tests/ref_test.cpp`
- `tests/relayout_parity_test.cpp`
- `tests/sched_test.cpp`
- `tests/server_test.cpp`
- `tests/text_test.cpp`
- `tools/CMakeLists.txt`
- `tools/opshapes.h`
- `tools/rad_convert.cpp`
- `tools/rad_tokenize.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_41

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_41
git apply ../../candidates/upstream/pr_41_mx_native_ocp_mx_family_mxfp6mxfp8int5_p/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
