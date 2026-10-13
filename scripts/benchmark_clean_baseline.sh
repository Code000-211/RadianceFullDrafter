#!/usr/bin/env bash
# ==============================================================================
# benchmark_clean_baseline.sh — Pure Opt 146 Golden Baseline Benchmark Runner
# ==============================================================================
# Runs Tier 1 Greedy Parity and Tier 2 BetterBench against the certified Opt 146
# baseline build with golden configuration:
#   - Speculative Depth: Dynamic Ladder up to 5 (NUM_SPECULATIVE_TOKENS=5)
#   - VRAM Budget: 0 checkpoint slots (saves 232 MiB VRAM for expert cache)
#   - Staging: Double-buffering (RADIANCE_PREFILL_BUFFERS=2)
#   - Headroom: 96 MiB (Opt 146 standard)
#   - Overlap: CED predictive prefetch active (no-ced-prefetch removed)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"
PORT="${PORT:-8000}"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
OUT_DIR="${OUT_DIR:-${REPO_ROOT}/reports/baseline_opt146_${TIMESTAMP}}"
mkdir -p "${OUT_DIR}"

echo "======================================================================"
echo " RadianceMine Opt 146 Golden Baseline Benchmark"
echo " Build directory: ${BUILD_DIR}"
echo " Port:            ${PORT}"
echo " Report output:   ${OUT_DIR}"
echo "======================================================================"

# Check if any rogue radiance process is currently running
RUNNING_PIDS=$(pgrep -f "bin/radiance" || true)
if [ -n "${RUNNING_PIDS}" ]; then
    echo "⚠️  Found running radiance process(es): ${RUNNING_PIDS}"
    echo "Aborting. Please stop running engines before benchmarking." >&2
    exit 3
fi

# Export Golden Baseline Parameters
export NUM_SPECULATIVE_TOKENS=5
export CHECKPOINT_SLOTS=0
export RADIANCE_PREFILL_BUFFERS=2
export GPU_HEADROOM_MIB=96
export RADIANCE_RIDGEFILL="${RADIANCE_RIDGEFILL:-speed}"

ENGINE_LOG="${OUT_DIR}/engine.log"

echo "1. Starting Engine in background (log: ${ENGINE_LOG})..."
bash "${SCRIPT_DIR}/start_engine.sh" --build-dir "${BUILD_DIR}" --port "${PORT}" > "${ENGINE_LOG}" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo ""
    echo "Shutting down engine (PID: ${SERVER_PID})..."
    kill -TERM "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
    echo "Engine stopped."
}
trap cleanup EXIT INT TERM

echo "Waiting for engine readiness on port ${PORT}..."
READY=0
for i in $(seq 1 120); do
    if curl -s "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
        READY=1
        break
    fi
    if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        echo "❌ Engine exited unexpectedly. Check ${ENGINE_LOG}" >&2
        exit 1
    fi
    sleep 2
done

if [ "${READY}" -ne 1 ]; then
    echo "❌ Engine timed out waiting for port ${PORT}" >&2
    exit 1
fi
echo "✅ Engine is ready and responsive."

echo ""
echo "======================================================================"
echo "2. Running Tier 1: Strict Greedy Parity Gate"
echo "======================================================================"
PARITY_REPORT="${OUT_DIR}/parity_report.json"
set +e
python3 "${SCRIPT_DIR}/parity_check.py" \
    --endpoint "http://127.0.0.1:${PORT}/v1" \
    --suite full \
    --token-tolerance "${TOKEN_TOLERANCE:-5}" \
    --json-out "${PARITY_REPORT}"
PARITY_RC=$?
set -e

if [ "${PARITY_RC}" -ne 0 ]; then
    echo "❌ Parity check failed (rc=${PARITY_RC}). See ${PARITY_REPORT}" >&2
    exit "${PARITY_RC}"
fi
echo "✅ Tier 1 Parity Gate PASSED."

echo ""
echo "======================================================================"
echo "3. Running Tier 2: BetterBench Suite"
echo "======================================================================"
BENCH_CFG="${REPO_ROOT}/baselines/bench_config.json"
BETTERBENCH_RAW="${OUT_DIR}/betterbench_raw.json"
SCORE_FILE="${OUT_DIR}/score.json"

python3 "${SCRIPT_DIR}/run_betterbench_gate.py" \
    --port "${PORT}" \
    --bench-config "${BENCH_CFG}" \
    --betterbench-path "/opt/BetterBench" \
    --raw-out "${BETTERBENCH_RAW}" \
    --score-out "${SCORE_FILE}"

echo ""
echo "======================================================================"
echo " Benchmark Run Complete"
echo " Full Report: ${OUT_DIR}"
echo " Score JSON:  ${SCORE_FILE}"
echo "======================================================================"
