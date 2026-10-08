#!/usr/bin/env bash
# ==============================================================================
# verify_ground_truth.sh — Physical Verification & Epistemic Integrity Gate
# ==============================================================================
# Pre-commit entry point: runs the Tier 0 static checks
# (scripts/check_epistemic_invariants.py) on this checkout and its build_hip, and
# blocks commits that touch baselines/ without RADIANCE_GATE_CHANGE=1.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

BUILD_DIR="${BUILD_DIR:-${REPO_ROOT}/build_hip}"

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--build-dir PATH]"
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
        # Baselines, seals and thresholds only change with an explicit human decision.
        GATE_FILES=$(echo "${STAGED_FILES}" | grep -E '^baselines/' || true)
        if [ -n "${GATE_FILES}" ] && [ "${RADIANCE_GATE_CHANGE:-0}" != "1" ]; then
            echo "❌ This commit changes gate baselines or thresholds:" >&2
            echo "${GATE_FILES}" | sed 's/^/     /' >&2
            git diff --cached --stat -- baselines/ >&2
            echo "   Re-run with RADIANCE_GATE_CHANGE=1 git commit ... if this is intended." >&2
            exit 1
        fi
        CODE_FILES=$(echo "${STAGED_FILES}" | grep -E '\.(cpp|hip|h|hpp|c|py|sh)$|CMakeLists\.txt|^baselines/|^scripts/' || true)
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
    --repo-root "${REPO_ROOT}" \
    --build-dir "${BUILD_DIR}"

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
echo " 🏆 TIER 0 STATIC CHECKS PASSED."
echo "================================================================================"
exit 0
