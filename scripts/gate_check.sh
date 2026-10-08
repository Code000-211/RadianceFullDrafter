#!/usr/bin/env bash
# ==============================================================================
# gate_check.sh — RadianceMine Master Regression & Quality Gate
# ==============================================================================
# Rule 1 & Rule 5 of ENGINEERING_CONSTITUTION.md:
# No code is EVER merged into main unless it passes the Master Quality Gates:
#   - Tier 0: Epistemic Ground-Truth Gate (scripts/check_epistemic_invariants.py)
#   - Tier 1: Parity Check Gate (scripts/parity_check.py --suite full)
#   - Tier 2: BetterBench Composite Gate (scripts/check_composite_gate.py)
#   - Tier 3: RDNA4 ISA & Hardware Invariants (scripts/verify_rdna4_invariants.sh)
#
# Fail-closed: a tier that cannot run fails the gate. DRY_RUN never certifies.
# Thresholds come only from baselines/gate_thresholds.json.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_TIER="${1:-all}"
ENDPOINT="${ENDPOINT:-http://localhost:${PORT:-8000}/v1}"
MODEL="${MODEL:-qwen4exp}"
BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"
CANDIDATE_JSON="${CANDIDATE_JSON:-}"
BASELINE_JSON="${BASELINE_JSON:-${REPO_ROOT}/baselines/baseline_opt146.json}"

# Parse optional command line flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            TARGET_TIER="$2"
            shift 2
            ;;
        --endpoint)
            ENDPOINT="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --bench-json|--candidate-json)
            CANDIDATE_JSON="$2"
            shift 2
            ;;
        --baseline-json)
            BASELINE_JSON="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--tier 0|1|2|3|all] [--endpoint URL] [--bench-json PATH] [--build-dir PATH]"
            exit 0
            ;;
        *)
            if [[ "$1" =~ ^(0|1|2|3|all)$ ]]; then
                TARGET_TIER="$1"
            fi
            shift
            ;;
    esac
done

echo "================================================================================"
echo " 🛡️  RadianceMine 4-Tier Master Push & Merge Gate"
echo " Workspace:     ${REPO_ROOT}"
echo " Baseline:      Opt 146 (1a4455d26871100a6a97e1dd3b5c83d4431764b6)"
echo " Evaluation:    Tier '${TARGET_TIER}'"
echo " Endpoint:      ${ENDPOINT}"
echo "================================================================================"

if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "❌ DRY_RUN=1: the gate measures nothing in a dry run and cannot certify anything." >&2
    exit 10
fi

TIERS_RUN=()

# ==============================================================================
# Pre-Flight Gate: Environment Sanitation & Forensic Invariants
# ==============================================================================
echo ""
echo "[Pre-Flight] Auditing Runtime Environment for Toxic Flags..."

ENV_DIRTY=0

# 1. Prohibit RADIANCE_HEAT_RESIDENCY > 0
if [ "${RADIANCE_HEAT_RESIDENCY:-0}" != "0" ]; then
    echo "❌ FATAL: RADIANCE_HEAT_RESIDENCY is set to '${RADIANCE_HEAT_RESIDENCY}'." >&2
    echo "   Forensic audit proved that non-zero residency locks cold MoE experts in VRAM" >&2
    echo "   and forces active Code/Math experts into PCIe Zero-Copy. Unset this variable." >&2
    ENV_DIRTY=1
fi

# 2. Prohibit uncalibrated static draft depth override
if [ "${NUM_SPECULATIVE_TOKENS:-0}" != "0" ] && [ "${NUM_SPECULATIVE_TOKENS:-0}" -gt 3 ]; then
    echo "⚠️  WARNING: NUM_SPECULATIVE_TOKENS is statically overridden to '${NUM_SPECULATIVE_TOKENS}'." >&2
    echo "   Opt 146 calibrated ladder uses dynamic depth [3..5] with automatic fallback." >&2
fi

# 3. Check for rogue gpu_sentinel processes
if pgrep -f "gpu_sentinel" >/dev/null 2>&1; then
    echo "❌ FATAL: Active 'gpu_sentinel' background daemon detected!" >&2
    echo "   Background pulse kernels inject continuous command-queue interrupts and bus traffic." >&2
    echo "   Terminating rogue sentinel..." >&2
    pkill -9 -f "gpu_sentinel" || true
    echo "   Sentinel killed. Proceeding with sanitized environment."
fi

if [ ${ENV_DIRTY} -ne 0 ]; then
    echo "❌ Pre-flight environment sanitation FAILED. Aborting gate check." >&2
    exit 1
fi
echo "✓ Pre-flight environment certified clean."

# ==============================================================================
# Tier 0: Epistemic Ground-Truth & Anti-Hallucination Gate
# ==============================================================================
run_tier0() {
    echo ""
    echo "================================================================================"
    echo " Executing Tier 0: Epistemic Ground-Truth & Anti-Hallucination Gate"
    echo "================================================================================"
    python3 "${SCRIPT_DIR}/check_epistemic_invariants.py" \
        --strict \
        --endpoint "${ENDPOINT}"
    TIERS_RUN+=(0)
}

# ==============================================================================
# Tier 1: Parity Check Gate (Greedy Bit-Exactness & Throughput Floors)
# ==============================================================================
run_tier1() {
    echo ""
    echo "================================================================================"
    echo " Executing Tier 1: Parity Check Gate"
    echo "================================================================================"
    
    TIER1_JSON="${REPO_ROOT}/baselines/tier1_gate_results.json"
    
    if ! curl -s --max-time 3 "${ENDPOINT}/models" >/dev/null 2>&1; then
        echo "❌ FAIL: Tier 1 needs a running inference server at ${ENDPOINT}; none answered." >&2
        return 2
    fi

    python3 "${SCRIPT_DIR}/parity_check.py" \
        --endpoint "${ENDPOINT}" \
        --model "${MODEL}" \
        --suite full \
        --json-out "${TIER1_JSON}"
    TIERS_RUN+=(1)
}

# ==============================================================================
# Tier 2: BetterBench Composite Score Gate
# ==============================================================================
run_tier2() {
    echo ""
    echo "================================================================================"
    echo " Executing Tier 2: BetterBench Composite Score Gate"
    echo "================================================================================"
    
    if [ -z "${CANDIDATE_JSON}" ] || [ ! -f "${CANDIDATE_JSON}" ]; then
        echo "❌ FAIL: Tier 2 needs the candidate's benchmark results via --bench-json (got '${CANDIDATE_JSON}')." >&2
        return 2
    fi
    if [ "$(realpath "${CANDIDATE_JSON}")" = "$(realpath "${BASELINE_JSON}")" ]; then
        echo "❌ FAIL: Tier 2 candidate results are the baseline file itself." >&2
        return 2
    fi

    python3 "${SCRIPT_DIR}/check_composite_gate.py" "${CANDIDATE_JSON}" "${BASELINE_JSON}"
    TIERS_RUN+=(2)
}

# ==============================================================================
# Tier 3: RDNA4 ISA & Hardware Invariants Gate
# ==============================================================================
run_tier3() {
    echo ""
    echo "================================================================================"
    echo " Executing Tier 3: RDNA4 ISA & Hardware Invariants Gate"
    echo "================================================================================"
    
    bash "${SCRIPT_DIR}/verify_rdna4_invariants.sh" "${BUILD_DIR}"
    TIERS_RUN+=(3)
}

# ==============================================================================
# Dispatch Execution
# ==============================================================================
case "${TARGET_TIER}" in
    0)
        run_tier0
        ;;
    1)
        run_tier0
        run_tier1
        ;;
    2)
        run_tier2
        ;;
    3)
        run_tier3
        ;;
    all)
        # Execution order mandated by Rule 1 & Rule 5:
        # Tier 0 (Epistemic Ground-Truth Gate)
        # Tier 1 (Parity & Greedy Exactness Gate)
        # Tier 2 (BetterBench Composite Score Gate)
        # Tier 3 (RDNA4 Hardware & ISA Compliance Gate)
        run_tier0
        run_tier1
        run_tier2
        run_tier3
        ;;
    *)
        echo "❌ Unknown tier '${TARGET_TIER}'. Must be 0, 1, 2, 3, or all." >&2
        exit 1
        ;;
esac

echo ""
echo "================================================================================"
if [ "${TARGET_TIER}" = "all" ]; then
    echo " 🏆 ALL 4 TIERS PASSED (ran: ${TIERS_RUN[*]}). CODE CERTIFIED FOR PROMOTION."
else
    echo " ✓ Tier(s) ${TIERS_RUN[*]} passed. Partial run, not a certification."
fi
echo "================================================================================"
exit 0
