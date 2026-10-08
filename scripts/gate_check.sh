#!/usr/bin/env bash
# ==============================================================================
# gate_check.sh — RadianceMine Master Gate for one candidate build
# ==============================================================================
#   Tier 0:     static checks of the candidate source tree and build
#               (scripts/check_epistemic_invariants.py --repo-root/--build-dir)
#   Tier 1 + 2: parity and A/B speed against the baseline build, each in its own
#               freshly started engine (scripts/ab_gate.py)
#   Tier 3:     per-kernel VGPR/spill diff baseline -> candidate (scripts/isa_diff.py)
#
# Fail-closed: a tier that cannot run fails the gate. DRY_RUN never certifies.
# Settings and seals come only from baselines/gate_thresholds.json.
#
# Usage:
#   gate_check.sh --build-dir <candidate build_hip> [--candidate-root <tree>]
#                 [--baseline-build-dir <dir>] [--out <dir>] [--abba]
#                 [--candidate-arg <engine flag>]... [--candidate-env KEY=VALUE]...
#                 [--tier 0|ab|3|all]
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_TIER="all"
BUILD_DIR=""
CANDIDATE_ROOT=""
BASELINE_BUILD_DIR="${REPO_ROOT}/build_hip"
OUT_DIR=""
AB_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier) TARGET_TIER="$2"; shift 2 ;;
        --build-dir) BUILD_DIR="$2"; shift 2 ;;
        --candidate-root) CANDIDATE_ROOT="$2"; shift 2 ;;
        --baseline-build-dir) BASELINE_BUILD_DIR="$2"; shift 2 ;;
        --out) OUT_DIR="$2"; shift 2 ;;
        --abba) AB_ARGS+=("--abba"); shift ;;
        --candidate-arg) AB_ARGS+=("--candidate-arg=$2"); shift 2 ;;
        --candidate-env) AB_ARGS+=("--candidate-env=$2"); shift 2 ;;
        --help|-h) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "❌ Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "❌ DRY_RUN=1: the gate measures nothing in a dry run and cannot certify anything." >&2
    exit 10
fi
if [ -z "${BUILD_DIR}" ] || [ ! -x "${BUILD_DIR}/bin/radiance" ]; then
    echo "❌ --build-dir must point at the candidate build (no bin/radiance in '${BUILD_DIR}')." >&2
    exit 1
fi
BUILD_DIR="$(realpath "${BUILD_DIR}")"
CANDIDATE_ROOT="$(realpath "${CANDIDATE_ROOT:-${BUILD_DIR}/..}")"
OUT_DIR="${OUT_DIR:-${CANDIDATE_ROOT}/gate_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "${OUT_DIR}"

echo "================================================================================"
echo " 🛡️  RadianceMine Master Gate"
echo " Candidate tree:  ${CANDIDATE_ROOT} ($(git -C "${CANDIDATE_ROOT}" rev-parse --short HEAD 2>/dev/null || echo 'no git'))"
echo " Candidate build: ${BUILD_DIR}"
echo " Baseline build:  ${BASELINE_BUILD_DIR}"
echo " Tier:            ${TARGET_TIER}"
echo " Results:         ${OUT_DIR}"
echo "================================================================================"

if [ "${RADIANCE_HEAT_RESIDENCY:-0}" != "0" ]; then
    echo "❌ RADIANCE_HEAT_RESIDENCY='${RADIANCE_HEAT_RESIDENCY}' is set; unset it before gating." >&2
    exit 1
fi
if pgrep -f "gpu_sentinel" >/dev/null 2>&1; then
    echo "❌ gpu_sentinel is running and would disturb the measurement; stop it first." >&2
    exit 1
fi

TIERS_RUN=()

run_tier0() {
    echo ""
    echo "=== Tier 0: static checks of the candidate tree ==="
    python3 "${SCRIPT_DIR}/check_epistemic_invariants.py" \
        --repo-root "${CANDIDATE_ROOT}" --build-dir "${BUILD_DIR}"
    TIERS_RUN+=(0)
}

run_tier_ab() {
    echo ""
    echo "=== Tier 1 + 2: parity and A/B speed ==="
    python3 "${SCRIPT_DIR}/ab_gate.py" \
        --baseline-build "${BASELINE_BUILD_DIR}" \
        --candidate-build "${BUILD_DIR}" \
        --out "${OUT_DIR}/ab" \
        "${AB_ARGS[@]}"
    TIERS_RUN+=(1 2)
}

run_tier3() {
    echo ""
    echo "=== Tier 3: ISA diff baseline -> candidate ==="
    python3 "${SCRIPT_DIR}/isa_diff.py" "${BASELINE_BUILD_DIR}" "${BUILD_DIR}" \
        --json-out "${OUT_DIR}/isa_diff.json"
    TIERS_RUN+=(3)
}

case "${TARGET_TIER}" in
    0) run_tier0 ;;
    ab) run_tier_ab ;;
    3) run_tier3 ;;
    all)
        run_tier0
        run_tier3
        run_tier_ab
        ;;
    *) echo "❌ Unknown tier '${TARGET_TIER}'. Must be 0, ab, 3 or all." >&2; exit 1 ;;
esac

echo ""
echo "================================================================================"
if [ "${TARGET_TIER}" = "all" ]; then
    echo " 🏆 ALL TIERS PASSED (ran: ${TIERS_RUN[*]}). Report: ${OUT_DIR}/ab/report.md"
else
    echo " ✓ Tier(s) ${TIERS_RUN[*]} passed. Partial run, not a certification."
fi
echo "================================================================================"
exit 0
