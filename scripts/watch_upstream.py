#!/usr/bin/env python3
"""
watch_upstream.py — Upstream Codeberg watcher, review list only

Polls open pull requests of https://codeberg.org/StillDeadcode/radiance, asks Jev
(TypeSafe System One) one question — could this be useful for our setup? — and
writes the result into candidates/upstream/REVIEW.md for a human to look at.

This script deliberately does NOT:
  * create GitHub issues, branches or pull requests
  * apply, build or execute upstream code
  * set any status label that ORCA would pick up

State lives in telemetry/upstream_review.json. Mark a PR as looked at with
`--done <PR> [<PR> ...]`; it moves back onto the list if the PR changes upstream.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import typesafe_triage
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent))
    import typesafe_triage

BASE_DIR = Path(__file__).resolve().parent.parent
TELEMETRY_DIR = BASE_DIR / "telemetry"
STATE_FILE = TELEMETRY_DIR / "upstream_review.json"
STATE_LOCK_FILE = TELEMETRY_DIR / "upstream_review.lock"
DAEMON_LOCK_FILE = TELEMETRY_DIR / "watcher.lock"
REVIEW_FILE = BASE_DIR / "candidates" / "upstream" / "REVIEW.md"

CODEBERG_BASE = "https://codeberg.org"
REPO_OWNER = "StillDeadcode"
REPO_NAME = "radiance"
API_BASE = f"{CODEBERG_BASE}/api/v1/repos/{REPO_OWNER}/{REPO_NAME}"
USER_AGENT = "RadianceMine-Watcher/2.0"
PAGE_LIMIT = 50

DEFAULT_THRESHOLD = 0.5

OUR_SETUP = (
    "Our setup: exactly 2x AMD Radeon AI PRO R9700 (RDNA4, gfx1201, 32 GB each), "
    "PCIe 4.0, no NVLink/xGMI, tensor parallel world size 2 (never 3 or 4 ranks). "
    "ROCm/HIP only, no CUDA. Model: Qwen FP8 Mixture-of-Experts served by the "
    "Radiance engine. Goal: faster decode/prefill throughput or better correctness "
    "on this exact setup."
)


def http_get_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"HTTP GET failed for {url}: {e}") from e


def fetch_paged(url: str) -> list[Any]:
    sep = "&" if "?" in url else "?"
    items: list[Any] = []
    page = 1
    while True:
        batch = http_get_json(f"{url}{sep}limit={PAGE_LIMIT}&page={page}")
        if not batch:
            return items
        items.extend(batch)
        if len(batch) < PAGE_LIMIT:
            return items
        page += 1


def fetch_open_prs() -> list[dict[str, Any]]:
    return fetch_paged(f"{API_BASE}/pulls?state=open")


def fetch_changed_files(pr_id: int) -> list[dict[str, Any]]:
    files = fetch_paged(f"{API_BASE}/pulls/{pr_id}/files")
    return [
        {
            "name": f.get("filename", "?"),
            "add": f.get("additions", 0),
            "del": f.get("deletions", 0),
        }
        for f in files
    ]


def load_state() -> dict[str, Any]:
    if STATE_FILE.is_file():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"prs": {}, "last_checked": 0}


@contextlib.contextmanager
def state_lock() -> Any:
    """Serialises access to the state file between the daemon and --done/--pr runs."""
    with STATE_LOCK_FILE.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def save_state(state: dict[str, Any]) -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def fingerprint(title: str, body: str, files: list[dict[str, Any]]) -> str:
    raw = json.dumps([title, body, files], sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def classify_usefulness(title: str, body: str, files: list[dict[str, Any]]) -> float:
    """Returns Jev's probability that the PR could be useful for us."""
    file_lines = "\n".join(f"  {f['name']} (+{f['add']}/-{f['del']})" for f in files[:80])
    if len(files) > 80:
        file_lines += f"\n  ... and {len(files) - 80} more files"
    state = (
        f"{OUR_SETUP}\n\n"
        f"Upstream pull request title: {title}\n\n"
        f"Description:\n{body[:3000]}\n\n"
        f"Changed files:\n{file_lines or '  (unknown)'}"
    )
    questions = {
        "useful": {
            "type": "noul",
            "instructions": (
                "Could this pull request plausibly be useful for our setup, so that a human "
                "should look at it? Say no for changes that only matter for 3+ GPUs, CUDA/NVIDIA, "
                "other model families we do not run, or pure cosmetics."
            ),
        },
    }
    answers = typesafe_triage.query_jev(state, questions)
    return float(answers["useful"]["noul"])


def triage(state: dict[str, Any], use_jev: bool, force: bool, only_pr: int | None) -> None:
    open_prs = fetch_open_prs()
    open_ids = {str(pr["number"]) for pr in open_prs}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {len(open_prs)} open upstream PRs", flush=True)

    for key, entry in state["prs"].items():
        entry["open"] = key in open_ids

    for pr in open_prs:
        pr_id = pr["number"]
        if only_pr is not None and pr_id != only_pr:
            continue
        key = str(pr_id)
        entry = state["prs"].get(key, {})
        if not force and entry.get("updated_at") == pr.get("updated_at") and entry.get("useful") is not None:
            continue

        title = pr.get("title", "")
        body = pr.get("body") or ""
        try:
            files = fetch_changed_files(pr_id)
        except RuntimeError as e:
            print(f"  #{pr_id}: file list unavailable ({e})", flush=True)
            files = []

        fp = fingerprint(title, body, files)
        changed = fp != entry.get("fingerprint")
        useful = entry.get("useful") if not (changed or force) else None
        error = None
        if useful is None and use_jev:
            try:
                useful = classify_usefulness(title, body, files)
            except (RuntimeError, KeyError, TypeError, ValueError) as e:
                error = str(e)
                print(f"  #{pr_id}: Jev failed, listed as unclassified ({e})", flush=True)

        done = entry.get("done", False) and not changed
        state["prs"][key] = {
            "pr_id": pr_id,
            "title": title,
            "author": (pr.get("user") or {}).get("username", "?"),
            "url": pr.get("html_url") or f"{CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_id}",
            "updated_at": pr.get("updated_at"),
            "fingerprint": fp,
            "files": files,
            "useful": useful,
            "jev_error": error,
            "done": done,
            "changed_since_done": entry.get("done", False) and changed,
            "open": True,
        }
        label = "unclassified" if useful is None else f"useful={useful:.2f}"
        print(f"  #{pr_id}: {label}  {title[:70]}", flush=True)

    state["last_checked"] = int(time.time())


def mark_done(state: dict[str, Any], pr_ids: list[int]) -> None:
    for pr_id in pr_ids:
        entry = state["prs"].get(str(pr_id))
        if entry is None:
            print(f"PR #{pr_id} is not in the review state", file=sys.stderr)
            continue
        entry["done"] = True
        entry["changed_since_done"] = False
        print(f"PR #{pr_id} marked as reviewed")


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def format_files(files: list[dict[str, Any]]) -> str:
    if not files:
        return "?"
    shown = ", ".join(f"`{f['name']}`" for f in files[:4])
    return shown + (f" +{len(files) - 4} weitere" if len(files) > 4 else "")


def write_review_list(state: dict[str, Any], threshold: float) -> None:
    entries = [e for e in state["prs"].values() if e.get("open")]
    todo = [e for e in entries if not e.get("done") and (e.get("useful") is None or e["useful"] >= threshold)]
    dropped = [e for e in entries if not e.get("done") and e.get("useful") is not None and e["useful"] < threshold]
    done = [e for e in entries if e.get("done")]

    def sort_key(e: dict[str, Any]) -> tuple[float, int]:
        return (-(e["useful"] if e.get("useful") is not None else 2.0), -e["pr_id"])

    def table(rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["_keine_", ""]
        out = ["| PR | Nützlich (Jev) | Titel | Autor | Dateien |", "|---|---|---|---|---|"]
        for e in sorted(rows, key=sort_key):
            score = "unklassifiziert" if e.get("useful") is None else f"{e['useful']:.2f}"
            if e.get("changed_since_done"):
                score += " (geändert seit Review)"
            out.append(
                f"| [#{e['pr_id']}]({e['url']}) | {score} | {md_escape(e['title'][:90])} "
                f"| @{e['author']} | {format_files(e.get('files', []))} |"
            )
        out.append("")
        return out

    last = time.strftime("%Y-%m-%d %H:%M", time.localtime(state.get("last_checked", 0)))
    lines = [
        "# Upstream-PRs zum Ansehen",
        "",
        f"Quelle: [{REPO_OWNER}/{REPO_NAME}]({CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME}/pulls), "
        f"zuletzt geprüft {last}. Jev schätzt nur, ob ein PR für unser Setup nützlich sein "
        f"könnte (Schwelle {threshold:.2f}). Es wird nichts automatisch angewendet oder getestet.",
        "",
        "Als angesehen markieren: `python3 scripts/watch_upstream.py --done <PR> [<PR> ...]`",
        "",
        f"## Ansehen ({len(todo)})",
        "",
        *table(todo),
        f"## Von Jev aussortiert ({len(dropped)})",
        "",
        *table(dropped),
        f"## Bereits angesehen ({len(done)})",
        "",
        *table(done),
    ]
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upstream Codeberg watcher: Jev usefulness triage into a review list")
    parser.add_argument("--daemon", action="store_true", help="Poll continuously")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds (default: 300)")
    parser.add_argument("--force", action="store_true", help="Re-classify all open PRs")
    parser.add_argument("--no-typesafe", action="store_true", help="Skip Jev; everything is listed as unclassified")
    parser.add_argument("--pr", type=int, help="Only (re-)classify this PR")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Usefulness cut-off for the list")
    parser.add_argument("--done", type=int, nargs="+", metavar="PR", help="Mark PRs as reviewed and exit")
    args = parser.parse_args()

    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

    if args.done:
        with state_lock():
            state = load_state()
            mark_done(state, args.done)
            save_state(state)
            write_review_list(state, args.threshold)
        return 0

    if args.daemon:
        daemon_lock = DAEMON_LOCK_FILE.open("w")
        try:
            fcntl.flock(daemon_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"another watcher daemon holds {DAEMON_LOCK_FILE}; exiting", file=sys.stderr)
            return 1
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] watcher daemon started, interval {args.interval}s", flush=True)

    force = args.force or args.pr is not None
    while True:
        try:
            with state_lock():
                state = load_state()
                triage(state, use_jev=not args.no_typesafe, force=force, only_pr=args.pr)
                save_state(state)
                write_review_list(state, args.threshold)
            print(f"Review list: {REVIEW_FILE.relative_to(BASE_DIR)}", flush=True)
        except RuntimeError as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] polling failed: {e}", flush=True)
            if not args.daemon:
                return 1
        if not args.daemon:
            return 0
        force = False
        time.sleep(args.interval)

if __name__ == "__main__":
    sys.exit(main())
