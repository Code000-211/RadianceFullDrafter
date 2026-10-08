#!/usr/bin/env bash
set -euo pipefail

# RadianceMine Project-level Linter and Epistemic Gate Hook
# Invoked by auto-lint plugin (PostToolUse) on every file write/edit.

FILE="${1:-}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$FILE" ]]; then
  exit 0
fi

# 1. For C/C++/HIP headers or sources, run fast Tier 0 Epistemic Invariants Check (takes ~135ms)
case "$FILE" in
  *.h|*.hpp|*.cpp|*.hip|*.c)
    python3 "$ROOT_DIR/scripts/check_epistemic_invariants.py"
    ;;
esac
