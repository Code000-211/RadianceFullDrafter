#!/usr/bin/env bash
# ==============================================================================
# RadianceMine Engine Startup Script
# Golden Baseline: Build 146 Clean Engine on Dual R9700 (gfx1201)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"
PORT="${PORT:-8000}"
TP="${TP:-2}"
TP_WIRE="${TP_WIRE:-wht6}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

BIN_PATH="${BUILD_DIR}/bin/radiance"
export RADIANCE_HOME="${BUILD_DIR}/radiance_home"

MODEL_PATH="${1:-/root/models/qwen3.8-next-flash-fp8-iq4r-moe/qwen3.8-next-flash-fp8-iq4r-moe.rad}"
if [ $# -gt 0 ]; then shift; fi

# Runtime environment invariants
export RADIANCE_RIDGEFILL="${RADIANCE_RIDGEFILL:-speed}"
export RADIANCE_RIDGEFILL_PROJECTOR="${RIDGEFILL_PROJECTOR:-/root/models/qwen3.8-next-flash-fp8-iq4r-moe/ridgefill}"
export RADIANCE_RIDGEFILL_TAIL=512
export RADIANCE_RIDGEFILL_FINAL=off
export RADIANCE_RIDGEFILL_STAGE=auto
export RADIANCE_RIDGEFILL_FORCE_STREAM=1

export ROCM_PATH="${ROCM_PATH:-/opt/rocm}"
export LD_LIBRARY_PATH="${ROCM_PATH}/lib:${ROCM_PATH}/core-10.0/lib:${LD_LIBRARY_PATH:-}"
export RADIANCE_PREFILL_BUFFERS="${RADIANCE_PREFILL_BUFFERS:-2}"
export RADIANCE_RIDGEFILL_SHARE=0.25
export RADIANCE_RIDGEFILL_ALPHA=1.0
export RADIANCE_ADAPTIVE_SPEC=1
export RADIANCE_HEAT_RESIDENCY=0
export GPU_KEEP_ALIVE=0
export RADIANCE_GDN_ANCHOR="${RADIANCE_GDN_ANCHOR:-1}"

# ==============================================================================
# GPU Power Profile Governance: Compute Mode & DPM Boost
# ==============================================================================
TARGET_GPUS="${HIP_VISIBLE_DEVICES:-}"
if [ -z "${TARGET_GPUS}" ]; then
    TARGET_GPUS=$(seq -s, 0 $((TP - 1)))
fi

IFS=',' read -ra GPU_ARR <<< "${TARGET_GPUS}"
echo "Setting GPU Power Profile to COMPUTE for GPUs: [${TARGET_GPUS}]..."

for GPU in "${GPU_ARR[@]}"; do
    GPU=$(echo "${GPU}" | tr -d ' ')
    SYSFS_PROFILE="/sys/class/drm/card${GPU}/device/pp_power_profile_mode"
    if [ ! -e "${SYSFS_PROFILE}" ] && [ -e "/sys/class/drm/card$((GPU + 1))/device/pp_power_profile_mode" ]; then
        SYSFS_PROFILE="/sys/class/drm/card$((GPU + 1))/device/pp_power_profile_mode"
    fi

    APPLIED=0
    if [ -w "${SYSFS_PROFILE}" ]; then
        if echo "compute" > "${SYSFS_PROFILE}" 2>/dev/null || echo "5" > "${SYSFS_PROFILE}" 2>/dev/null || echo "1" > "${SYSFS_PROFILE}" 2>/dev/null; then
            echo "  ✓ GPU ${GPU}: 'compute' profile set via sysfs (${SYSFS_PROFILE})"
            APPLIED=1
        fi
    fi

    if [ "${APPLIED}" -eq 0 ] && command -v rocm-smi >/dev/null 2>&1; then
        if rocm-smi -d "${GPU}" --setprofile compute >/dev/null 2>&1; then
            echo "  ✓ GPU ${GPU}: 'compute' profile set via rocm-smi"
            APPLIED=1
        fi
    fi
done

echo "======================================================================"
echo " Starting RadianceMine Engine (Clean Build 146)"
echo " Repository:    ${REPO_ROOT}"
echo " Binary:        ${BIN_PATH}"
echo " RADIANCE_HOME: ${RADIANCE_HOME}"
echo " Model:         ${MODEL_PATH}"
echo " Port:          ${PORT} (TP=${TP}, Wire=${TP_WIRE})"
echo "======================================================================"

if [ ! -x "${BIN_PATH}" ]; then
    echo "ERROR: Engine binary not found or not executable at ${BIN_PATH}"
    echo "Compile via: cmake --build ${REPO_ROOT}/build_hip --target radiance -j32"
    exit 1
fi

if [ ! -f "${MODEL_PATH}" ]; then
    echo "ERROR: Model file not found at ${MODEL_PATH}"
    exit 1
fi

WRAPPER=""
if [ -x "/usr/local/bin/with_render" ]; then
    WRAPPER="/usr/local/bin/with_render"
fi

# RADIANCE_ENGINE_PREFIX puts a launcher directly in front of the binary, e.g. rocprofv3 for
# scripts/profile_engine.py: the profiler then wraps only bin/radiance, as libr4d/isa/trace.sh's
# callers do, and not this script and every helper it runs. Split on spaces on purpose.
ENGINE_ARGS=(
  --model "${MODEL_PATH}"
  --port "${PORT}"
  --tp "${TP}"
  --tp-wire "${TP_WIRE}"
  --max-num-seqs 8
  --max-model-len 65536
  --placement expert_tiered
  --ngram-placement auto
  --host-pool-mib 12288
  --gpu-headroom-mib "${GPU_HEADROOM_MIB:-96}"
  --checkpoint-slots "${CHECKPOINT_SLOTS:-0}"
  --vram-kv-mib "${VRAM_KV_MIB:-1600}"
  --kv-cache-dtype fp8
  --num-speculative-tokens "${NUM_SPECULATIVE_TOKENS:-5}"
  --adaptive-spec
  --prefix-cache-host-mib 8192
  --prefix-cache-disk-mib 0
  --prefix-aware-prefetch
  --no-ced-prefetch
  --ridgefill "${RADIANCE_RIDGEFILL}"
  --ridgefill-projector "${RADIANCE_RIDGEFILL_PROJECTOR}"
  --reasoning-effort "${REASONING_EFFORT:-none}"
  --temp 1.0
  --top-p 0.95
  --top-k 20
  --min-p 0.0
  --presence-penalty 0.0
  --repetition-penalty 1.0
  --max-num-batched-tokens 2048
  --checkpoint-interval 2048
  --mm-max-patches 0
  "$@"
)

# RADIANCE_ENGINE_FOREGROUND=1: a run that ends by itself (--diagnose, --kld-ref) listens on no
# port, so there is nothing to wait for and no warmup to send; the engine's exit code is the result.
if [ "${RADIANCE_ENGINE_FOREGROUND:-0}" = "1" ]; then
    rc=0
    # shellcheck disable=SC2086
    $WRAPPER ${RADIANCE_ENGINE_PREFIX:-} "${BIN_PATH}" "${ENGINE_ARGS[@]}" || rc=$?
    exit "${rc}"
fi

# shellcheck disable=SC2086
$WRAPPER ${RADIANCE_ENGINE_PREFIX:-} "${BIN_PATH}" "${ENGINE_ARGS[@]}" &
SERVER_PID=$!

trap "kill -TERM $SERVER_PID 2>/dev/null || true; exit 0" EXIT INT TERM

echo "Waiting for RadianceMine engine to report healthy on port ${PORT}..."
until curl -s "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; do
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "Radiance server exited prematurely."
        wait $SERVER_PID
        exit 1
    fi
    sleep 0.5
done

# Perform Warmup Pass: prime GPU boost clocks and VRAM expert tier
echo "=== Priming GPU Clocks & VRAM Expert Cache ==="
curl -s -X POST "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen4exp","messages":[{"role":"user","content":"Warmup pass to prime GPU boost clocks and load hot MoE expert tier into resident VRAM slab."}],"max_tokens":128,"temperature":0.0}' >/dev/null 2>&1 || true

echo "=== RadianceMine Engine Ready: Port ${PORT} (PID ${SERVER_PID}) ==="
wait $SERVER_PID
