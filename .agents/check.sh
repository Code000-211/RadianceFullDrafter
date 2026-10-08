#!/usr/bin/env bash
set -euo pipefail

# RadianceMine Project-level Linter and Epistemic Gate Hook
# Invoked by auto-lint plugin (PostToolUse) on every file write/edit.

FILE="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$FILE" ]]; then
  exit 0
fi

# 1. Tier 0 Epistemic Invariants Check (Symbols, Anti-Silent-Skip, Thresholds, Clocks)
# Runs for all C/C++/HIP sources and headers (~135ms)
case "$FILE" in
  *.h|*.hpp|*.cpp|*.hip|*.c)
    python3 "$ROOT_DIR/scripts/check_epistemic_invariants.py"
    ;;
esac

# 2. Fast Compiler Syntax Check (-fsyntax-only)
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
    # Check if file belongs to core, tests, or libr4d (exclude vendor)
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
