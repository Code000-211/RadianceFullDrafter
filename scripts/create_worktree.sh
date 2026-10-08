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

# Never touch an existing worktree: it may hold uncommitted or unpushed work.
if [ -e "${WORKTREE_DIR}" ]; then
    echo "❌ '${WORKTREE_DIR}' already exists. Use it as is, or remove it yourself" >&2
    echo "   (git worktree remove ${WORKTREE_DIR}) after checking its contents." >&2
    exit 1
fi
if git -C "${REPO_ROOT}" show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
    echo "❌ Branch '${BRANCH_NAME}' already exists; pick another name or delete the branch yourself." >&2
    exit 1
fi

git -C "${REPO_ROOT}" worktree add -b "${BRANCH_NAME}" "${WORKTREE_DIR}" "${BASE_BRANCH}"

# No binaries are copied from main: the worktree builds its own build_hip, so a
# failed or partial build can never be mistaken for the candidate.

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
echo "     cmake -B build_hip -S . -G Ninja -DCMAKE_BUILD_TYPE=Release -DRAD_WITH_HIP=ON -DRAD_GPU_TARGETS=gfx1201 -DRAD_BUILD_TESTS=ON"
echo "     ninja -C build_hip"
echo ""
echo "  4. Or queue the lever for the full build + gate run:"
echo "     python3 scripts/lever_queue.py add <slug> && python3 scripts/lever_queue.py run"
echo "================================================================================"
