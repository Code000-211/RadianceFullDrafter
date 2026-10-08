#!/usr/bin/env bash
# ==============================================================================
# dispatch_goal.sh — Set a High-Level Goal & Trigger Autonomous Pipeline
# ==============================================================================
# Rule 1, 3, 5, 6 of ENGINEERING_CONSTITUTION.md:
# The user provides a goal; the system handles:
# 1. Scoped research if new (Claude) or matches existing candidate lever.
# 2. Automated worktree creation & build.
# 3. 4-Tier Master Gate execution on dual AMD Radeon AI PRO R9700 GPUs.
# 4. Automatic PR on pass, or review loop on regression.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GOAL="${1:-}"
LEVER_SLUG="${2:-}"

if [ -z "${GOAL}" ]; then
    echo "❌ ERROR: Goal description is required." >&2
    echo "Usage: $0 \"<goal_description>\" [candidate_lever_slug]" >&2
    echo "Example: $0 \"Accelerate P2P All-Reduce with Store Drain\" lever6_fast_store_drain_p2p_ar" >&2
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "❌ ERROR: GitHub CLI ('gh') is not installed or not in PATH." >&2
    exit 1
fi

echo "================================================================================"
echo " 🎯 Registering Objective: ${GOAL}"
echo " Workspace: ${REPO_ROOT}"
echo "================================================================================"

# Check if an existing candidate package matches
CANDIDATE_PATH=""
if [ -n "${LEVER_SLUG}" ] && [ -d "${REPO_ROOT}/candidates/${LEVER_SLUG}" ]; then
    CANDIDATE_PATH="candidates/${LEVER_SLUG}"
    echo "✓ Matched existing candidate package: ${CANDIDATE_PATH}"
fi

# Generate scoped issue body using generate_agent_context.py
if [ -n "${CANDIDATE_PATH}" ]; then
    BODY=$(python3 "${SCRIPT_DIR}/generate_agent_context.py" \
        --role implementation \
        --lever "${LEVER_SLUG}" \
        --worktree "${REPO_ROOT}/worktrees/${LEVER_SLUG}")
    
    LABEL="status:ready-to-test"
    ISSUE_TITLE="🚀 Goal: ${GOAL} (${LEVER_SLUG})"
else
    BODY=$(python3 "${SCRIPT_DIR}/generate_agent_context.py" \
        --role research \
        --goal "${GOAL}")
    
    LABEL="research:new-lever"
    ISSUE_TITLE="🎯 Goal: ${GOAL}"
fi

echo "Creating GitHub tracking issue..."
ISSUE_URL=$(gh issue create \
    --title "${ISSUE_TITLE}" \
    --label "${LABEL}" \
    --body "${BODY}")

ISSUE_NUM="$(basename "${ISSUE_URL}")"
echo "✓ Issue created: ${ISSUE_URL} (#${ISSUE_NUM})"

# If we have an existing candidate, immediately execute the gate runner!
if [ -n "${CANDIDATE_PATH}" ]; then
    echo ""
    echo "⚡ Launching isolated worktree test for ${LEVER_SLUG} on physical GPUs..."
    bash "${SCRIPT_DIR}/test_candidate_lever.sh" "${LEVER_SLUG}" --issue "${ISSUE_NUM}"
else
    echo ""
    echo "⏳ Goal queued for Research Agent (Claude). Once packaged in candidates/, testing will trigger automatically."
fi
