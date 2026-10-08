#!/usr/bin/env python3
"""upstream_sync.py — prepares, never performs, a merge of Codeberg main into our main.

    upstream_sync.py [--dry-run]

Deterministic and without an LLM: fetch Codeberg main, and if it has commits our main does not
contain and no sync issue is open, mirror it to origin as branch `upstream/main` and open one
issue labelled `upstream:sync` with what an agent needs to decide: the upstream commits, the files
a merge would conflict on (git merge-tree, nothing is checked out) and the files both sides
changed since the fork. The planner triages the commits, a code agent merges, review and the GPU
gate decide; nothing reaches main without that and Leon's merge. See docs/UPSTREAM.md.

--dry-run prints the issue body instead of pushing and creating the issue.
Exit 0 = done or nothing to do, 2 = a step failed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = "OoguroRyuuya/RadianceMine"
REPO_ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_URL = "https://codeberg.org/StillDeadcode/radiance.git"
UPSTREAM_REF = "refs/remotes/upstream/main"
MIRROR_BRANCH = "upstream/main"
LABEL = "upstream:sync"
MAX_COMMITS_LISTED = 150
# Where our own work lives; a conflict or overlap here is where upstream could break our pipeline.
OUR_AREAS = {
    "libr4d/": "Kernel (libr4d)",
    "arch/": "Architektur-Plugins",
    "core/": "Engine-Kern",
    "libavx/": "CPU-Kernel",
    "abi/": "ABI",
}


def git(*args: str, ok: tuple[int, ...] = (0,)) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    if proc.returncode not in ok:
        raise RuntimeError(f"git {' '.join(args[:2])} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.returncode, proc.stdout.strip()


def gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def area(path: str) -> str:
    return next((name for prefix, name in OUR_AREAS.items() if path.startswith(prefix)), "Sonstiges")


def grouped(paths: list[str]) -> str:
    if not paths:
        return "_keine_"
    groups: dict[str, list[str]] = {}
    for p in paths:
        groups.setdefault(area(p), []).append(p)
    out = []
    for name in [*OUR_AREAS.values(), "Sonstiges"]:
        if name in groups:
            out.append(f"- **{name}** ({len(groups[name])}): " + ", ".join(f"`{p}`" for p in groups[name]))
    return "\n".join(out)


def analyse(ours: str = "origin/main", theirs: str = UPSTREAM_REF) -> dict:
    _, upstream_sha = git("rev-parse", theirs)
    _, base = git("merge-base", ours, theirs)
    _, log = git("log", "--reverse", "--format=%h%x09%an%x09%s", f"{ours}..{theirs}")
    commits = [line.split("\t", 2) for line in log.splitlines() if line]
    rc, tree = git("merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs, ok=(0, 1))
    conflicts = tree.splitlines()[1:] if rc == 1 else []
    _, theirs_files = git("diff", "--name-only", base, theirs)
    _, ours_files = git("diff", "--name-only", base, ours)
    overlap = sorted(set(theirs_files.splitlines()) & set(ours_files.splitlines()) - set(conflicts))
    _, excluded = git("log", "--format=%h %s%n%b", "--grep=^Upstream-Excluded:", ours)
    excluded_lines = [l.strip() for l in excluded.splitlines() if l.strip().startswith("Upstream-Excluded:")]
    stat = {}
    for line in git("log", "--format=%h", "--shortstat", f"{ours}..{theirs}")[1].splitlines():
        if line and not line.startswith(" "):
            current = line
        elif line:
            stat[current] = line.strip()
    return {"upstream_sha": upstream_sha, "base": base, "commits": commits, "conflicts": conflicts,
            "overlap": overlap, "stat": stat, "excluded": excluded_lines}


def issue_body(a: dict) -> str:
    short = a["upstream_sha"][:10]
    rows = [f"| `{h}` | {author} | {subject.replace('|', '/')} | {a['stat'].get(h, '')} |"
            for h, author, subject in a["commits"][:MAX_COMMITS_LISTED]]
    more = len(a["commits"]) - MAX_COMMITS_LISTED
    lines = [
        f"Codeberg `main` hat {len(a['commits'])} Commits, die unser `main` nicht enthält.",
        "",
        f"upstream: {a['upstream_sha']}",
        f"Gemeinsame Basis: `{a['base'][:10]}` · Spiegel auf GitHub: Branch `{MIRROR_BRANCH}`",
        "",
        "Ablauf (docs/UPSTREAM.md): Der Planer sortiert die Commits (übernehmen, angepasst übernehmen,",
        "ausschließen) und schreibt die Konfliktregeln; der Code-Agent merged genau diesen Stand",
        f"(`git fetch origin {MIRROR_BRANCH} && git merge {short}`), Review und GPU-Gate entscheiden,",
        "Leon merged den PR mit Merge-Commit.",
        "",
        f"## Konflikte bei einem Merge ({len(a['conflicts'])} Dateien)",
        "",
        grouped(a["conflicts"]),
        "",
        f"## Von beiden Seiten geändert, ohne Konflikt ({len(a['overlap'])} Dateien)",
        "",
        "Kein Textkonflikt heißt nicht, dass es zusammenpasst: hier besonders auf Semantik achten.",
        "",
        grouped(a["overlap"]),
        "",
        f"## Früher ausgeschlossen ({len(a['excluded'])})",
        "",
        "Neu bewerten: Ist der Grund noch gültig, oder hat Upstream das Problem inzwischen behoben?",
        "",
        "\n".join(f"- {line}" for line in a["excluded"]) or "_keine_",
        "",
        "## Upstream-Commits",
        "",
        "| Commit | Autor | Betreff | Umfang |",
        "|---|---|---|---|",
        *rows,
    ]
    if more > 0:
        lines.append(f"\n_… und {more} weitere: `git log origin/main..{short}`_")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        git("fetch", "--quiet", "origin", "main")
        git("fetch", "--quiet", UPSTREAM_URL, f"+main:{UPSTREAM_REF}")
        _, count = git("rev-list", "--count", f"origin/main..{UPSTREAM_REF}")
        if int(count) == 0:
            print("upstream main ist vollständig in origin/main")
            return 0
        if not args.dry_run:
            open_issues = json.loads(gh("issue", "list", "--repo", REPO, "--state", "open", "--label", LABEL,
                                        "--json", "number"))
            if open_issues:
                print(f"Sync-Issue #{open_issues[0]['number']} ist noch offen; neue Upstream-Commits kommen in den nächsten Sync")
                return 0
        a = analyse()
        body = issue_body(a)
        if args.dry_run:
            print(body)
            return 0
        git("push", "--quiet", "origin", f"+{UPSTREAM_REF}:refs/heads/{MIRROR_BRANCH}")
        title = f"Upstream-Sync: {len(a['commits'])} Commits bis {a['upstream_sha'][:10]} ({len(a['conflicts'])} Konflikte)"
        url = gh("issue", "create", "--repo", REPO, "--label", LABEL, "--title", title, "--body", body).strip()
        print(url)
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"upstream_sync fehlgeschlagen: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
