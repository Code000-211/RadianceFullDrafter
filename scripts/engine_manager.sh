#!/usr/bin/env bash
# ==============================================================================
# engine_manager.sh — start/stop/status of one manually run Radiance engine
# ==============================================================================
# The engine runs scripts/start_engine.sh in its own process group; the group id is
# kept in telemetry/engine.pgid and stop only signals that group, never other
# radiance processes (e.g. one started by ab_gate.py).
#
# Usage: engine_manager.sh {status|start|stop|restart} [--build-dir DIR] [--port N] [--timeout S]
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

PORT="${PORT:-8000}"
BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"
PGID_FILE="${REPO_ROOT}/telemetry/engine.pgid"
LOG_FILE="${REPO_ROOT}/telemetry/engine.log"
TIMEOUT_SECS=1200

COMMAND="${1:-status}"
shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir) BUILD_DIR="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --timeout) TIMEOUT_SECS="$2"; shift 2 ;;
        *) echo "❌ Unknown argument: $1" >&2; exit 1 ;;
    esac
done
mkdir -p "${REPO_ROOT}/telemetry"

our_pgid() {
    [ -f "${PGID_FILE}" ] || return 1
    local pgid
    pgid="$(cat "${PGID_FILE}")"
    [ -n "${pgid}" ] && pgrep -g "${pgid}" >/dev/null 2>&1 && echo "${pgid}"
}

cmd_status() {
    local pgid
    if pgid="$(our_pgid)"; then
        echo "RUNNING (process group ${pgid}, port ${PORT})"
        pgrep -a -g "${pgid}" -f "bin/radiance" | cut -c1-160
        curl -s --max-time 2 "http://127.0.0.1:${PORT}/v1/models" >/dev/null && echo "endpoint: healthy" || echo "endpoint: not answering"
    else
        echo "STOPPED (no engine started by engine_manager)"
        local others
        others="$(pgrep -a -f "bin/radiance" | cut -c1-160 || true)"
        [ -n "${others}" ] && echo "other radiance processes:" && echo "${others}"
    fi
}

cmd_stop() {
    local pgid
    if ! pgid="$(our_pgid)"; then
        echo "No engine started by engine_manager is running."
        rm -f "${PGID_FILE}"
        return 0
    fi
    echo "Stopping process group ${pgid}..."
    kill -TERM -- "-${pgid}" 2>/dev/null || true
    for _ in $(seq 1 60); do
        pgrep -g "${pgid}" >/dev/null 2>&1 || { rm -f "${PGID_FILE}"; echo "✓ stopped"; return 0; }
        sleep 1
    done
    echo "⚠️  still running after 60 s, sending SIGKILL"
    kill -KILL -- "-${pgid}" 2>/dev/null || true
    rm -f "${PGID_FILE}"
}

cmd_start() {
    if our_pgid >/dev/null; then
        echo "❌ An engine started by engine_manager is already running; stop it first." >&2
        return 1
    fi
    if pgrep -f "bin/radiance" >/dev/null 2>&1; then
        echo "❌ Another radiance process holds the GPUs:" >&2
        pgrep -a -f "bin/radiance" | cut -c1-160 >&2
        return 1
    fi
    if [ ! -x "${BUILD_DIR}/bin/radiance" ]; then
        echo "❌ Engine executable not found at '${BUILD_DIR}/bin/radiance'" >&2
        return 1
    fi
    setsid bash "${SCRIPT_DIR}/start_engine.sh" --build-dir "${BUILD_DIR}" --port "${PORT}" > "${LOG_FILE}" 2>&1 < /dev/null &
    local pid=$!
    echo "${pid}" > "${PGID_FILE}"
    echo "Engine starting (process group ${pid}, log ${LOG_FILE})"
    local start
    start=$(date +%s)
    until curl -s --max-time 1 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; do
        if ! kill -0 "${pid}" 2>/dev/null; then
            echo "❌ Engine exited during startup:" >&2
            tail -n 30 "${LOG_FILE}" >&2
            rm -f "${PGID_FILE}"
            return 1
        fi
        if [ $(( $(date +%s) - start )) -ge "${TIMEOUT_SECS}" ]; then
            echo "❌ Not ready after ${TIMEOUT_SECS} s" >&2
            cmd_stop
            return 1
        fi
        sleep 2
    done
    echo "✅ Engine ready after $(( $(date +%s) - start )) s"
}

case "${COMMAND}" in
    status) cmd_status ;;
    start) cmd_start ;;
    stop) cmd_stop ;;
    restart) cmd_stop; cmd_start ;;
    *) echo "Usage: $0 {status|start|stop|restart} [--build-dir DIR] [--port N] [--timeout S]" >&2; exit 1 ;;
esac
