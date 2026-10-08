#!/usr/bin/env python3
"""orca_precheck.py — bounded prechecks for the Orca automations of RadianceMine.

Orca runs an automation's agent only when its precheck exits 0, so each check answers
"is there work for this agent right now?" without starting an LLM session.

    orca_precheck.py needs-review   open issue with status:needs-review (not blocked)
    orca_precheck.py new-lever      open issue with research:new-lever and no candidate yet
    orca_precheck.py upstream       REVIEW.md lists a PR to look at that has no assessment

Exit 0 = work found (the first item is printed), 1 = nothing to do, 2 = check failed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = "OoguroRyuuya/RadianceMine"
REPO_ROOT = Path("/home/orca/RadianceMine")


def issues(label: str) -> list[dict]:
    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--state", "open", "--label", label, "--limit", "50",
         "--json", "number,title,labels"],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return json.loads(proc.stdout)


def check_needs_review() -> str | None:
    for issue in issues("status:needs-review"):
        names = {l["name"] for l in issue["labels"]}
        if "status:blocked" not in names and "status:queued" not in names:
            return f"#{issue['number']} {issue['title']}"
    return None


def check_new_lever() -> str | None:
    for issue in issues("research:new-lever"):
        names = {l["name"] for l in issue["labels"]}
        if not names & {"status:ready-to-test", "status:queued", "status:gate-passed", "status:blocked", "status:needs-review"}:
            return f"#{issue['number']} {issue['title']}"
    return None


def check_upstream() -> str | None:
    state = json.loads((REPO_ROOT / "telemetry" / "upstream_review.json").read_text())
    for entry in sorted(state["prs"].values(), key=lambda e: -(e.get("useful") or 0)):
        if entry.get("open") and not entry.get("done") and not entry.get("assessment") and (entry.get("useful") or 1.0) >= 0.5:
            return f"upstream PR #{entry['pr_id']} {entry['title']}"
    return None


def main() -> int:
    checks = {"needs-review": check_needs_review, "new-lever": check_new_lever, "upstream": check_upstream}
    if len(sys.argv) != 2 or sys.argv[1] not in checks:
        print(f"usage: {sys.argv[0]} {{{'|'.join(checks)}}}", file=sys.stderr)
        return 2
    try:
        found = checks[sys.argv[1]]()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"precheck failed: {e}", file=sys.stderr)
        return 2
    if found:
        print(found)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
