#!/usr/bin/env bash
# ==============================================================================
# upstream_watcher_manager.sh — Daemon Lifecycle Manager for Upstream Watcher
# ==============================================================================
# Starts, stops, and checks the status of the permanent upstream watcher.
# Automatically monitors Codeberg (StillDeadcode/radiance) in the background.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PID_FILE="${REPO_ROOT}/telemetry/watcher.pid"
LOG_FILE="${REPO_ROOT}/telemetry/watcher.log"

INTERVAL="${INTERVAL:-300}"
CREATE_ISSUES="${CREATE_ISSUES:-1}"
CREATE_PRS="${CREATE_PRS:-1}"

COMMAND="${1:-status}"
shift || true

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        --no-issues)
            CREATE_ISSUES=0
            shift
            ;;
        --no-prs)
            CREATE_PRS=0
            shift
            ;;
        *)
            shift
            ;;
    esac
done

mkdir -p "${REPO_ROOT}/telemetry"

is_running() {
    if [ -f "${PID_FILE}" ]; then
        local pid
        pid=$(cat "${PID_FILE}")
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

start_watcher() {
    if is_running; then
        local pid
        pid=$(cat "${PID_FILE}")
        echo "✓ Upstream watcher is already running (PID: ${pid})."
        return 0
    fi

    echo "🚀 Starting Upstream Watcher daemon in background..."
    echo "  • Polling interval: ${INTERVAL}s"
    echo "  • Create GitHub Issues: $([ "${CREATE_ISSUES}" = "1" ] && echo "YES" || echo "NO")"
    echo "  • Create GitHub Draft PRs: $([ "${CREATE_PRS}" = "1" ] && echo "YES" || echo "NO")"
    echo "  • Log file: ${LOG_FILE}"

    local args=("--daemon" "--interval" "${INTERVAL}")
    if [ "${CREATE_ISSUES}" = "1" ]; then
        args+=("--create-issues")
    fi
    if [ "${CREATE_PRS}" = "1" ]; then
        args+=("--create-prs")
    fi

    nohup python3 -u "${SCRIPT_DIR}/watch_upstream.py" "${args[@]}" >> "${LOG_FILE}" 2>&1 &
    local new_pid=$!
    echo "${new_pid}" > "${PID_FILE}"
    sleep 1

    if is_running; then
        echo "✅ Upstream Watcher daemon successfully started (PID: ${new_pid})."
    else
        echo "❌ ERROR: Watcher failed to start. Last log lines:"
        tail -n 20 "${LOG_FILE}"
        return 1
    fi
}

stop_watcher() {
    if ! is_running; then
        echo "ℹ️  Upstream watcher is not running."
        rm -f "${PID_FILE}"
        return 0
    fi

    local pid
    pid=$(cat "${PID_FILE}")
    echo "🛑 Stopping Upstream Watcher (PID: ${pid})..."
    kill -15 "${pid}" 2>/dev/null || true

    local count=0
    while kill -0 "${pid}" 2>/dev/null && [ "${count}" -lt 10 ]; do
        sleep 0.5
        count=$((count + 1))
    done

    if kill -0 "${pid}" 2>/dev/null; then
        echo "⚠️ Force killing PID ${pid}..."
        kill -9 "${pid}" 2>/dev/null || true
    fi

    rm -f "${PID_FILE}"
    echo "✅ Upstream Watcher stopped."
}

status_watcher() {
    echo "================================================================================"
    echo " 📡 RadianceMine Upstream Watcher Daemon Status"
    echo "================================================================================"
    if is_running; then
        local pid
        pid=$(cat "${PID_FILE}")
        echo " • Status:  RUNNING (PID: ${pid})"
        echo " • Log:     ${LOG_FILE}"
        if [ -f "${REPO_ROOT}/telemetry/upstream_seen.json" ]; then
            python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
prs = data.get("prs", {})
last_c = data.get("last_checked", 0)
print(f" • Screened PRs: {len(prs)}")
if last_c:
    import time
    print(f" • Last Poll:    {time.strftime(\"%Y-%m-%d %H:%M:%S\", time.localtime(last_c))}")
' "${REPO_ROOT}/telemetry/upstream_seen.json"
        fi
        echo ""
        echo "--- Recent Logs (last 10 lines) ---"
        tail -n 10 "${LOG_FILE}" 2>/dev/null || echo "(no logs yet)"
    else
        echo " • Status:  STOPPED"
        rm -f "${PID_FILE}" 2>/dev/null || true
    fi
    echo "================================================================================"
}

logs_watcher() {
    if [ -f "${LOG_FILE}" ]; then
        tail -f "${LOG_FILE}"
    else
        echo "No log file found at ${LOG_FILE}."
    fi
}

case "${COMMAND}" in
    start)
        start_watcher
        ;;
    stop)
        stop_watcher
        ;;
    restart)
        stop_watcher
        start_watcher
        ;;
    status)
        status_watcher
        ;;
    logs)
        logs_watcher
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs} [--interval <secs>] [--no-issues] [--no-prs]"
        exit 1
        ;;
esac
