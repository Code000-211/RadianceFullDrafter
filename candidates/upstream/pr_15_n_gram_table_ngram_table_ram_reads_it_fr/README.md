# Upstream PR #15: n-gram table: --ngram-table ram reads it from a locked copy in RAM

**Author**: @keptn42  
**Upstream URL**: https://codeberg.org/StillDeadcode/radiance/pulls/15  
**Status**: `READY_TO_TEST`  
**Candidate Directory**: `candidates/upstream/pr_15_n_gram_table_ngram_table_ram_reads_it_fr`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `general`
- **RDNA4 Hardware Violation Risk**: `0.07` (lower is safer)
- **Feasibility Score**: `2.39 / 4.00`
- **Expected Performance ROI**: `2.30 / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `PASS`
- Zero dangerous anti-patterns detected.

---

## 3. Modified Files (19)
- `abi/rad_builder.h`
- `arch/common/rad_arch.h`
- `arch/common/rad_block_ple.h`
- `core/config.cpp`
- `core/engine_bringup.cpp`
- `core/rad_core.h`
- `docs/DOCKER.md`
- `docs/GUIDE.md`
- `docs/OPS.md`
- `libavx/avx_check.cpp`
- `libavx/avx_check_rows.cpp`
- `libavx/avx_gemm.cpp`
- `libavx/avx_ngram.cpp`
- `libavx/avx_registry.cpp`
- `libavx/avx_rows.h`
- `libref/ref_registry.cpp`
- `tests/CMakeLists.txt`
- `tests/config_test.cpp`
- `libavx/README.md`

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_15

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_15
git apply ../../candidates/upstream/pr_15_n_gram_table_ngram_table_ram_reads_it_fr/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
