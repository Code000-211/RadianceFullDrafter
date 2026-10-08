#!/usr/bin/env bash
# ==============================================================================
# create_worktree.sh — Isolated Git Worktree Provisioner for RadianceMine
# ==============================================================================
# Rule 3 of ENGINEERING_CONSTITUTION.md:
#   - Main is ALWAYS frozen to the latest winning build.
#   - All development happens in dedicated, isolated Git worktrees (worktrees/<feature_name>).
#   - Never edit trunk directly.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

FEATURE_NAME="${1:-}"
BASE_BRANCH="${BASE_BRANCH:-main}"

if [ -z "${FEATURE_NAME}" ]; then
    echo "❌ ERROR: Feature / Worktree name is required." >&2
    echo "Usage: $0 <feature_name> [base_branch]" >&2
    echo "Example: $0 lever1_gdn_qsa_fusion" >&2
    exit 1
fi

# Clean up feature name
FEATURE_SLUG="$(echo "${FEATURE_NAME}" | tr ' /' '_-' | sed 's/[^a-zA-Z0-9_-]//g')"
WORKTREE_DIR="${REPO_ROOT}/worktrees/${FEATURE_SLUG}"
BRANCH_NAME="worktree/${FEATURE_SLUG}"

echo "================================================================================"
echo " 🌿 Provisioning Isolated Git Worktree for: ${FEATURE_SLUG}"
echo " Base Commit:   ${BASE_BRANCH} ($(git -C "${REPO_ROOT}" rev-parse --short "${BASE_BRANCH}"))"
echo " Target Path:   ${WORKTREE_DIR}"
echo " Branch Name:   ${BRANCH_NAME}"
echo "================================================================================"

# Check if worktree directory already exists
if [ -d "${WORKTREE_DIR}" ]; then
    echo "ℹ️  Worktree directory '${WORKTREE_DIR}' already exists."
    echo "   Cleaning and resetting worktree state to pristine '${BASE_BRANCH}'..."
    git -C "${WORKTREE_DIR}" checkout -f "${BASE_BRANCH}" 2>/dev/null || git -C "${WORKTREE_DIR}" checkout -f -B "${BRANCH_NAME}" "${BASE_BRANCH}"
    git -C "${WORKTREE_DIR}" reset --hard "${BASE_BRANCH}" 2>/dev/null || true
    git -C "${WORKTREE_DIR}" clean -fd 2>/dev/null || true
    echo "✓ Worktree cleaned and synchronized with '${BASE_BRANCH}'."
    exit 0
fi

# Check if branch exists
if git -C "${REPO_ROOT}" show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
    echo "ℹ️  Branch '${BRANCH_NAME}' already exists. Attaching worktree..."
    git -C "${REPO_ROOT}" worktree add "${WORKTREE_DIR}" "${BRANCH_NAME}"
else
    echo "Creating new branch '${BRANCH_NAME}' branched from '${BASE_BRANCH}'..."
    git -C "${REPO_ROOT}" worktree add -b "${BRANCH_NAME}" "${WORKTREE_DIR}" "${BASE_BRANCH}"
fi

# Initialize isolated build environment directory
mkdir -p "${WORKTREE_DIR}/build_hip/bin"
mkdir -p "${WORKTREE_DIR}/build_hip/radiance_home"
if [ -d "${REPO_ROOT}/build_hip/radiance_home" ]; then
    cp -rn "${REPO_ROOT}/build_hip/radiance_home/"* "${WORKTREE_DIR}/build_hip/radiance_home/" 2>/dev/null || true
fi
if [ -d "${REPO_ROOT}/build_hip/bin" ]; then
    cp -rn "${REPO_ROOT}/build_hip/bin/"* "${WORKTREE_DIR}/build_hip/bin/" 2>/dev/null || true
fi

# Check if corresponding candidate lever exists
CANDIDATE_PATH="${REPO_ROOT}/candidates/${FEATURE_SLUG}"
if [ ! -d "${CANDIDATE_PATH}" ]; then
    # Search for partial match
    MATCH=$(find "${REPO_ROOT}/candidates" -maxdepth 1 -type d -name "*${FEATURE_SLUG}*" 2>/dev/null | head -n 1 || true)
    if [ -n "${MATCH}" ]; then
        CANDIDATE_PATH="${MATCH}"
    fi
fi

echo ""
echo "================================================================================"
echo " ✅ WORKTREE READY: ${WORKTREE_DIR}"
echo "================================================================================"
echo "Next Steps:"
echo "  1. Switch to worktree:"
echo "     cd ${WORKTREE_DIR}"

if [ -f "${CANDIDATE_PATH}/lever.patch" ]; then
    echo ""
    echo "  2. Apply candidate patch directly:"
    echo "     git apply ${CANDIDATE_PATH}/lever.patch"
fi

echo ""
echo "  3. Compile test targets in isolation:"
echo "     cmake -B build_hip -S . -DCMAKE_BUILD_TYPE=Release"
echo "     cmake --build build_hip --target arch_test -j\$(nproc)"
echo ""
echo "  4. Execute 3-Tier Regression Gate before requesting merge:"
echo "     bash scripts/gate_check.sh"
echo "================================================================================"
