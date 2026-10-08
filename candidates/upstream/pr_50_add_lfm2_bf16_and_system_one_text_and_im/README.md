# Upstream PR #50: Add LFM2 BF16 and System One text and image decisions

**Author**: @zivius  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/50  
**Status**: `SERVING_ENDPOINT`  
**Candidate Directory**: `candidates/upstream/pr_50_add_lfm2_bf16_and_system_one_text_and_im`  
- **GitHub Issue**: [Issue Link](https://github.com/OoguroRyuuya/RadianceMine/issues/11)

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `serving`
- **RDNA4 Hardware Violation Risk**: `0.18` (lower is safer)
- **Feasibility Score**: `1.65 / 4.00`
- **Expected Performance ROI**: `1.41 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.
- **Clean Mergeability (`git apply --check`)**: `CONFLICT (Requires rebase)`

---

## 3. Modified Files (82)
- `abi/rad_abi.h`
- `abi/rad_builder.h`
- `abi/rad_format.h`
- `abi/rad_runtime.h`
- `arch/lfm2_bf16/CMakeLists.txt`
- `arch/lfm2_bf16/lfm2_bf16.cpp`
- `arch/lfm2_bf16/vision.h`
- `core/build/rad_build.h`
- `core/build/rad_builder.cpp`
- `core/engine.cpp`
- `core/engine.h`
- `core/engine_bringup.cpp`
- `core/engine_mm.cpp`
- `core/engine_priv.h`
- `core/format/checkpoint.cpp`
- `core/mem/kv.cpp`
- `core/mem/kv.h`
- `core/mm/item.cpp`
- `core/mm/processor.cpp`
- `core/mm/processor.h`
- `core/rad_core.h`
- `core/runtime/ctx.cpp`
- `core/sched/batch.cpp`
- `core/sched/batch.h`
- `core/sched/mem_iface.h`
- `core/sched/scheduler.cpp`
- `core/sched/scheduler.h`
- `core/sched/token_scores.cpp`
- `core/sched/token_scores.h`
- `core/server/adapters.h`
- `core/server/iface.h`
- `core/server/oai.cpp`
- `core/server/oai.h`
- `core/server/server.cpp`
- `core/server/server.h`
- `core/server/systemone.cpp`
- `core/server/systemone.h`
- `core/text/tokenizer.cpp`
- `core/text/tokenizer.h`
- `core/text/tokenizer_json.cpp`
- `docs/ARCHITECTURES.md`
- `docs/GUIDE.md`
- `docs/OPS.md`
- `docs/SYSTEMONE.md`
- `docs/TOOLS.md`
- `libavx/avx_cases.cpp`
- `libavx/avx_check.cpp`
- `libavx/avx_gemm.cpp`
- `libavx/avx_isa.h`
- `libavx/avx_misc.cpp`
- `libavx/avx_norm.cpp`
- `libavx/avx_registry.cpp`
- `libr4d/CMakeLists.txt`
- `libr4d/r4d_attn_paged_h64_gqa4.hip`
- `libr4d/r4d_causal_conv_bf16.hip`
- `libr4d/r4d_logits_select_bf16.hip`
- `libr4d/r4d_model_bf16.hip`
- `libr4d/r4d_plugin.h`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `libr4d/r4d_shapes.cpp`
- `libr4d/r4d_vit_bf16.hip`
- `libref/ref_causal_conv.cpp`
- `libref/ref_elementwise.cpp`
- `libref/ref_logits_select.cpp`
- `libref/ref_ops.h`
- `libref/ref_registry.cpp`
- `libref/ref_shapes.cpp`
- `spec.md`
- `tests/arch_test.cpp`
- `tests/checkpoint_test.cpp`
- `tests/grid_embed_golden.h`
- `tests/mem_test.cpp`
- `tests/mm_test.cpp`
- `tests/ref_test.cpp`
- `tests/sched_test.cpp`
- `tests/systemone_test.cpp`
- `tests/text_test.cpp`
- `tests/token_scores_test.cpp`
- `tests/tokenizer_test.cpp`
- `tools/tokref.cpp`
- `libr4d/r4d_selftest.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_50

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_50
git apply ../../candidates/upstream/pr_50_add_lfm2_bf16_and_system_one_text_and_im/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
