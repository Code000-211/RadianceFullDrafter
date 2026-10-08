#!/usr/bin/env bash
# ==============================================================================
# orca_agent_runner.sh — Autonomous Orchestration Runner for AGY & GitHub Issues
# ==============================================================================
# Scans GitHub repository for candidate levers ready for testing.
# - Fetches issues labeled 'research:new-lever' or 'status:ready-to-test'
# - Dispatches them to test_candidate_lever.sh in isolated worktrees
# - Enforces the 4-Tier Master Gate on dual AMD Radeon AI PRO R9700 GPUs
# - Handles automatic PR generation on victory, or review loop on regression
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

POLL_INTERVAL="${POLL_INTERVAL:-30}"
ONE_SHOT="${ONE_SHOT:-0}"

echo "================================================================================"
echo " 🤖 RadianceMine Autonomous Agent Runner"
echo " Workspace:     ${REPO_ROOT}"
echo " Poll Interval: ${POLL_INTERVAL}s"
echo " Mode:          $([ "${ONE_SHOT}" = "1" ] && echo "One-Shot" || echo "Continuous Daemon")"
echo "================================================================================"

if ! command -v gh >/dev/null 2>&1; then
    echo "❌ ERROR: GitHub CLI ('gh') is not installed or not in PATH." >&2
    exit 1
fi

process_issues() {
    # Query open issues labeled 'research:new-lever' or 'status:ready-to-test'
    ISSUES_JSON=$(gh issue list --state open --limit 20 \
        --json number,title,labels,body 2>/dev/null || echo "[]")
    
    # Process issues matching criteria
    python3 -c '
import json, sys, subprocess, os, re

repo_root = sys.argv[1]
issues_data = sys.stdin.read()
if not issues_data.strip():
    sys.exit(0)

try:
    issues = json.loads(issues_data)
except Exception:
    sys.exit(0)

for issue in issues:
    labels = [l.get("name", "") for l in issue.get("labels", [])]
    
    # We want issues that are ready to test and not currently in-progress
    if ("research:new-lever" in labels or "status:ready-to-test" in labels) and "status:in-progress" not in labels and "status:needs-review" not in labels:
        num = issue["number"]
        title = issue["title"]
        body = issue.get("body", "")
        
        # Look for candidate directory pattern: lever<N>_<name>
        match = re.search(r"lever\d+_[a-zA-Z0-9_]+", title + " " + body)
        if match:
            candidate_slug = match.group(0)
            candidate_dir = os.path.join(repo_root, "candidates", candidate_slug)
            if os.path.isdir(candidate_dir):
                print(f"[FOUND] Issue #{num}: {title} -> Candidate: {candidate_slug}")
                runner_cmd = [
                    os.path.join(repo_root, "scripts", "test_candidate_lever.sh"),
                    candidate_slug,
                    "--issue", str(num)
                ]
                sys.stdout.flush()
                res = subprocess.run(runner_cmd)
                print(f"[RESULT] Finished Issue #{num} with return code {res.returncode}")
                sys.stdout.flush()
            else:
                print(f"[SKIP] Candidate dir {candidate_dir} does not exist.")
        else:
            print(f"[SKIP] No lever slug found in Issue #{num}: {title}")
' "${REPO_ROOT}" <<< "${ISSUES_JSON}"
}

if [ "${ONE_SHOT}" = "1" ]; then
    process_issues
    exit 0
fi

while true; do
    process_issues
    sleep "${POLL_INTERVAL}"
done
