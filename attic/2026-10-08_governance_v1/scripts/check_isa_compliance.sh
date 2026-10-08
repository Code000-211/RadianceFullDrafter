#!/usr/bin/env bash
# ==============================================================================
# RDNA4 (gfx1201) ISA Engineering Compliance & Verification Suite
# Enforces the 7 RDNA4 ISA Engineering Ground Truths:
#   Rule 1: 24-VGPR Allocation Granularity & Occupancy Cliff Avoidance
#   Rule 2: Zero-Waterfall Loop Standard on Hot Decode/Draft Paths
#   Rule 3: Dual-Issue VOPD Constraints Validation
#   Rule 4: Canonical K-Ordering for GLOBAL_LOAD_TR
#   Rule 5: Split Cache Temporal Hints (TH) Standard
#   Rule 6: Independent Wait Counters & s_wait_alu Guard
#   Rule 7: Early Deallocation (MSG_DEALLOC_VGPRS) Epilogue Contract
# ==============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_ROOT="$(cd "${HERE}/.." && pwd)"

: "${ROCM:=/opt/rocm}"
: "${BUILD:=${ENGINE_ROOT}/build_hip}"

PY_CHECKER="${HERE}/check_isa_compliance.py"

if [ ! -f "${PY_CHECKER}" ]; then
    echo "Error: Python checker engine ${PY_CHECKER} not found." >&2
    exit 1
fi

TARGET=""
STRICT=0
JSON=0
EXTRA_ARGS=()

show_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [TARGET]

Options:
  --strict          Fail (exit non-zero) on any VGPR cliff danger window or scratch spill.
  --json            Output detailed diagnostics in JSON format.
  --rocm <path>     Explicit ROCm path (default: /opt/rocm).
  -h, --help        Show this help message.

Target:
  Path to a build directory (e.g. build_hip), a shared library (e.g. libr4d.so),
  or an individual code object (.co or .hip.o). If omitted, defaults to \${BUILD}.

Examples:
  ./scripts/check_isa_compliance.sh
  ./scripts/check_isa_compliance.sh --strict
  ./scripts/check_isa_compliance.sh build_hip/radiance_home/kernels/libr4d.so
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict)
            STRICT=1
            EXTRA_ARGS+=("--strict")
            shift
            ;;
        --json)
            JSON=1
            EXTRA_ARGS+=("--json")
            shift
            ;;
        --rocm)
            ROCM="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            if [ -z "${TARGET}" ]; then
                TARGET="$1"
            else
                EXTRA_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

if [ -z "${TARGET}" ]; then
    if [ -d "${BUILD}" ]; then
        TARGET="${BUILD}"
    elif [ -f "${ENGINE_ROOT}/build_hip/radiance_home/kernels/libr4d.so" ]; then
        TARGET="${ENGINE_ROOT}/build_hip/radiance_home/kernels/libr4d.so"
    elif [ -d "${ENGINE_ROOT}/build" ]; then
        TARGET="${ENGINE_ROOT}/build"
    else
        echo "Error: No target specified and default build directory (${BUILD}) not found." >&2
        echo "Please specify a build directory or kernel library path." >&2
        exit 1
    fi
fi

exec python3 "${PY_CHECKER}" --rocm "${ROCM}" "${EXTRA_ARGS[@]}" "${TARGET}"
