#!/usr/bin/env bash
# ==============================================================================
# orca_setup.sh — setup hook for Orca worktrees (referenced from orca.yaml)
# ==============================================================================
# Builds the worktree's own build_hip so agents can compile and test, and so the
# pre-commit hook (Tier 0 static checks need radiance_home/kernels) can run.
# Nothing is copied from the primary checkout.
# ==============================================================================
set -euo pipefail

WT="${ORCA_WORKTREE_PATH:-$(pwd)}"
cd "${WT}"

export ROCM_PATH="${ROCM_PATH:-/opt/rocm}"
export PATH="${ROCM_PATH}/bin:${ROCM_PATH}/llvm/bin:${PATH}"

if [ ! -f build_hip/build.ninja ]; then
    cmake -B build_hip -S . -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DRAD_WITH_HIP=ON -DRAD_GPU_TARGETS=gfx1201 -DRAD_BUILD_TESTS=ON
fi
ninja -C build_hip
echo "✓ worktree build ready: ${WT}/build_hip"
