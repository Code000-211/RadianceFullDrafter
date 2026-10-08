"""gh_bridge.py — GitHub side of the lever queue (used by lever_queue.py run --github).

State machine on issues of OoguroRyuuya/RadianceMine:

    status:ready-to-test  --pull-->  status:queued  --report-->  status:gate-passed  (+ branch pushed, PR opened)
                                                          \\-->  status:needs-review
    needs-review issues that already have MAX_ATTEMPTS gate results  -->  status:blocked

An issue is testable when its body or a later comment contains a metadata block

    candidate: <slug under candidates/>
    ref: <branch on origin that contains candidates/<slug>/lever.patch>   (optional, default main)
    mode: merge                                                           (optional, see below)

`mode: merge` is for upstream syncs (docs/UPSTREAM.md): the branch itself is the candidate, it
must contain origin/main, and its PR has to be merged with a merge commit so the upstream
history stays an ancestor of main.

The newest block wins, so an agent can point an issue at a corrected branch by commenting.
Gate results are posted by this module only, marked with RESULT_MARKER; nothing here
swallows gh errors.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = "OoguroRyuuya/RadianceMine"
RESULT_MARKER = "<!-- radiance-gate-result -->"
MAX_ATTEMPTS = 3
META_RE = re.compile(r"^candidate:\s*([A-Za-z0-9_.-]+)\s*$(?:\s*^ref:\s*(\S+)\s*$)?(?:\s*^mode:\s*(merge)\s*$)?",
                     re.MULTILINE)

LABELS = {
    "status:ready-to-test": ("0e8a16", "Candidate is ready for the GPU gate"),
    "status:queued": ("fbca04", "Picked up by the lever queue"),
    "status:gate-passed": ("1d76db", "Passed parity and A/B gate; PR opened"),
    "status:needs-review": ("d93f0b", "Gate failed; needs analysis"),
    "status:blocked": ("b60205", "Too many failed attempts; needs a human"),
    "goal:status": ("5319e7", "Stand der Engine gegen das Ziel in baselines/targets.json"),
}
GOAL_LABEL = "goal:status"


def gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def ensure_labels() -> None:
    existing = {l["name"] for l in json.loads(gh("label", "list", "--repo", REPO, "--limit", "200", "--json", "name"))}
    for name, (color, desc) in LABELS.items():
        if name not in existing:
            gh("label", "create", name, "--repo", REPO, "--color", color, "--description", desc)


def issue_texts(number: int) -> tuple[str, list[str]]:
    data = json.loads(gh("issue", "view", str(number), "--repo", REPO, "--json", "body,comments"))
    return data.get("body") or "", [c.get("body") or "" for c in data.get("comments", [])]


def parse_meta(texts: list[str]) -> tuple[str, str, str] | None:
    found = None
    for text in texts:
        for m in META_RE.finditer(text):
            found = (m.group(1), m.group(2) or "main", m.group(3) or "patch")
    return found


def candidate_meta(number: int) -> tuple[str, str, str] | None:
    body, comments = issue_texts(number)
    return parse_meta([body, *comments])


def attempts(number: int) -> int:
    _, comments = issue_texts(number)
    return sum(1 for c in comments if RESULT_MARKER in c)


def set_labels(number: int, add: list[str], remove: list[str]) -> None:
    args = ["issue", "edit", str(number), "--repo", REPO]
    for a in add:
        args += ["--add-label", a]
    for r in remove:
        args += ["--remove-label", r]
    gh(*args)


def update_goal_issue(status_md: str, reached: bool) -> None:
    """One issue carries the target status; its body is replaced after every measurement of main,
    and a comment marks the moment the target is reached or lost again."""
    body = "Automatisch gepflegt von `lever_queue.py` nach jeder Messung von `main` (`scripts/goal.py`).\n\n" + status_md
    issues = json.loads(gh("issue", "list", "--repo", REPO, "--state", "open", "--label", GOAL_LABEL,
                           "--limit", "5", "--json", "number,title"))
    title = "Ziel-Status: erreicht" if reached else "Ziel-Status: nicht erreicht"
    if not issues:
        gh("issue", "create", "--repo", REPO, "--label", GOAL_LABEL, "--title", title, "--body", body)
        return
    n = issues[0]["number"]
    if issues[0]["title"] != title:
        comment(n, f"**{title}**\n\n{status_md}")
    gh("issue", "edit", str(n), "--repo", REPO, "--title", title, "--body", body)


def comment(number: int, body: str) -> None:
    gh("issue", "comment", str(number), "--repo", REPO, "--body", body)


def pull_ready() -> list[dict[str, Any]]:
    """Moves ready-to-test issues to queued and returns the jobs to enqueue."""
    issues = json.loads(gh("issue", "list", "--repo", REPO, "--state", "open", "--label", "status:ready-to-test",
                           "--limit", "50", "--json", "number,title"))
    jobs = []
    for issue in issues:
        n = issue["number"]
        meta = candidate_meta(n)
        if meta is None:
            set_labels(n, ["status:needs-review"], ["status:ready-to-test"])
            comment(n, "Kein `candidate: <slug>`-Block gefunden (optional mit `ref: <branch>`). "
                       "Bitte ergänzen und `status:ready-to-test` erneut setzen.")
            continue
        if attempts(n) >= MAX_ATTEMPTS:
            set_labels(n, ["status:blocked"], ["status:ready-to-test"])
            comment(n, f"{MAX_ATTEMPTS} Gate-Läufe ohne Erfolg. Gesperrt, bis ein Mensch entscheidet "
                       "(Label `status:blocked` entfernen und `status:ready-to-test` setzen).")
            continue
        set_labels(n, ["status:queued"], ["status:ready-to-test", "status:needs-review"])
        jobs.append({"slug": meta[0], "ref": meta[1], "mode": meta[2], "issue": n})
    return jobs


def push_and_open_pr(result: dict[str, Any], repo_root: Path) -> str:
    branch = result["branch"]
    subprocess.run(["git", "push", "origin", f"{result['candidate_sha']}:refs/heads/{branch}"],
                   cwd=str(repo_root), capture_output=True, text=True, check=True)
    body = (repo_root / "reports" / Path(result["report"]).name / "RESULT.md").read_text()
    title = f"lever: {result['slug']} (gate passed)"
    if result.get("mode") == "merge":
        title = f"upstream: {result['slug']} (gate passed)"
        body = ("**Upstream-Sync: mit Merge-Commit mergen, nicht squashen und nicht rebasen**, sonst ist die "
                "Upstream-Historie kein Vorfahre von main mehr und jeder Konflikt kommt beim nächsten Sync "
                "wieder.\n\n" + body)
    if result.get("issue"):
        body += f"\n\nCloses #{result['issue']}\n"
    return gh("pr", "create", "--repo", REPO, "--head", branch, "--base", "main",
              "--title", title, "--body", body).strip()


def report(result: dict[str, Any], repo_root: Path) -> None:
    n = result.get("issue")
    if not n:
        return
    text = Path(result["report"], "RESULT.md").read_text() if Path(result["report"], "RESULT.md").is_file() else result["verdict"]
    if len(text) > 60000:
        text = text[:60000] + "\n\n_(gekürzt, vollständiger Bericht lokal im Report-Ordner)_"
    if result["verdict"] == "PASS":
        pr_url = push_and_open_pr(result, repo_root)
        comment(n, f"{RESULT_MARKER}\n### Gate bestanden\n\nPR: {pr_url}\n\n{text}")
        set_labels(n, ["status:gate-passed"], ["status:queued"])
    else:
        left = MAX_ATTEMPTS - attempts(n) - 1
        comment(n, f"{RESULT_MARKER}\n### Gate nicht bestanden: {result['verdict']}\n\n"
                   f"Verbleibende automatische Versuche: {max(left, 0)}\n\n{text}")
        set_labels(n, ["status:needs-review"], ["status:queued"])
