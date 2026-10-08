#!/usr/bin/env bash
# ==============================================================================
# engine_manager.sh — Robust GPU Engine Lifecycle & Binary Hot-Swap Manager
# ==============================================================================
# Rule 1 & Rule 3 of ENGINEERING_CONSTITUTION.md:
# Manages stopping, starting, health-checking, and hot-swapping the Radiance
# inference engine across worktrees on dual AMD Radeon AI PRO R9700 GPUs.
# Prevents dual-engine VRAM exhaustion and ensures clean hardware isolation.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

PORT="${PORT:-8000}"
BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"
PID_FILE="/tmp/radiance_engine.pid"
LOG_FILE="/tmp/radiance_engine.log"
TIMEOUT_SECS=45

COMMAND="${1:-status}"
shift || true

# Parse flags
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
        --timeout)
            TIMEOUT_SECS="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

get_running_pid() {
    pgrep -f "bin/radiance" | head -n 1 || true
}

cmd_status() {
    PID=$(get_running_pid)
    echo "================================================================================"
    echo " 🔍 Radiance Engine Status"
    echo "================================================================================"
    if [ -n "${PID}" ]; then
        echo " • State:   🟢 RUNNING (PID: ${PID})"
        echo " • Port:    ${PORT}"
        # Check endpoint
        if curl -s --max-time 2 "http://localhost:${PORT}/v1/models" >/dev/null 2>&1; then
            MODEL_INFO=$(curl -s --max-time 2 "http://localhost:${PORT}/v1/models" | jq -r '.data[0].id // "unknown"' 2>/dev/null || echo "active")
            echo " • Health:  ✅ Responsive (Model: ${MODEL_INFO})"
        else
            echo " • Health:  ⚠️  Process running but /v1/models not responding yet"
        fi
        # GPU VRAM check
        if command -v rocm-smi >/dev/null 2>&1; then
            echo " • VRAM:    $(rocm-smi --showmeminfo vram 2>/dev/null | grep -E "VRAM Total Used Memory" | tr '\n' ' ' || echo 'N/A')"
        fi
    else
        echo " • State:   ⚪ STOPPED (No engine process running)"
        echo " • Port:    ${PORT} (Free)"
    fi
    echo "================================================================================"
}

cmd_stop() {
    PID=$(get_running_pid)
    if [ -z "${PID}" ]; then
        echo "ℹ️  No running engine found. Nothing to stop."
        rm -f "${PID_FILE}"
        return 0
    fi

    echo "🛑 Stopping Radiance engine (PID: ${PID})..."
    kill -15 "${PID}" 2>/dev/null || true

    # Wait up to 10 seconds for graceful termination
    for i in {1..10}; do
        if ! kill -0 "${PID}" 2>/dev/null; then
            echo "✓ Engine stopped gracefully."
            rm -f "${PID_FILE}"
            sleep 1
            return 0
        fi
        sleep 1
    done

    # Force kill if still lingering
    echo "⚠️  Engine did not stop gracefully. Issuing SIGKILL..."
    kill -9 "${PID}" 2>/dev/null || true
    sleep 2
    rm -f "${PID_FILE}"
    echo "✓ Engine terminated."
}

cmd_start() {
    EXISTING_PID=$(get_running_pid)
    if [ -n "${EXISTING_PID}" ]; then
        echo "❌ ERROR: Engine already running (PID: ${EXISTING_PID}). Stop or restart it first." >&2
        return 1
    fi

    echo "================================================================================"
    echo " 🚀 Starting Radiance Engine"
    echo " Build Dir: ${BUILD_DIR}"
    echo " Port:      ${PORT}"
    echo " Log:       ${LOG_FILE}"
    echo "================================================================================"

    if [ ! -x "${BUILD_DIR}/bin/radiance" ]; then
        echo "❌ FATAL: Engine executable not found at '${BUILD_DIR}/bin/radiance'!" >&2
        return 1
    fi

    nohup bash "${SCRIPT_DIR}/start_engine.sh" --build-dir "${BUILD_DIR}" --port "${PORT}" > "${LOG_FILE}" 2>&1 &
    NEW_PID=$!
    echo "${NEW_PID}" > "${PID_FILE}"
    echo "Engine process launched in background (PID: ${NEW_PID})."

    # Healthcheck polling
    echo -n "Waiting for engine readiness on http://localhost:${PORT}/v1/models"
    START_TIME=$(date +%s)
    while true; do
        if curl -s --max-time 1 "http://localhost:${PORT}/v1/models" >/dev/null 2>&1; then
            echo ""
            echo "✅ Engine is ready and healthy! (took $(($(date +%s) - START_TIME))s)"
            return 0
        fi

        # Check if process died prematurely
        if ! kill -0 "${NEW_PID}" 2>/dev/null; then
            echo ""
            echo "❌ FATAL: Engine process ${NEW_PID} crashed on startup!" >&2
            echo "Tail of ${LOG_FILE}:"
            tail -n 30 "${LOG_FILE}" >&2
            return 1
        fi

        CURRENT_TIME=$(date +%s)
        if [ $((CURRENT_TIME - START_TIME)) -ge "${TIMEOUT_SECS}" ]; then
            echo ""
            echo "❌ ERROR: Healthcheck timed out after ${TIMEOUT_SECS} seconds." >&2
            echo "Tail of ${LOG_FILE}:"
            tail -n 30 "${LOG_FILE}" >&2
            cmd_stop
            return 1
        fi

        echo -n "."
        sleep 1
    done
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_restore_golden() {
    echo "🔄 Restoring Golden Baseline Engine (${REPO_ROOT}/build_hip)..."
    BUILD_DIR="${REPO_ROOT}/build_hip"
    cmd_stop
    cmd_start
}

case "${COMMAND}" in
    status)
        cmd_status
        ;;
    stop)
        cmd_stop
        ;;
    start)
        cmd_start
        ;;
    restart)
        cmd_restart
        ;;
    restore-golden|restore)
        cmd_restore_golden
        ;;
    help|--help|-h)
        echo "Usage: $0 {status|start|stop|restart|restore-golden} [--build-dir <path>] [--port <port>] [--timeout <secs>]"
        exit 0
        ;;
    *)
        echo "❌ Unknown command: ${COMMAND}" >&2
        echo "Usage: $0 {status|start|stop|restart|restore-golden}" >&2
        exit 1
        ;;
esac
