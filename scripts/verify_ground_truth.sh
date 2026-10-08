#!/usr/bin/env bash
# ==============================================================================
# verify_ground_truth.sh — Physical Verification & Epistemic Integrity Gate
# ==============================================================================
# Master ground-truth verification script for RadianceMine.
# Enforces the 5 physical ground-truth invariants:
#   1. Binary Symbol Physical Grounding (nm -D & .so check)
#   2. Test Integrity & Anti-Silent-Skip Policy
#   3. Threshold & Tolerance Immutability Lock (SHA-256 baseline seal)
#   4. Hardware Clock & DPM State Pre-Flight Check
#   5. Context-Mode Transparency & Exit Code Integrity
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"
ENDPOINT="${ENDPOINT:-http://localhost:${PORT:-8000}/v1}"
WARMUP_FLAG=""

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --warmup)
            WARMUP_FLAG="--warmup"
            shift
            ;;
        --endpoint)
            ENDPOINT="$2"
            shift 2
            ;;
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--warmup] [--endpoint URL] [--build-dir PATH]"
            exit 0
            ;;
        *)
            shift
            ;;
    esac
done

# Check if executing in git pre-commit and whether staged files touch code
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)
    if [ -n "${STAGED_FILES}" ]; then
        CODE_FILES=$(echo "${STAGED_FILES}" | grep -E '\.(cpp|hip|h|hpp|c)$|CMakeLists\.txt|baselines/' || true)
        if [ -z "${CODE_FILES}" ]; then
            echo "ℹ️  Pure documentation/metadata commit detected. Skipping binary symbol & GPU hardware checks."
            exit 0
        fi
    fi
fi

echo "================================================================================"
echo " 🔍 RadianceMine Epistemic Ground-Truth & Anti-Hallucination Gate"
echo " Workspace:     ${REPO_ROOT}"
echo " Build Dir:     ${BUILD_DIR}"
echo " Endpoint:      ${ENDPOINT}"
echo "================================================================================"

# Step 1: Pre-flight Verification of Compiled Binaries
if [ ! -d "${BUILD_DIR}/radiance_home/kernels" ]; then
    echo "❌ FATAL: Compiled kernel directory not found at '${BUILD_DIR}/radiance_home/kernels'!" >&2
    echo "   Binary symbol grounding requires compiled .so libraries." >&2
    echo "   Compile before verification: cmake --build ${BUILD_DIR} --target arch_test -j32" >&2
    exit 1
fi

# Step 2: Execute Epistemic Invariants Checker (Tier 0)
python3 "${SCRIPT_DIR}/check_epistemic_invariants.py" \
    --strict \
    --endpoint "${ENDPOINT}" \
    ${WARMUP_FLAG}

CHECK_RC=$?
if [ ${CHECK_RC} -ne 0 ]; then
    echo "❌ Ground truth verification FAILED with exit code ${CHECK_RC}." >&2
    exit ${CHECK_RC}
fi

# Step 3: Verify Pre-Commit Hook Installation
HOOK_PATH="${REPO_ROOT}/.git/hooks/pre-commit"
if [ ! -x "${HOOK_PATH}" ]; then
    echo "⚠️  NOTICE: Pre-commit hook is not installed or not executable at '${HOOK_PATH}'."
    echo "   Installing pre-commit hook automatically..."
    cat > "${HOOK_PATH}" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
echo "🛡️  Running RadianceMine Epistemic Pre-Commit Gate..."
bash "${REPO_ROOT}/scripts/verify_ground_truth.sh"
EOF
    chmod +x "${HOOK_PATH}"
    echo "   ✓ Pre-commit hook successfully installed at '${HOOK_PATH}'."
else
    echo "✓ Pre-commit hook active and executable."
fi

echo ""
echo "================================================================================"
echo " 🏆 GROUND TRUTH VERIFICATION COMPLETE: ALL 5 INVARIANTS SATISFIED."
echo "================================================================================"
exit 0
