# Upstream PR #38: WIP: serve: --rope-scaling, #37's static YaRN on an existing container without a reconvert (supplemental to #37)

**Author**: @bakon  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/38  
**Status**: `QUEUED_LOW_PRIORITY`  
**Candidate Directory**: `candidates/upstream/pr_38_wip_serve_rope_scaling_37s_static_yarn_o`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `general`
- **RDNA4 Hardware Violation Risk**: `0.06` (lower is safer)
- **Feasibility Score**: `2.02 / 4.00`
- **Expected Performance ROI**: `0.47 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (46)
- `abi/rad_yarn.h`
- `arch/common/rad_arch.h`
- `arch/common/rad_block_dflash2.h`
- `arch/qwen35_bf16/qwen35_bf16.cpp`
- `arch/qwen35_fp8/qwen35_fp8.cpp`
- `docs/OPS.md`
- `docs/YARN.md`
- `libavx/avx_attn.cpp`
- `libavx/avx_cases.cpp`
- `libavx/avx_registry.cpp`
- `libr4d/r4d_model_bf16.hip`
- `libr4d/r4d_qk_norm_rope_gate.hip`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `libref/ref_attn.cpp`
- `libref/ref_registry.cpp`
- `tests/arch_test.cpp`
- `tests/data/generate_yarn_reference.py`
- `tests/data/yarn_reference.json`
- `tests/data/yarn_reference_rocm.json`
- `tests/ref_test.cpp`
- `tests/yarn_test.cpp`
- `arch/common/rad_qsa.h`
- `arch/qwen4exp_fp8/qwen4exp_fp8.cpp`
- `docs/OPS.md`
- `docs/YARN.md`
- `libr4d/r4d_qsa_block_key_bf16.hip`
- `libr4d/r4d_rows.cpp`
- `libr4d/r4d_selftest.cpp`
- `tests/arch_test.cpp`
- `abi/rad_yarn.h`
- `arch/common/rad_arch.h`
- `docs/YARN-VALIDATION.md`
- `docs/YARN.md`
- `libavx/avx_cases.cpp`
- `tests/ref_test.cpp`
- `tests/yarn_test.cpp`
- `core/config.cpp`
- `core/engine.h`
- `core/engine_bringup.cpp`
- `core/format/rope_override.h`
- `core/rad_core.h`
- `docs/GUIDE.md`
- `docs/YARN.md`
- `tests/config_test.cpp`
- `tests/yarn_test.cpp`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_38

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_38
git apply ../../candidates/upstream/pr_38_wip_serve_rope_scaling_37s_static_yarn_o/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
