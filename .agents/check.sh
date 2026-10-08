#!/usr/bin/env bash
set -euo pipefail

# RadianceMine Project-level Linter and Epistemic Gate Hook
# Invoked by auto-lint plugin (PostToolUse) on file write/edit.

FILE="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$FILE" ]]; then
  exit 0
fi

# By default, keep per-write checks ultra-fast (<10ms) to preserve agent coding flow.
# Full compiler checks and epistemic invariant gates are enforced at pre-commit
# and in scripts/gate_check.sh before any merge.
ENABLE_COMPILER_HOOK="${ENABLE_COMPILER_HOOK:-0}"

if [[ "${ENABLE_COMPILER_HOOK}" == "1" ]]; then
  case "$FILE" in
    *.hip)
      if [[ -x /opt/rocm/lib/llvm/bin/clang++ ]]; then
        echo "⚡ Checking HIP syntax: $FILE"
        /opt/rocm/lib/llvm/bin/clang++ -x hip -fsyntax-only -std=gnu++17 --offload-arch=gfx1201 \
          -DRAD_HAVE_HIP=1 -D__HIP_PLATFORM_AMD__=1 -D__HIP_ROCclr__=1 -Dlibr4d_EXPORTS \
          -I"$ROOT_DIR/libr4d" -I"$ROOT_DIR/abi" -I"$ROOT_DIR/build_hip/rad_include" -I"$ROOT_DIR" \
          "$FILE"
      fi
      ;;
    *.cpp)
      if [[ "$FILE" != *"/vendor/"* ]]; then
        echo "⚡ Checking C++ syntax: $FILE"
        /usr/bin/c++ -std=gnu++20 -fsyntax-only \
          -DRAD_HAVE_HIP=1 -D__HIP_PLATFORM_AMD__=1 -DRAD_VERSION=\"1.0.13\" \
          -I"$ROOT_DIR" \
          -I"$ROOT_DIR/core" \
          -I"$ROOT_DIR/abi" \
          -I"$ROOT_DIR/libr4d" \
          -I"$ROOT_DIR/build_hip/rad_include" \
          -I"$ROOT_DIR/vendor/cpp-httplib" \
          -isystem "$ROOT_DIR/vendor" \
          -isystem /opt/rocm/include \
          -isystem "$ROOT_DIR/vendor/shim" \
          -isystem "$ROOT_DIR/vendor/llama/common" \
          "$FILE"
      fi
      ;;
  esac
fi

exit 0
