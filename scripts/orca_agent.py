#!/usr/bin/env python3
"""orca_agent.py — deterministic dispatcher for the RadianceMine agent roles.

Orca automations only take a prompt and a provider; they cannot pick a model per run. So a
systemd timer runs `tick`, which decides everything without an LLM, and Orca only hosts the
worktree and the terminal the agent runs in (visible in the Orca sidebar and dashboard).

    orca_agent.py tick                 timer entry: clean up old agent worktrees, then for every role
                                       with work and a free slot create a worktree and start `run` in an
                                       Orca terminal (launcher "orca") or as a detached process
    orca_agent.py run <role> [--issue N]
                                       inside an agent worktree: take a slot and the issue, build the
                                       role's worktree setup, start ONE fresh agent session with the
                                       model for its tier, verify the label handoff afterwards
    orca_agent.py ask <frage> [--wait S]
                                       for code/review agents: blocking question to the planner; a fresh
                                       planner session answers with only the plan and the question as
                                       context; question and answer go to the issue
    orca_agent.py answer <id> [--wait S]  keep waiting for an answer that was still open
    orca_agent.py check <role>         would `tick` start this role now? (diagnostics; exit 0/1/2)
    orca_agent.py labels               create the workflow labels on GitHub (gate labels via gh_bridge)
    orca_agent.py status               slots, backends, last runs, open questions

Roles: plan, code, review, research, audit, upstream; prompts in docs/agents/<role>.md.
Models, tiers, limits, launcher: scripts/agents/models.json. Workflow: docs/ORCA_AGENT_WORKFLOW.md.

Every run is a new CLI process without resume flags, i.e. a new session. Agents do not read the
whole issue: `run` puts a brief with only what the role needs (idea, latest plan, latest review
or gate report, answers to questions) into the prompt.

Locks are flock()ed files in the state directory, so a crashed agent frees its slot and its
issue. Round counters come from GitHub (gate results, written by gh_bridge only) and from this
script's own run ledger (review rounds, plan revisions, runs without handoff); they never depend
on an agent writing a marker.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

REPO = "OoguroRyuuya/RadianceMine"
PRIMARY = Path(os.environ.get("RADIANCE_PRIMARY", Path(__file__).resolve().parent.parent))
CONFIG = PRIMARY / "scripts" / "agents" / "models.json"
PROMPTS = PRIMARY / "docs" / "agents"
STATE = Path(os.environ.get("RADIANCE_AGENT_STATE", Path.home() / ".local" / "state" / "radiance-agents"))

RESULT_MARKER = "<!-- radiance-gate-result -->"
PLAN_MARKER = "<!-- radiance-plan -->"
REVIEW_MARKER = "<!-- radiance-review -->"
HANDOFF_MARKER = "<!-- radiance-handoff -->"
QA_MARKER = "<!-- radiance-qa -->"
META_RE = re.compile(r"^candidate:\s*[A-Za-z0-9_.-]+\s*$(?:\s*^ref:\s*\S+\s*$)?(?:\s*^mode:\s*merge\s*$)?", re.MULTILINE)

ROLES = ("plan", "code", "review", "research", "audit", "upstream")
ISSUE_ROLES = ("plan", "code", "review")
BUILD_ROLES = ("code", "review", "audit")
TICK_ORDER = ("review", "code", "plan", "upstream", "audit", "research")  # finish work before starting new
ASK_ROLES = ("code", "review")
TIERS = ("light", "medium", "heavy", "fallback")
PLANNER_TIERS = TIERS[:3]
TIER_DE = {"light": "leicht", "medium": "mittel", "heavy": "schwer", "fallback": "Fallback"}

WORKFLOW_LABELS = {
    "research:new-lever": ("5319e7", "Idee für einen Hebel; wartet auf den Planer"),
    "upstream:sync": ("0e8a16", "Codeberg-main zusammenführen; Planer, Code, Review, Gate wie ein Hebel"),
    "plan:ready": ("0052cc", "Implementierungsplan steht; wartet auf den Code-Agent"),
    "plan:needs-revision": ("c5def5", "Plan passt nicht zum Code oder Gate; zurück zum Planer"),
    "plan:rejected": ("cccccc", "Planer hat die Idee begründet verworfen"),
    "needs-code-review": ("fbca04", "Branch steht; wartet auf den Review-Agent"),
    "changes-requested": ("d93f0b", "Review verlangt Änderungen; zurück zum Code-Agent"),
    "tier:light": ("c2e0c6", "Planer: einfache, lokale Änderung"),
    "tier:medium": ("fef2c0", "Planer: mehrere Dateien oder Kernel-Anpassung"),
    "tier:heavy": ("f9d0c4", "Planer: neuer Kernel, Numerik, TP-Kommunikation"),
    "source:research": ("bfdadc", "Idee aus externer Recherche"),
    "source:audit": ("bfdadc", "Idee aus dem Code-Audit"),
    "audit:coverage": ("1d76db", "Tracking-Issue mit der Coverage-Karte des Audits"),
    "audit:bug": ("b60205", "Audit-Fund mit Paritäts- oder Korrektheitsrisiko; für Leon"),
}

STATUS_LABELS = {"status:ready-to-test", "status:queued", "status:gate-passed", "status:needs-review", "status:blocked"}
DOWNSTREAM = {"needs-code-review", "changes-requested", "plan:needs-revision"} | STATUS_LABELS
DEAD = {"status:blocked", "status:gate-passed", "plan:rejected"}

KIND_DE = {
    "plan/new": "neue Idee oder Upstream-Sync planen",
    "plan/revise": "Plan überarbeiten",
    "code/changes": "Review-Änderungen umsetzen",
    "code/gate-fix": "Gate-Fehlschlag beheben",
    "code/implement": "Plan implementieren",
    "review/review": "Branch reviewen",
}


# ---------------------------------------------------------------- configuration, GitHub, git

def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def open_issues() -> list[dict[str, Any]]:
    data = json.loads(gh("issue", "list", "--repo", REPO, "--state", "open", "--limit", "200",
                         "--json", "number,title,labels"))
    return [{"number": i["number"], "title": i["title"], "labels": {l["name"] for l in i["labels"]}} for i in data]


def issue_view(number: int) -> dict[str, Any]:
    data = json.loads(gh("issue", "view", str(number), "--repo", REPO, "--json",
                         "number,title,state,body,labels,comments"))
    return {"number": data["number"], "title": data["title"], "state": data["state"], "body": data.get("body") or "",
            "labels": {l["name"] for l in data["labels"]},
            "comments": [c.get("body") or "" for c in data.get("comments", [])]}


def gh_comments(number: int) -> list[str]:
    return issue_view(number)["comments"]


def comment(number: int, body: str) -> None:
    gh("issue", "comment", str(number), "--repo", REPO, "--body", body)


def block_issue(number: int, reason: str) -> None:
    comment(number, f"Automatisch gesperrt: {reason}\n\n— orca_agent.py")
    gh("issue", "edit", str(number), "--repo", REPO, "--add-label", "status:blocked")


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


# ---------------------------------------------------------------- selection (pure)

def kind_of(role: str, labels: set[str], has_gate_result: Callable[[], bool]) -> str | None:
    """Which job this issue is for the role, or None. Order of the checks is the priority."""
    if labels & DEAD:
        return None
    if role == "plan":
        if "plan:needs-revision" in labels:
            return "revise"
        if labels & {"research:new-lever", "upstream:sync"} and not labels & ({"plan:ready"} | DOWNSTREAM):
            return "new"
    elif role == "code":
        if "changes-requested" in labels:
            return "changes"
        if "status:needs-review" in labels and "status:queued" not in labels and has_gate_result():
            return "gate-fix"
        if "plan:ready" in labels and not labels & DOWNSTREAM:
            return "implement"
    elif role == "review":
        if "needs-code-review" in labels and not labels & ({"changes-requested"} | STATUS_LABELS):
            return "review"
    return None


KIND_PRIORITY = {"revise": 0, "new": 1, "changes": 0, "gate-fix": 1, "implement": 2, "review": 0}


def work_items(role: str, issues: list[dict[str, Any]], comments_of: Callable[[int], list[str]]) -> list[tuple[dict, str]]:
    found = []
    for issue in issues:
        k = kind_of(role, issue["labels"],
                    lambda n=issue["number"]: any(RESULT_MARKER in c for c in comments_of(n)))
        if k:
            found.append((issue, k))
    return sorted(found, key=lambda t: (KIND_PRIORITY[t[1]], t[0]["number"]))


def gate_failures(comments: list[str]) -> int:
    return sum(1 for c in comments if RESULT_MARKER in c and "### Gate bestanden" not in c)


def pick_tier(tier_backends: dict[str, str], labels: set[str], steps: int = 0,
              max_tier: str = "fallback") -> tuple[str, list[str]]:
    """Planner's tier (default medium), then one step up per failed round and per role offset.
    A step always changes the backend: tiers that map to the same backend as the tier below are
    skipped, so escalating from Gemini means GLM, and review never runs on the coder's model
    unless the role's max_tier forces it. Returns the tier and the remaining ladder above it."""
    set_tiers = [PLANNER_TIERS.index(l[5:]) for l in labels if l.startswith("tier:") and l[5:] in PLANNER_TIERS]
    base = TIERS[max(set_tiers) if set_tiers else 1]
    ladder: list[str] = []
    for t in TIERS[TIERS.index(base):TIERS.index(max_tier) + 1]:
        if not ladder or tier_backends[t] != tier_backends[ladder[-1]]:
            ladder.append(t)
    i = min(steps, len(ladder) - 1)
    return ladder[i], ladder[i + 1:]


def outcome(role: str, before: set[str], after: set[str], state: str) -> str | None:
    """What the agent handed over; None means no valid handoff."""
    if "status:blocked" in after - before:
        return "blocked"
    if role == "plan":
        if state == "CLOSED" or "plan:rejected" in after:
            return "rejected"
        if "plan:ready" in after and "plan:needs-revision" not in after and \
                not after.isdisjoint(f"tier:{t}" for t in PLANNER_TIERS):
            return "planned"
    elif role == "code":
        if "plan:needs-revision" in after - before:
            return "replan"
        if "needs-code-review" in after and not after & ({"changes-requested"} | STATUS_LABELS):
            return "submitted"
    elif role == "review":
        if "plan:needs-revision" in after - before:
            return "replan"
        if "changes-requested" in after:
            return "changes-requested"
        if "status:ready-to-test" in after and "needs-code-review" not in after:
            return "approved"
    return None


# ---------------------------------------------------------------- brief: only what the role needs

def clip(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + "\n\n_(gekürzt; vollständig im Issue)_"


def latest(comments: list[str], marker: str) -> str | None:
    return next((c for c in reversed(comments) if marker in c), None)


def since_latest_plan(comments: list[str]) -> list[str]:
    idx = max((i for i, c in enumerate(comments) if PLAN_MARKER in c), default=-1)
    return comments[idx + 1:]


def build_brief(role: str, kind: str, view: dict[str, Any]) -> str:
    comments = view["comments"]
    recent = since_latest_plan(comments)
    plan = latest(comments, PLAN_MARKER)
    sections: list[tuple[str, str | None]] = [("Idee (Issue-Text)", clip(view["body"], 4000))]
    if role == "plan":
        if kind == "revise":
            sections += [("Bisheriger Plan", plan),
                         ("Seit dem Plan (Grund der Überarbeitung, Review, Gate)",
                          clip("\n\n---\n\n".join(recent), 12000) if recent else None)]
    else:
        sections.append(("Plan", plan))
        if role == "code" and kind == "changes":
            sections.append(("Review-Befunde", latest(recent, REVIEW_MARKER)))
        if role == "code" and kind == "gate-fix":
            sections.append(("Gate-Bericht", clip(latest(comments, RESULT_MARKER), 8000)))
        if kind in ("changes", "gate-fix", "review"):
            sections.append(("Letzte Übergabe des Code-Agents", latest(recent, HANDOFF_MARKER)))
        if role == "review":
            sections.append(("Vorige Review-Runde", latest(recent, REVIEW_MARKER)))
        qa = [c for c in recent if QA_MARKER in c]
        sections.append(("Rückfragen und Antworten", "\n\n---\n\n".join(qa) if qa else None))
    meta = [m.group(0) for c in comments for m in META_RE.finditer(c)]
    if meta and role != "plan":
        sections.append(("Aktueller Kandidat (neuester Block)", f"```\n{meta[-1]}\n```"))
    out = ["# Übergabe", "",
           "Das ist alles, was du aus dem Issue brauchst. Lies das ganze Issue nur, wenn hier etwas fehlt.", ""]
    for title, text in sections:
        if text:
            out += [f"## {title}", "", text.strip(), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- local state: locks, ledger, reservations

def state_dir() -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE


def try_lock(path: Path) -> int | None:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def is_locked(path: Path) -> bool:
    fd = try_lock(path)
    if fd is None:
        return True
    os.close(fd)
    return False


def acquire_slot(max_parallel: int) -> int | None:
    for i in range(max_parallel):
        fd = try_lock(state_dir() / f"slot-{i}.lock")
        if fd is not None:
            return fd
    return None


def free_slots(max_parallel: int) -> int:
    return sum(1 for i in range(max_parallel) if not is_locked(state_dir() / f"slot-{i}.lock"))


def work_lock_path(role: str, issue: int | None) -> Path:
    """Issue roles lock the issue; research, audit and upstream run one at a time."""
    return state_dir() / (f"issue-{issue}.lock" if issue else f"role-{role}.lock")


RESERVATION_TTL = 20 * 60  # a started run takes its lock long before this


def reservation_path(role: str, issue: int | None) -> Path:
    return state_dir() / (f"reserved-issue-{issue}" if issue else f"reserved-role-{role}")


def reserved(role: str, issue: int | None) -> bool:
    p = reservation_path(role, issue)
    return p.is_file() and time.time() - p.stat().st_mtime < RESERVATION_TTL


def active_reservations() -> int:
    return sum(1 for p in state_dir().glob("reserved-*") if time.time() - p.stat().st_mtime < RESERVATION_TTL)


def ledger(number: int | None = None) -> list[dict[str, Any]]:
    path = state_dir() / "runs.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if number is None or r.get("issue") == number]


def record(row: dict[str, Any]) -> None:
    with open(state_dir() / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def count(rows: list[dict[str, Any]], role: str, result: str | None) -> int:
    return sum(1 for r in rows if r.get("role") == role and r.get("outcome") == result and not r.get("rate_limited"))


def cooling_until(backend: str) -> float:
    path = state_dir() / f"cooldown-{backend}"
    return float(path.read_text()) if path.is_file() else 0.0


def backend_problem(cfg: dict[str, Any], name: str) -> str | None:
    b = cfg["backends"].get(name)
    if b is None:
        return f"Backend {name} fehlt in models.json"
    if not b.get("model"):
        return f"Backend {name}: kein Modellname in models.json"
    if shutil.which(b["cli"]) is None:
        return f"Backend {name}: CLI {b['cli']} nicht im PATH"
    if b.get("key_file") and not Path(b["key_file"]).expanduser().is_file():
        return f"Backend {name}: Schlüsseldatei {b['key_file']} fehlt"
    if cooling_until(name) > time.time():
        return f"Backend {name}: Nutzungslimit, Pause bis {time.strftime('%H:%M', time.localtime(cooling_until(name)))}"
    return None


# ---------------------------------------------------------------- per-role decisions

def backend_options(cfg: dict[str, Any], role: str, labels: set[str], failures: int) -> list[tuple[str, str | None]]:
    """(backend, tier) in order of preference. A tiered role whose backend is unavailable moves up,
    but never into the fallback tier just because a cheaper backend is missing or rate limited."""
    rc = cfg["roles"][role]
    if not rc.get("tiered"):
        return [(rc["backend"], None)]
    tier, higher = pick_tier(cfg["tiers"], labels, failures + rc.get("tier_offset", 0), rc.get("max_tier", "fallback"))
    options = [(cfg["tiers"][tier], tier)]
    for t in higher:
        if t != "fallback" or cfg["limits"].get("availability_fallback", False):
            options.append((cfg["tiers"][t], t))
    return options


def code_failures(comments: list[str], rows: list[dict[str, Any]]) -> int:
    return gate_failures(comments) + count(rows, "review", "changes-requested") + count(rows, "code", None)


def choose_backend(cfg: dict[str, Any], options: list[tuple[str, str | None]], log: Callable[[str], None]) -> tuple[str, str | None] | None:
    problems = []
    for backend, tier in options:
        problem = backend_problem(cfg, backend)
        if problem is None:
            return backend, tier
        problems.append(problem)
    log("; ".join(problems))
    return None


def find_work(cfg: dict[str, Any], role: str, verbose: bool = True, only_issue: int | None = None) -> dict[str, Any] | None:
    lim = cfg["limits"]

    def log(msg: str) -> None:
        if verbose:
            print(f"[{role}] {msg}", file=sys.stderr)

    if role in ("research", "audit", "upstream"):
        if is_locked(work_lock_path(role, None)) or (only_issue is None and reserved(role, None)):
            return None
        title = f"{role}-Lauf"
        if role in ("research", "audit"):
            ideas = [i for i in open_issues() if "research:new-lever" in i["labels"] and not i["labels"] & DEAD]
            if len(ideas) >= lim["max_open_ideas"]:
                log(f"{len(ideas)} offene Ideen >= {lim['max_open_ideas']}: erst abarbeiten")
                return None
            stamp = state_dir() / f"last-{role}"
            if stamp.is_file() and time.time() - stamp.stat().st_mtime < lim["interval_hours"][role] * 3600:
                return None
        else:
            state = json.loads((PRIMARY / "telemetry" / "upstream_review.json").read_text())
            todo = [e for e in state["prs"].values() if e.get("open") and not e.get("done")
                    and not e.get("assessment") and (e.get("useful") or 1.0) >= 0.5]
            if not todo:
                return None
            title = f"Upstream-PRs ohne Bewertung: {len(todo)}"
        chosen = choose_backend(cfg, backend_options(cfg, role, set(), 0), log)
        if chosen is None:
            return None
        return {"role": role, "issue": None, "title": title, "kind": role, "backend": chosen[0], "tier": None}

    cache: dict[int, list[str]] = {}

    def comments_of(n: int) -> list[str]:
        if n not in cache:
            cache[n] = gh_comments(n)
        return cache[n]

    issues = open_issues()
    if only_issue is not None:
        issues = [i for i in issues if i["number"] == only_issue]
    for issue, kind in work_items(role, issues, comments_of):
        n = issue["number"]
        if is_locked(work_lock_path(role, n)) or (only_issue is None and reserved(role, n)):
            continue
        rows = ledger(n)
        failures = code_failures(comments_of(n), rows) if role in ("code", "review") else 0
        chosen = choose_backend(cfg, backend_options(cfg, role, issue["labels"], failures), lambda m: log(f"#{n}: {m}"))
        if chosen is None:
            continue
        return {"role": role, "issue": n, "title": issue["title"], "kind": kind, "backend": chosen[0],
                "tier": chosen[1], "failures": failures, "labels": sorted(issue["labels"])}
    return None


def limit_violation(cfg: dict[str, Any], item: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    lim = cfg["limits"]
    if count(rows, item["role"], None) >= lim["max_no_handoff"]:
        return f"{lim['max_no_handoff']} Läufe der Rolle {item['role']} ohne gültige Übergabe"
    if item["kind"] == "changes" and count(rows, "review", "changes-requested") > lim["max_review_rounds"]:
        return f"mehr als {lim['max_review_rounds']} Review-Runden mit Änderungswünschen"
    if item["kind"] == "revise" and count(rows, "plan", "planned") > lim["max_plan_revisions"]:
        return f"mehr als {lim['max_plan_revisions']} Plan-Überarbeitungen"
    return None


# ---------------------------------------------------------------- agent launch

def build_prompt(cfg: dict[str, Any], item: dict[str, Any], rows: list[dict[str, Any]], worktree: Path, branch: str,
                 brief: str = "") -> str:
    b = cfg["backends"][item["backend"]]
    lim = cfg["limits"]
    lines = ["# Auftrag", "", f"Rolle: **{item['role']}**"]
    if item["issue"]:
        lines.append(f"Issue: #{item['issue']} „{item['title']}“ ({KIND_DE[item['role'] + '/' + item['kind']]})")
    else:
        lines.append(f"Aufgabe: {item['title']}")
    tier_note = ""
    if item.get("tier"):
        tier_note = f", Stufe {TIER_DE[item['tier']]} (nach {item['failures']} Fehlschlägen dieses Issues)"
    lines += [f"Modell: {item['backend']} ({b['model']}){tier_note}",
              f"Worktree: `{worktree}` · Branch: `{branch}` (abgeleitet von origin/main)",
              f"Repo: {REPO} · Primary-Checkout (nur lesen): `{PRIMARY}`"]
    if item["issue"]:
        lines.append(f"Zähler: Review-Runden mit Änderungswünschen {count(rows, 'review', 'changes-requested')}/"
                     f"{lim['max_review_rounds']}, Plan-Fassungen {count(rows, 'plan', 'planned')}/"
                     f"{1 + lim['max_plan_revisions']}, Gate-Fehlschläge siehe Übergabe (max. 3)")
    if item["role"] in ASK_ROLES:
        lines.append(f"Rückfragen an den Planer: `python3 {PRIMARY}/scripts/orca_agent.py ask \"<frage>\"` "
                     f"(höchstens {lim['max_questions']} pro Lauf, siehe Rollen-Prompt)")
    lines += [f"Jeden Kommentar beenden mit: `— Agent {item['role']} · {b['model']}`", "",
              "Lies zuerst `AGENTS.md` und `docs/ORCA_AGENT_WORKFLOW.md`.", "", "---", ""]
    text = "\n".join(lines) + (PROMPTS / f"{item['role']}.md").read_text(encoding="utf-8")
    return text + ("\n\n---\n\n" + brief if brief else "")


def agent_command(b: dict[str, Any], prompt: str, read_only: bool = False) -> list[str]:
    if b["cli"] == "claude":
        cmd = ["claude", "-p", prompt, "--model", b["model"], "--dangerously-skip-permissions",
               "--output-format", "stream-json", "--verbose"]
        return cmd + (["--disallowedTools", "Edit", "Write", "NotebookEdit"] if read_only else [])
    if b["cli"] == "agy":
        return ["agy", "-p", prompt, "--model", b["model"], "--dangerously-skip-permissions"]
    raise ValueError(f"unbekannte CLI {b['cli']}")


def agent_env(b: dict[str, Any], extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    # An inherited endpoint or token must never reroute an "Opus" run to another provider.
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
              "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        env.pop(k, None)
    if b["cli"] == "claude":
        # `orca_agent.py ask` blocks up to a few minutes; the default shell timeout is 2 min.
        env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "300000")
        env.setdefault("BASH_MAX_TIMEOUT_MS", "600000")
    env.update(b.get("env", {}))
    if b.get("key_file"):
        env[b["key_env"]] = Path(b["key_file"]).expanduser().read_text(encoding="utf-8").strip()
    env.update(extra or {})
    return env


RATE_LIMIT_RE = re.compile(r"usage limit|rate.?limit|quota exceeded|resource.?exhausted|\b429\b", re.I)


def is_limit_message(cli: str, line: str) -> bool:
    """claude: only the final result event or plain stderr text, never file contents the agent read."""
    if not RATE_LIMIT_RE.search(line):
        return False
    if cli != "claude":
        return True
    try:
        return json.loads(line).get("type") == "result"
    except (json.JSONDecodeError, AttributeError):
        return True


def show_stream_line(line: str) -> None:
    """Compact live view of claude's stream-json in the Orca terminal."""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        print(line, end="")
        return
    if ev.get("type") == "assistant":
        for part in ev.get("message", {}).get("content", []):
            if part.get("type") == "text" and part.get("text", "").strip():
                print(part["text"].strip())
            elif part.get("type") == "tool_use":
                arg = json.dumps(part.get("input", {}), ensure_ascii=False)
                print(f"  → {part.get('name')} {arg[:160]}")
    elif ev.get("type") == "result":
        print(f"\n[Ergebnis: {'Fehler' if ev.get('is_error') else 'ok'}] {str(ev.get('result', ''))[:2000]}")


def final_text(cli: str, lines: list[str]) -> str:
    if cli == "claude":
        for line in reversed(lines):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                return str(ev.get("result", ""))
        return ""
    return "".join(lines)[-8000:]


def launch(b: dict[str, Any], prompt: str, timeout_min: float, log_path: Path,
           extra_env: dict[str, str] | None = None, read_only: bool = False) -> tuple[int, bool, str]:
    """One fresh agent session; returns (exit code, hit a usage limit, final text)."""
    proc = subprocess.Popen(agent_command(b, prompt, read_only), env=agent_env(b, extra_env), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timer = threading.Timer(timeout_min * 60, lambda: os.killpg(proc.pid, signal.SIGTERM))
    timer.start()
    limited = False
    lines: list[str] = []
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            for line in proc.stdout:
                log.write(line)
                lines.append(line)
                limited |= is_limit_message(b["cli"], line)
                if b["cli"] == "claude":
                    show_stream_line(line)
                else:
                    print(line, end="")
        rc = proc.wait()
    finally:
        timer.cancel()
    return rc, limited and rc != 0, final_text(b["cli"], lines)


def set_cooldown(cfg: dict[str, Any], backend: str) -> None:
    (state_dir() / f"cooldown-{backend}").write_text(str(time.time() + cfg["limits"]["cooldown_min"] * 60))


def log_file(name: str) -> Path:
    logs = state_dir() / "logs"
    logs.mkdir(exist_ok=True)
    return logs / f"{time.strftime('%Y%m%d_%H%M%S')}_{name}.log"


# ---------------------------------------------------------------- run: one agent session in a worktree

def cmd_run(cfg: dict[str, Any], role: str, only_issue: int | None) -> int:
    worktree = Path(git("rev-parse", "--show-toplevel")).resolve()
    if worktree == PRIMARY.resolve():
        print(f"Agents laufen nicht im Primary-Checkout {PRIMARY}; `orca_agent.py tick` legt Worktrees an", file=sys.stderr)
        return 2
    slot = acquire_slot(cfg["limits"]["max_parallel"])
    if slot is None:
        print("alle Agent-Slots belegt; nichts gestartet")
        return 0
    reservation_path(role, only_issue).unlink(missing_ok=True)
    item = None
    for _ in range(3):  # another run may take the work between find_work and the lock
        item = find_work(cfg, role, only_issue=only_issue)
        if item is None:
            break
        work_fd = try_lock(work_lock_path(role, item["issue"]))
        if work_fd is not None:
            break
        item = None
    if item is None:
        print("keine Arbeit für", role, f"#{only_issue}" if only_issue else "")
        return 0
    n = item["issue"]
    rows = ledger(n) if n else []
    brief = ""
    if n:
        reason = limit_violation(cfg, item, rows)
        if reason:
            block_issue(n, reason)
            record({"time": time.time(), "role": role, "issue": n, "kind": item["kind"], "outcome": "limit", "reason": reason})
            print(f"#{n} gesperrt: {reason}")
            return 0
        view = issue_view(n)
        before = view["labels"]
        brief = build_brief(role, item["kind"], view)
    elif role in ("research", "audit"):
        (state_dir() / f"last-{role}").touch()

    if role in BUILD_ROLES:
        print("Worktree-Build (scripts/orca_setup.sh) …", flush=True)
        setup = subprocess.run(["bash", str(worktree / "scripts" / "orca_setup.sh")], cwd=str(worktree), check=False)
        if setup.returncode != 0:
            print(f"Worktree-Build fehlgeschlagen (exit {setup.returncode}); kein Agent gestartet", file=sys.stderr)
            record({"time": time.time(), "role": role, "issue": n, "kind": item["kind"], "outcome": "setup-failed"})
            return 1

    b = cfg["backends"][item["backend"]]
    log_path = log_file(f"{role}_{n or item['kind']}")
    run_id = log_path.stem
    print(f"Rolle {role} · {item['title']} · {item['backend']} ({b['model']}) · Log {log_path}", flush=True)
    t0 = time.time()
    rc, limited, _ = launch(b, build_prompt(cfg, item, rows, worktree, git("branch", "--show-current"), brief),
                            cfg["roles"][role]["timeout_min"], log_path,
                            {"RADIANCE_AGENT_ROLE": role, "RADIANCE_AGENT_ISSUE": str(n or ""), "RADIANCE_AGENT_RUN": run_id})
    row = {"time": t0, "seconds": round(time.time() - t0), "role": role, "issue": n, "kind": item["kind"],
           "backend": item["backend"], "model": b["model"], "tier": item.get("tier"), "rc": rc, "log": str(log_path),
           "run": run_id, "worktree": str(worktree)}
    if limited:
        set_cooldown(cfg, item["backend"])
        if role in ("research", "audit"):
            (state_dir() / f"last-{role}").unlink(missing_ok=True)
        record({**row, "rate_limited": True, "outcome": None})
        print(f"Nutzungslimit bei {item['backend']}: Pause {cfg['limits']['cooldown_min']} min, Lauf zählt nicht")
        return 0
    if not n:
        record({**row, "outcome": "done" if rc == 0 else "error"})
        return 0 if rc == 0 else 1

    after = issue_view(n)
    result = outcome(role, before, after["labels"], after["state"])
    record({**row, "outcome": result})
    if result is None:
        left = cfg["limits"]["max_no_handoff"] - count(ledger(n), role, None)
        how = "Zeitlimit" if rc == -signal.SIGTERM else f"exit {rc}"
        comment(n, f"Agent-Lauf ({role}, {b['model']}, {how}) endete ohne gültige Label-Übergabe. "
                   f"Log auf dem Server: `{log_path}`. Weitere Versuche dieser Rolle: {max(left, 0)}.\n\n— orca_agent.py")
        if left <= 0:
            block_issue(n, f"{cfg['limits']['max_no_handoff']} Läufe der Rolle {role} ohne gültige Übergabe")
        return 1
    print(f"#{n}: {result}")
    return 0


# ---------------------------------------------------------------- ask: blocking question to the planner

def question_path(qid: str) -> Path:
    qdir = state_dir() / "questions"
    qdir.mkdir(exist_ok=True)
    return qdir / f"{qid}.json"


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def wait_answer(qid: str, wait_s: float) -> int:
    path = question_path(qid)
    deadline = time.time() + wait_s
    while True:
        q = json.loads(path.read_text(encoding="utf-8"))
        if q["status"] in ("answered", "failed"):
            print(q["answer"])
            return 0
        if time.time() >= deadline:
            print(f"Antwort steht noch aus. Weiter warten mit: python3 {PRIMARY}/scripts/orca_agent.py answer {qid}")
            return 3
        time.sleep(5)


def cmd_ask(cfg: dict[str, Any], question: str, wait_s: float) -> int:
    role = os.environ.get("RADIANCE_AGENT_ROLE", "")
    issue = os.environ.get("RADIANCE_AGENT_ISSUE", "")
    run_id = os.environ.get("RADIANCE_AGENT_RUN", "")
    if role not in ASK_ROLES or not issue:
        print("ask ist nur aus einem code- oder review-Lauf heraus möglich", file=sys.stderr)
        return 2
    asked = [p for p in (state_dir() / "questions").glob("*.json")
             if json.loads(p.read_text(encoding="utf-8")).get("run") == run_id] if (state_dir() / "questions").is_dir() else []
    if len(asked) >= cfg["limits"]["max_questions"]:
        print(f"Fragelimit ({cfg['limits']['max_questions']} pro Lauf) erreicht. Nach Plan entscheiden oder "
              "bei echtem Widerspruch plan:needs-revision setzen.")
        return 1
    qid = f"{issue}-{time.strftime('%Y%m%d%H%M%S')}"
    write_json(question_path(qid), {"id": qid, "issue": int(issue), "role": role, "run": run_id, "question": question,
                                    "cwd": os.getcwd(), "status": "open", "asked": time.time()})
    with open(log_file(f"answer_{qid}"), "w", encoding="utf-8") as out:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_answer", qid], cwd=os.getcwd(),
                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    print(f"Frage {qid} an den Planer gestellt; warte bis {int(wait_s)} s …", flush=True)
    return wait_answer(qid, wait_s)


def cmd_answer_worker(cfg: dict[str, Any], qid: str) -> int:
    path = question_path(qid)
    q = json.loads(path.read_text(encoding="utf-8"))
    backend = cfg["roles"]["answer"]["backend"]
    problem = backend_problem(cfg, backend)
    if problem:
        q.update(status="failed", answer=f"Planer nicht erreichbar ({problem}). Nach Plan entscheiden; bei echtem "
                                          "Widerspruch zum Code plan:needs-revision setzen.")
        write_json(path, q)
        return 1
    b = cfg["backends"][backend]
    view = issue_view(q["issue"])
    qa = [c for c in since_latest_plan(view["comments"]) if QA_MARKER in c]
    context = [f"# Rückfrage zu Issue #{q['issue']} „{view['title']}“", "",
               f"Gestellt vom Agent `{q['role']}` im Worktree `{q['cwd']}` (dein Arbeitsverzeichnis).", "",
               "## Frage", "", q["question"], "", "## Plan", "", latest(view["comments"], PLAN_MARKER) or "(kein Plan)"]
    if qa:
        context += ["", "## Frühere Rückfragen zu diesem Plan", "", "\n\n---\n\n".join(qa)]
    prompt = (PROMPTS / "answer.md").read_text(encoding="utf-8") + "\n\n---\n\n" + "\n".join(context)
    log_path = log_file(f"answer-session_{qid}")
    t0 = time.time()
    rc, limited, text = launch(b, prompt, cfg["roles"]["answer"]["timeout_min"], log_path, read_only=True)
    record({"time": t0, "seconds": round(time.time() - t0), "role": "answer", "issue": q["issue"], "backend": backend,
            "model": b["model"], "rc": rc, "log": str(log_path), "outcome": "answered" if rc == 0 and text else None,
            "rate_limited": limited})
    if limited:
        set_cooldown(cfg, backend)
    if rc != 0 or not text.strip():
        q.update(status="failed", answer=f"Keine Antwort vom Planer (exit {rc}). Nach Plan entscheiden; bei echtem "
                                          "Widerspruch plan:needs-revision setzen.")
        write_json(path, q)
        return 1
    q.update(status="answered", answer=text.strip(), answered=time.time())
    write_json(path, q)
    comment(q["issue"], f"{QA_MARKER}\n**Rückfrage ({q['role']}):** {q['question']}\n\n"
                        f"**Antwort (Planer · {b['model']}):**\n\n{text.strip()}\n\n— orca_agent.py")
    return 0


# ---------------------------------------------------------------- tick: start agents, clean up worktrees

def orca(cfg: dict[str, Any], *args: str) -> str:
    proc = subprocess.run([cfg["orca"]["cli"], *args, "--json"], capture_output=True, text=True, check=False, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"{cfg['orca']['cli']} {' '.join(args[:2])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def worktree_records() -> dict[str, Any]:
    path = state_dir() / "worktrees.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def start_agent(cfg: dict[str, Any], item: dict[str, Any]) -> Path:
    role, n = item["role"], item["issue"]
    name = f"agent-{role}-{n or 'x'}-{time.strftime('%m%d-%H%M%S')}"
    wt = PRIMARY / "worktrees" / name
    git("-C", str(PRIMARY), "worktree", "add", "-b", f"agent/{name}", str(wt), "origin/main")
    cmd = f"python3 {PRIMARY / 'scripts' / 'orca_agent.py'} run {role}" + (f" --issue {n}" if n else "")
    try:
        if cfg["orca"]["launcher"] == "orca":
            title = f"{role} #{n}" if n else role
            orca(cfg, "terminal", "create", "--worktree", f"path:{wt}", "--title", title, "--command", cmd)
        else:
            with open(log_file(f"detached_{name}"), "w", encoding="utf-8") as out:
                subprocess.Popen(cmd.split(), cwd=str(wt), stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    except (RuntimeError, OSError):
        remove_worktree(cfg, wt, name)
        raise
    reservation_path(role, n).touch()
    recs = worktree_records()
    recs[name] = {"path": str(wt), "branch": f"agent/{name}", "created": time.time(), "role": role, "issue": n}
    write_json(state_dir() / "worktrees.json", recs)
    return wt


def remove_worktree(cfg: dict[str, Any], wt: Path, name: str) -> None:
    if cfg["orca"]["launcher"] == "orca":
        try:
            orca(cfg, "worktree", "rm", "--worktree", f"path:{wt}", "--force")
        except RuntimeError as e:
            print(f"orca worktree rm {name}: {e}; entferne mit git", file=sys.stderr)
    if wt.exists():
        git("-C", str(PRIMARY), "worktree", "remove", "--force", str(wt))
    git("-C", str(PRIMARY), "worktree", "prune")
    if subprocess.run(["git", "-C", str(PRIMARY), "show-ref", "--verify", "--quiet", f"refs/heads/agent/{name}"]).returncode == 0:
        git("-C", str(PRIMARY), "branch", "-D", f"agent/{name}")


def cleanup_worktrees(cfg: dict[str, Any]) -> None:
    """Removes agent worktrees older than keep_hours whose run is over and that hold no unpushed work."""
    recs = worktree_records()
    keep = cfg["orca"]["keep_worktree_hours"] * 3600
    for name, rec in list(recs.items()):
        wt = Path(rec["path"])
        if time.time() - rec["created"] < keep or is_locked(work_lock_path(rec["role"], rec.get("issue"))):
            continue
        if wt.exists():
            dirty = git("status", "--porcelain", cwd=wt)
            unpushed = git("log", "--oneline", "HEAD", "--not", "--remotes", cwd=wt)
            if dirty or unpushed:
                if not rec.get("kept"):
                    print(f"{name}: ungesicherte Änderungen, bleibt liegen ({wt})", file=sys.stderr)
                    rec["kept"] = True
                continue
        remove_worktree(cfg, wt, name)
        del recs[name]
    write_json(state_dir() / "worktrees.json", recs)


def cmd_tick(cfg: dict[str, Any]) -> int:
    tick_fd = try_lock(state_dir() / "tick.lock")
    if tick_fd is None:
        print("anderer tick läuft")
        return 0
    try:
        return tick(cfg)
    finally:
        os.close(tick_fd)


def tick(cfg: dict[str, Any]) -> int:
    if cfg["orca"]["launcher"] == "orca":
        orca(cfg, "status")
    cleanup_worktrees(cfg)
    free = free_slots(cfg["limits"]["max_parallel"]) - active_reservations()
    if free <= 0:
        return 0
    git("-C", str(PRIMARY), "fetch", "--quiet", "origin", "main")
    failed = []
    for role in TICK_ORDER:
        try:
            while free > 0:
                item = find_work(cfg, role)
                if item is None:
                    break
                wt = start_agent(cfg, item)
                print(f"gestartet: {role} {('#' + str(item['issue'])) if item['issue'] else ''} · {item['backend']} · {wt}")
                free -= 1
                if item["issue"] is None:
                    break
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            # One broken role (e.g. missing upstream state) must not stop the others; the exit code still fails.
            print(f"[{role}] fehlgeschlagen: {e}", file=sys.stderr)
            failed.append(role)
    return 2 if failed else 0


# ---------------------------------------------------------------- small commands

def cmd_check(cfg: dict[str, Any], role: str) -> int:
    if free_slots(cfg["limits"]["max_parallel"]) - active_reservations() <= 0:
        print("alle Agent-Slots belegt", file=sys.stderr)
        return 1
    item = find_work(cfg, role)
    if item is None:
        return 1
    print(f"#{item['issue']} {item['title']} · {item['backend']}" if item["issue"] else f"{item['title']} · {item['backend']}")
    return 0


def cmd_labels() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gh_bridge
    gh_bridge.ensure_labels()
    existing = {l["name"] for l in json.loads(gh("label", "list", "--repo", REPO, "--limit", "300", "--json", "name"))}
    for name, (color, desc) in WORKFLOW_LABELS.items():
        if name not in existing:
            gh("label", "create", name, "--repo", REPO, "--color", color, "--description", desc)
            print("angelegt:", name)
    return 0


def cmd_status(cfg: dict[str, Any]) -> int:
    lim = cfg["limits"]
    print(f"Slots frei: {free_slots(lim['max_parallel'])}/{lim['max_parallel']}, reserviert: {active_reservations()}"
          f"  (State: {STATE})")
    for name in cfg["backends"]:
        print(f"  {name:13s} {backend_problem(cfg, name) or 'bereit'}")
    for r in ledger()[-15:]:
        when = time.strftime("%m-%d %H:%M", time.localtime(r["time"]))
        print(f"  {when} {r['role']:8s} #{r.get('issue') or '-':<5} {r.get('model', ''):14s} {r.get('outcome')}")
    qdir = state_dir() / "questions"
    for p in sorted(qdir.glob("*.json")) if qdir.is_dir() else []:
        q = json.loads(p.read_text(encoding="utf-8"))
        if q["status"] == "open":
            print(f"  offene Frage {q['id']} ({q['role']}): {q['question'][:80]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("tick")
    p = sub.add_parser("run")
    p.add_argument("role", choices=ROLES)
    p.add_argument("--issue", type=int)
    p = sub.add_parser("check")
    p.add_argument("role", choices=ROLES)
    p = sub.add_parser("ask")
    p.add_argument("question")
    p.add_argument("--wait", type=float, default=240)
    p = sub.add_parser("answer")
    p.add_argument("id")
    p.add_argument("--wait", type=float, default=240)
    p = sub.add_parser("_answer")
    p.add_argument("id")
    sub.add_parser("labels")
    sub.add_parser("status")
    args = ap.parse_args()
    try:
        cfg = load_config()
        if args.command == "tick":
            return cmd_tick(cfg)
        if args.command == "run":
            return cmd_run(cfg, args.role, args.issue)
        if args.command == "check":
            return cmd_check(cfg, args.role)
        if args.command == "ask":
            return cmd_ask(cfg, args.question, args.wait)
        if args.command == "answer":
            return wait_answer(args.id, args.wait)
        if args.command == "_answer":
            return cmd_answer_worker(cfg, args.id)
        if args.command == "labels":
            return cmd_labels()
        return cmd_status(cfg)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print(f"orca_agent {args.command} fehlgeschlagen: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
