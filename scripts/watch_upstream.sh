#!/usr/bin/env bash
# ==============================================================================
# Upstream Codeberg Monitor & Triage Runner
# Automatically monitors https://codeberg.org/StillDeadcode/radiance
# Asks Jev whether open PRs could be useful and writes candidates/upstream/REVIEW.md.
# ==============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${HERE}/watch_upstream.py"

if [ ! -f "${PYTHON_SCRIPT}" ]; then
    echo "Error: ${PYTHON_SCRIPT} not found." >&2
    exit 1
fi

exec python3 "${PYTHON_SCRIPT}" "$@"
