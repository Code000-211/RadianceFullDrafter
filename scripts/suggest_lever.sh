#!/usr/bin/env bash
# ==============================================================================
# suggest_lever.sh — Submit a User Suggestion or Hypothesis to the Agent Fleet
# ==============================================================================
# Rule 6 of ENGINEERING_CONSTITUTION.md:
# The user can propose ideas, which are automatically registered as hypotheses.
# - Formats the suggestion as a testable proposal.
# - Injects the mandatory fact-checking directive (alphaXiv, GitHub, AMD ISA).
# - Labels the issue 'user:suggestion' and 'research:new-lever'.
# - Claude will autonomously research, verify, and package the candidate lever.
# ==============================================================================
set -euo pipefail

TITLE="${1:-}"
DETAILS="${2:-}"

if [ -z "${TITLE}" ]; then
    echo "❌ ERROR: Suggestion title is required." >&2
    echo "Usage: $0 \"<suggestion_title>\" [\"<details_or_hypothesis>\"]" >&2
    echo "Example: $0 \"Wave32 P2P Store Drain Vectorization\" \"Can we avoid __threadfence_system() using workgroup leader sync?\"" >&2
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "❌ ERROR: GitHub CLI ('gh') is not installed or not in PATH." >&2
    exit 1
fi

BODY=$(cat << EOF
## User Proposal & Hypothesis
${DETAILS:-$TITLE}

---

## Autonomous Agent Instructions (Rule 6: Empirical Skepticism)
- **To Research Agent (Claude)**:
  1. Independently fact-check this proposal against academic literature (alphaXiv/arXiv), open-source kernels (GitHub), and the AMD RDNA4 (gfx1201) ISA manual.
  2. Treat this as an empirical hypothesis: do NOT blindly implement if it violates hardware reality (PCIe 4.0 x16, LDS 64 KiB, Wave32, <= 84 VGPRs).
  3. If viable, package the candidate inside \`candidates/lever<N>_<slug>/\` with \`README.md\` and \`lever.patch\`.
  4. If not viable, reply with a detailed counter-analysis and propose the technically correct alternative.
EOF
)

echo "Submitting suggestion to GitHub as a research task..."
ISSUE_URL=$(gh issue create \
    --title "💡 User Suggestion: ${TITLE}" \
    --label "user:suggestion,research:new-lever" \
    --body "${BODY}")

echo ""
echo "================================================================================"
echo " ✓ Suggestion successfully registered: ${ISSUE_URL}"
echo " The agent workflow will autonomously pick this up, research, and test it."
echo "================================================================================"
