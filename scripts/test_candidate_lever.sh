#!/usr/bin/env bash
# ==============================================================================
# test_candidate_lever.sh — Automated Candidate Lever Gate & Review Lifecycle
# ==============================================================================
# Rule 1, 3 & 6 of ENGINEERING_CONSTITUTION.md:
# Automatically tests candidate levers in isolated worktrees.
# - If Master Gate passes: archives winner, opens PR, marks issue passed.
# - If Master Gate fails: captures regression diff, labels issue 'status:needs-review',
#   and routes telemetry back to Claude / Research Agent for Root Cause Analysis.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CANDIDATE_NAME="${1:-}"
ISSUE_NUM=""
DRY_RUN="${DRY_RUN:-0}"

# Parse optional flags
shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --issue)
            ISSUE_NUM="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

if [ -z "${CANDIDATE_NAME}" ]; then
    echo "❌ ERROR: Candidate name or directory is required." >&2
    echo "Usage: $0 <candidate_folder_or_slug> [--issue <gh_issue_number>] [--dry-run]" >&2
    echo "Example: $0 lever6_fast_store_drain_p2p_ar --issue 42" >&2
    exit 1
fi

# Resolve candidate path
CANDIDATE_SLUG="$(basename "${CANDIDATE_NAME}")"
CANDIDATE_DIR="${REPO_ROOT}/candidates/${CANDIDATE_SLUG}"
PATCH_FILE="${CANDIDATE_DIR}/lever.patch"

if [ ! -d "${CANDIDATE_DIR}" ]; then
    echo "❌ ERROR: Candidate directory not found at '${CANDIDATE_DIR}'." >&2
    exit 1
fi

if [ ! -f "${PATCH_FILE}" ]; then
    echo "❌ ERROR: Patch file not found at '${PATCH_FILE}'." >&2
    exit 1
fi

echo "================================================================================"
echo " 🚀 Testing Candidate Lever: ${CANDIDATE_SLUG}"
echo " Candidate Dir:  ${CANDIDATE_DIR}"
echo " Patch File:     ${PATCH_FILE}"
echo " GitHub Issue:   ${ISSUE_NUM:-'(none)'}"
echo "================================================================================"

# Update GitHub Issue if provided
if [ -n "${ISSUE_NUM}" ] && command -v gh >/dev/null 2>&1; then
    gh issue edit "${ISSUE_NUM}" --add-label "status:in-progress" --remove-label "status:needs-review" 2>/dev/null || true
    gh issue comment "${ISSUE_NUM}" --body "🤖 **AGY Runner**: Started isolated worktree testing for \`${CANDIDATE_SLUG}\` on dual AMD Radeon AI PRO R9700 GPUs." 2>/dev/null || true
fi

# Step 0: Deterministic Patch Safety Check (eval_patch_safety.py)
echo ""
echo "🛡️  [Step 0/4] Deterministic Patch Safety Audit (Zero LLM Tokens)..."
if ! python3 "${SCRIPT_DIR}/eval_patch_safety.py" "${PATCH_FILE}"; then
    echo "❌ FATAL: Candidate patch failed deterministic safety audit!" >&2
    if [ -n "${ISSUE_NUM}" ] && command -v gh >/dev/null 2>&1; then
        gh issue comment "${ISSUE_NUM}" --body "### ❌ Patch Rejected by Deterministic Safety Auditor\n\nAnti-patterns detected in \`${PATCH_FILE}\`. Check worktree logs."
        gh issue edit "${ISSUE_NUM}" --add-label "status:needs-review,regression:detected" --remove-label "status:in-progress"
    fi
    exit 1
fi

# Step 1: Provision Isolated Worktree
WORKTREE_DIR="${REPO_ROOT}/worktrees/${CANDIDATE_SLUG}"
echo ""
echo "🌿 [Step 1/4] Provisioning isolated git worktree..."
bash "${SCRIPT_DIR}/create_worktree.sh" "${CANDIDATE_SLUG}"

# Step 2: Apply Candidate Patch
echo ""
echo "🧩 [Step 2/4] Applying candidate patch..."
cd "${WORKTREE_DIR}"

# Check if patch is already applied
if git apply --check -R "${PATCH_FILE}" 2>/dev/null; then
    echo "ℹ️  Patch is already applied in worktree."
else
    if git apply --check "${PATCH_FILE}" 2>/dev/null; then
        git apply "${PATCH_FILE}"
        echo "✓ Patch cleanly applied to worktree."
    else
        echo "❌ FATAL: Patch does not apply cleanly to current base branch!" >&2
        FAIL_MSG="Patch conflict: \`${PATCH_FILE}\` cannot be applied to base \`$(git rev-parse --short HEAD)\`."
        if [ -n "${ISSUE_NUM}" ] && command -v gh >/dev/null 2>&1; then
            gh issue comment "${ISSUE_NUM}" --body "### ❌ Patch Application Failed\n\n${FAIL_MSG}\n\nRe-routing to Research Agent for rebase."
            gh issue edit "${ISSUE_NUM}" --add-label "status:needs-review,regression:detected" --remove-label "status:in-progress"
        fi
        exit 2
    fi
fi

# Step 3: Compile Worktree Binaries
echo ""
echo "🔨 [Step 3/5] Building binaries in worktree..."
export ROCM_PATH="${ROCM_PATH:-/opt/rocm}"
export HIP_PATH="${HIP_PATH:-/opt/rocm}"
export PATH="${ROCM_PATH}/bin:${ROCM_PATH}/llvm/bin:${PATH}"

if [ ! -f "${WORKTREE_DIR}/build_hip/build.ninja" ]; then
    cmake -B "${WORKTREE_DIR}/build_hip" -S "${WORKTREE_DIR}" -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DRAD_WITH_HIP=ON \
        -DRAD_GPU_TARGETS=gfx1201 \
        -DRAD_BUILD_TESTS=ON
fi
ninja -C "${WORKTREE_DIR}/build_hip" -j32 radiance arch_test || ninja -C "${WORKTREE_DIR}/build_hip" -j32

# Step 4: Hot-Swap Dual-GPU Engine to Candidate Binary
if [ "${DRY_RUN}" != "1" ]; then
    echo ""
    echo "🔄 [Step 4/5] Hot-swapping engine on dual GPUs to worktree candidate..."
    if ! bash "${SCRIPT_DIR}/engine_manager.sh" restart --build-dir "${WORKTREE_DIR}/build_hip"; then
        echo "❌ FATAL: Candidate engine failed to start on dual GPUs!" >&2
        echo "Restoring golden baseline engine..."
        bash "${SCRIPT_DIR}/engine_manager.sh" restore-golden || true
        FAIL_MSG="Candidate engine crashed on startup. See /tmp/radiance_engine.log."
        if [ -n "${ISSUE_NUM}" ] && command -v gh >/dev/null 2>&1; then
            gh issue comment "${ISSUE_NUM}" --body "### ❌ Startup Crash on Dual GPUs\n\n${FAIL_MSG}"
            gh issue edit "${ISSUE_NUM}" --add-label "status:needs-review,regression:detected" --remove-label "status:in-progress"
        fi
        exit 3
    fi
fi

# Step 5: Execute 4-Tier Master Gate on physical GPUs
echo ""
echo "🛡️  [Step 5/5] Executing 4-Tier Master Quality Gate on physical GPUs..."
GATE_LOG="${WORKTREE_DIR}/gate_execution.log"
set +e
DRY_RUN="${DRY_RUN}" bash "${SCRIPT_DIR}/gate_check.sh" --build-dir "${WORKTREE_DIR}/build_hip" 2>&1 | tee "${GATE_LOG}"
GATE_RC=${PIPESTATUS[0]}
set -e

# Collect Structured Telemetry for TypeSafe AI (Jev)
TELEMETRY_JSON="${REPO_ROOT}/telemetry/latest_run.json"
if [ -f "${SCRIPT_DIR}/collect_telemetry.py" ]; then
    python3 "${SCRIPT_DIR}/collect_telemetry.py" \
        --candidate-slug "${CANDIDATE_SLUG}" \
        --gate-log "${GATE_LOG}" \
        --exit-code "${GATE_RC}" \
        --out "${TELEMETRY_JSON}" || true
fi

# Evaluate Gate Outcome
if [ ${GATE_RC} -eq 0 ]; then
    echo ""
    echo "================================================================================"
    echo " 🏆 GATE PASSED: ${CANDIDATE_SLUG} is certified clean and faster!"
    echo "================================================================================"
    
    # Commit change in worktree branch
    git -C "${WORKTREE_DIR}" add -A
    git -C "${WORKTREE_DIR}" commit -m "feat(${CANDIDATE_SLUG}): verified passing 4-tier master gate on dual R9700" 2>/dev/null || true
    
    if [ -n "${ISSUE_NUM}" ] && command -v gh >/dev/null 2>&1; then
        gh issue comment "${ISSUE_NUM}" --body "### 🏆 Master Quality Gate Passed!\n\nCandidate \`${CANDIDATE_SLUG}\` has passed all 4 tiers of \`scripts/gate_check.sh\`.\n\nOpening Pull Request against \`main\`."
        gh issue edit "${ISSUE_NUM}" --add-label "status:gate-passed" --remove-label "status:in-progress,status:needs-review,regression:detected"
        
        PR_URL=$(gh pr create --head "worktree/${CANDIDATE_SLUG}" --base main \
            --title "feat: integrate candidate ${CANDIDATE_SLUG}" \
            --body "Automated PR created by AGY Runner.\n\nCloses #${ISSUE_NUM}.\n\nVerified clean via 4-Tier Master Gate on dual AMD Radeon AI PRO R9700." 2>/dev/null || true)
        echo "✓ Pull Request created: ${PR_URL}"
    fi

    # Restore golden baseline engine on physical GPUs
    if [ "${DRY_RUN}" != "1" ]; then
        echo "🔄 Restoring golden baseline engine..."
        bash "${SCRIPT_DIR}/engine_manager.sh" restore-golden || true
    fi
    exit 0
else
    echo ""
    echo "================================================================================"
    echo " ⚠️  GATE REGRESSION DETECTED: ${CANDIDATE_SLUG} failed gate check (code ${GATE_RC})"
    echo " Restoring Golden Baseline engine and routing failure to Review Loop..."
    echo "================================================================================"
    
    # Immediately restore golden baseline engine so the system remains healthy
    if [ "${DRY_RUN}" != "1" ]; then
        echo "🔄 Restoring golden baseline engine..."
        bash "${SCRIPT_DIR}/engine_manager.sh" restore-golden || true
    fi
    
    # Extract last 40 lines of gate log for diagnostic report
    FAILURE_SNIPPET=$(tail -n 40 "${GATE_LOG}")
    
    # Run TypeSafe AI (Jev System One) Root-Cause Classification on structured telemetry!
    JEV_CLASSIFICATION=""
    if [ -f "${SCRIPT_DIR}/typesafe_triage.py" ]; then
        echo "🧠 Classifying regression root cause with TypeSafe AI (Jev)..."
        JEV_CLASSIFICATION=$(python3 "${SCRIPT_DIR}/typesafe_triage.py" classify-regression "${TELEMETRY_JSON}" 2>/dev/null || true)
    fi
    
    # Write local REGRESSION_REPORT.md
    REPORT_FILE="${WORKTREE_DIR}/REGRESSION_REPORT.md"
    cat > "${REPORT_FILE}" << EOF
# Regression Report: ${CANDIDATE_SLUG}
**Date**: $(date -Iseconds)  
**Exit Code**: ${GATE_RC}  
**Candidate Directory**: \`${CANDIDATE_DIR}\`  
**Worktree**: \`${WORKTREE_DIR}\`  

## 🧠 TypeSafe AI (Jev) Classification
\`\`\`
${JEV_CLASSIFICATION:-'(Classification unavailable)'}
\`\`\`

## Failure Diagnostic
\`\`\`
${FAILURE_SNIPPET}
\`\`\`

## Action Required (Review Loop)
1. Research Agent (Claude) or Engineer must perform Root Cause Analysis.
2. Cross-reference failure with alphaXiv / GitHub for known edge cases or LDS bank conflicts.
3. Update patch in \`${PATCH_FILE}\` and re-test.
EOF
    echo "✓ Regression report saved to: ${REPORT_FILE}"
    
    # Post report to GitHub Issue and trigger review
    if [ -n "${ISSUE_NUM}" ] && command -v gh >/dev/null 2>&1; then
        COMMENT_BODY=$(cat << EOF
### ⚠️ Master Gate Regression Detected (Exit Code ${GATE_RC})

The candidate lever \`${CANDIDATE_SLUG}\` failed the 4-Tier Master Quality Gate.

#### Diagnostic Summary:
\`\`\`
${FAILURE_SNIPPET}
\`\`\`

#### Next Steps:
- Re-routed to **Research Agent (Claude)** for Root Cause Analysis.
- Review worktree: \`${WORKTREE_DIR}\`
- Update patch in \`candidates/${CANDIDATE_SLUG}/lever.patch\` and comment when ready.
EOF
)
        gh issue comment "${ISSUE_NUM}" --body "${COMMENT_BODY}" 2>/dev/null || true
        gh issue edit "${ISSUE_NUM}" --add-label "status:needs-review,regression:detected" --remove-label "status:in-progress" 2>/dev/null || true
        echo "✓ GitHub Issue #${ISSUE_NUM} updated with regression report and labeled 'status:needs-review'."
    fi
    
    exit ${GATE_RC}
fi
