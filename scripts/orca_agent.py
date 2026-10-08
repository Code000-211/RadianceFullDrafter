#!/usr/bin/env python3
"""orca_agent.py — role dispatch for the Orca automations of RadianceMine.

Every Orca automation calls this script twice: as its precheck and as its agent command.

    orca_agent.py check <role>   exit 0 and print the work item when a slot is free and there is work,
                                 1 = nothing to do, 2 = check failed (Orca starts no agent)
    orca_agent.py run <role>     inside the automation's worktree: take a slot and the work item, pick
                                 the model, start the agent CLI, verify the label handoff afterwards
    orca_agent.py labels         create the workflow labels on GitHub (gate labels via gh_bridge)
    orca_agent.py status         slots, cooldowns, last runs

Roles: plan, code, review, research, audit, upstream (prompts in docs/agents/<role>.md).
Models, tiers and limits: scripts/agents/models.json. Workflow: docs/ORCA_AGENT_WORKFLOW.md.

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

ROLES = ("plan", "code", "review", "research", "audit", "upstream")
TIERS = ("light", "medium", "heavy")
TIER_DE = {"light": "leicht", "medium": "mittel", "heavy": "schwer"}

WORKFLOW_LABELS = {
    "research:new-lever": ("5319e7", "Idee für einen Hebel; wartet auf den Planer"),
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
    "plan/new": "neue Idee planen",
    "plan/revise": "Plan überarbeiten",
    "code/changes": "Review-Änderungen umsetzen",
    "code/gate-fix": "Gate-Fehlschlag beheben",
    "code/implement": "Plan implementieren",
    "review/review": "Branch reviewen",
}


# ---------------------------------------------------------------- configuration, GitHub

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
    data = json.loads(gh("issue", "view", str(number), "--repo", REPO, "--json", "number,title,state,labels,comments"))
    return {"number": data["number"], "title": data["title"], "state": data["state"],
            "labels": {l["name"] for l in data["labels"]},
            "comments": [c.get("body") or "" for c in data.get("comments", [])]}


def gh_comments(number: int) -> list[str]:
    return issue_view(number)["comments"]


def block_issue(number: int, reason: str) -> None:
    gh("issue", "comment", str(number), "--repo", REPO, "--body", f"Automatisch gesperrt: {reason}\n\n— orca_agent.py")
    gh("issue", "edit", str(number), "--repo", REPO, "--add-label", "status:blocked")


# ---------------------------------------------------------------- selection (pure)

def kind_of(role: str, labels: set[str], has_gate_result: Callable[[], bool]) -> str | None:
    """Which job this issue is for the role, or None. Order of the checks is the priority."""
    if labels & DEAD:
        return None
    if role == "plan":
        if "plan:needs-revision" in labels:
            return "revise"
        if "research:new-lever" in labels and not labels & ({"plan:ready"} | DOWNSTREAM):
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


def pick_tier(labels: set[str], failures: int, offset: int = 0) -> tuple[str, int]:
    """Planner's tier (default medium), one step up per failed round, plus the role offset."""
    set_tiers = [TIERS.index(l[5:]) for l in labels if l.startswith("tier:") and l[5:] in TIERS]
    base = max(set_tiers) if set_tiers else 1
    return TIERS[min(len(TIERS) - 1, base + failures + offset)], base


def outcome(role: str, before: set[str], after: set[str], state: str) -> str | None:
    """What the agent handed over; None means no valid handoff."""
    if "status:blocked" in after - before:
        return "blocked"
    if role == "plan":
        if state == "CLOSED" or "plan:rejected" in after:
            return "rejected"
        if "plan:ready" in after and "plan:needs-revision" not in after and not after.isdisjoint(set(f"tier:{t}" for t in TIERS)):
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


# ---------------------------------------------------------------- local state: locks, ledger, cooldowns

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


def issue_lock_path(number: int) -> Path:
    return state_dir() / f"issue-{number}.lock"


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

def backend_for(cfg: dict[str, Any], role: str, labels: set[str], failures: int) -> tuple[str, str | None]:
    rc = cfg["roles"][role]
    if rc.get("tiered"):
        tier, _ = pick_tier(labels, failures, rc.get("tier_offset", 0))
        return cfg["tiers"][tier], tier
    return rc["backend"], None


def code_failures(comments: list[str], rows: list[dict[str, Any]]) -> int:
    return gate_failures(comments) + count(rows, "review", "changes-requested") + count(rows, "code", None)


def find_work(cfg: dict[str, Any], role: str, verbose: bool = True) -> dict[str, Any] | None:
    lim = cfg["limits"]
    if role in ("research", "audit"):
        ideas = [i for i in open_issues() if "research:new-lever" in i["labels"] and not i["labels"] & DEAD]
        if len(ideas) >= lim["max_open_ideas"]:
            if verbose:
                print(f"{len(ideas)} offene Ideen >= {lim['max_open_ideas']}: erst abarbeiten", file=sys.stderr)
            return None
        stamp = state_dir() / f"last-{role}"
        if stamp.is_file() and time.time() - stamp.stat().st_mtime < lim["interval_hours"][role] * 3600:
            return None
        backend = cfg["roles"][role]["backend"]
        problem = backend_problem(cfg, backend)
        if problem:
            if verbose:
                print(problem, file=sys.stderr)
            return None
        return {"role": role, "issue": None, "title": f"{role}-Lauf", "kind": role, "backend": backend, "tier": None}
    if role == "upstream":
        state = json.loads((PRIMARY / "telemetry" / "upstream_review.json").read_text())
        for e in sorted(state["prs"].values(), key=lambda e: -(e.get("useful") or 0)):
            if e.get("open") and not e.get("done") and not e.get("assessment") and (e.get("useful") or 1.0) >= 0.5:
                backend = cfg["roles"]["upstream"]["backend"]
                problem = backend_problem(cfg, backend)
                if problem:
                    if verbose:
                        print(problem, file=sys.stderr)
                    return None
                return {"role": role, "issue": None, "title": f"upstream PR #{e['pr_id']} {e['title']}",
                        "kind": "upstream", "backend": backend, "tier": None}
        return None

    cache: dict[int, list[str]] = {}

    def comments_of(n: int) -> list[str]:
        if n not in cache:
            cache[n] = gh_comments(n)
        return cache[n]

    for issue, kind in work_items(role, open_issues(), comments_of):
        n = issue["number"]
        if is_locked(issue_lock_path(n)):
            continue
        rows = ledger(n)
        failures = code_failures(comments_of(n), rows) if role in ("code", "review") else 0
        backend, tier = backend_for(cfg, role, issue["labels"], failures)
        problem = backend_problem(cfg, backend)
        if problem:
            if verbose:
                print(f"#{n} übersprungen: {problem}", file=sys.stderr)
            continue
        return {"role": role, "issue": n, "title": issue["title"], "kind": kind, "backend": backend,
                "tier": tier, "failures": failures, "labels": sorted(issue["labels"])}
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

def build_prompt(cfg: dict[str, Any], item: dict[str, Any], rows: list[dict[str, Any]], worktree: Path, branch: str) -> str:
    b = cfg["backends"][item["backend"]]
    lim = cfg["limits"]
    lines = ["# Auftrag", "", f"Rolle: **{item['role']}**"]
    if item["issue"]:
        lines += [f"Issue: #{item['issue']} „{item['title']}“ ({KIND_DE[item['role'] + '/' + item['kind']]})",
                  f"Issue vollständig lesen: `gh issue view {item['issue']} --repo {REPO} --comments`"]
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
                     f"{1 + lim['max_plan_revisions']}, Gate-Fehlschläge siehe Issue (max. 3)")
    lines += [f"Jeden Kommentar beenden mit: `— Agent {item['role']} · {b['model']}`", "",
              "Lies zuerst `AGENTS.md` und `docs/ORCA_AGENT_WORKFLOW.md`.", "", "---", ""]
    return "\n".join(lines) + (PROMPTS / f"{item['role']}.md").read_text(encoding="utf-8")


def agent_command(b: dict[str, Any], prompt: str) -> list[str]:
    if b["cli"] == "claude":
        return ["claude", "-p", prompt, "--model", b["model"], "--dangerously-skip-permissions",
                "--output-format", "stream-json", "--verbose"]
    if b["cli"] == "agy":
        return ["agy", "-p", prompt, "--model", b["model"], "--dangerously-skip-permissions"]
    raise ValueError(f"unbekannte CLI {b['cli']}")


def agent_env(b: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    # An inherited endpoint or token must never reroute an "Opus" run to another provider.
    for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
              "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        env.pop(k, None)
    env.update(b.get("env", {}))
    if b.get("key_file"):
        env[b["key_env"]] = Path(b["key_file"]).expanduser().read_text(encoding="utf-8").strip()
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


def launch(b: dict[str, Any], prompt: str, timeout_min: int, log_path: Path) -> tuple[int, bool]:
    proc = subprocess.Popen(agent_command(b, prompt), env=agent_env(b), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    timer = threading.Timer(timeout_min * 60, lambda: os.killpg(proc.pid, signal.SIGTERM))
    timer.start()
    limited = False
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            for line in proc.stdout:
                log.write(line)
                limited |= is_limit_message(b["cli"], line)
                if b["cli"] == "claude":
                    show_stream_line(line)
                else:
                    print(line, end="")
        rc = proc.wait()
    finally:
        timer.cancel()
    return rc, limited and rc != 0


def git_out(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


# ---------------------------------------------------------------- commands

def cmd_check(cfg: dict[str, Any], role: str) -> int:
    if free_slots(cfg["limits"]["max_parallel"]) == 0:
        print("alle Agent-Slots belegt", file=sys.stderr)
        return 1
    item = find_work(cfg, role)
    if item is None:
        return 1
    print(f"#{item['issue']} {item['title']}" if item["issue"] else item["title"])
    return 0


def cmd_run(cfg: dict[str, Any], role: str) -> int:
    worktree = Path(git_out("rev-parse", "--show-toplevel")).resolve()
    if worktree == PRIMARY.resolve():
        print(f"Agents laufen nicht im Primary-Checkout {PRIMARY}; Orca-Worktree oder scripts/create_worktree.sh", file=sys.stderr)
        return 2
    slot = acquire_slot(cfg["limits"]["max_parallel"])
    if slot is None:
        print("alle Agent-Slots belegt; nichts gestartet")
        return 0
    item = None
    issue_fd = None
    for _ in range(3):  # another run may take the issue between find_work and the lock
        item = find_work(cfg, role)
        if item is None or item["issue"] is None:
            break
        issue_fd = try_lock(issue_lock_path(item["issue"]))
        if issue_fd is not None:
            break
        item = None
    if item is None:
        print("keine Arbeit für", role)
        return 0
    n = item["issue"]
    rows = ledger(n) if n else []
    if n:
        reason = limit_violation(cfg, item, rows)
        if reason:
            block_issue(n, reason)
            record({"time": time.time(), "role": role, "issue": n, "kind": item["kind"], "outcome": "limit", "reason": reason})
            print(f"#{n} gesperrt: {reason}")
            return 0
        before = set(item["labels"])
    elif role in ("research", "audit"):
        (state_dir() / f"last-{role}").touch()

    b = cfg["backends"][item["backend"]]
    logs = state_dir() / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"{time.strftime('%Y%m%d_%H%M%S')}_{role}_{n or item['kind']}.log"
    print(f"Rolle {role} · {item['title']} · {item['backend']} ({b['model']}) · Log {log_path}", flush=True)
    t0 = time.time()
    rc, limited = launch(b, build_prompt(cfg, item, rows, worktree, git_out("branch", "--show-current")),
                         cfg["roles"][role]["timeout_min"], log_path)
    row = {"time": t0, "seconds": round(time.time() - t0), "role": role, "issue": n, "kind": item["kind"],
           "backend": item["backend"], "model": b["model"], "tier": item.get("tier"), "rc": rc, "log": str(log_path)}
    if limited:
        until = time.time() + cfg["limits"]["cooldown_min"] * 60
        (state_dir() / f"cooldown-{item['backend']}").write_text(str(until))
        if not n:
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
        gh("issue", "comment", str(n), "--repo", REPO, "--body",
           f"Agent-Lauf ({role}, {b['model']}, {'Zeitlimit' if rc == -signal.SIGTERM else f'exit {rc}'}) "
           f"endete ohne gültige Label-Übergabe. "
           f"Log auf dem Server: `{log_path}`. Weitere Versuche dieser Rolle: {max(left, 0)}.\n\n— orca_agent.py")
        if left <= 0:
            block_issue(n, f"{cfg['limits']['max_no_handoff']} Läufe der Rolle {role} ohne gültige Übergabe")
        return 1
    print(f"#{n}: {result}")
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
    print(f"Slots frei: {free_slots(lim['max_parallel'])}/{lim['max_parallel']}  (State: {STATE})")
    for name in cfg["backends"]:
        print(f"  {name:13s} {backend_problem(cfg, name) or 'bereit'}")
    for r in ledger()[-15:]:
        when = time.strftime("%m-%d %H:%M", time.localtime(r["time"]))
        print(f"  {when} {r['role']:8s} #{r.get('issue') or '-':<5} {r.get('model', ''):14s} {r.get('outcome')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "run", "labels", "status"])
    ap.add_argument("role", nargs="?", choices=ROLES)
    args = ap.parse_args()
    if args.command in ("check", "run") and not args.role:
        ap.error("check und run brauchen eine Rolle")
    try:
        cfg = load_config()
        if args.command == "check":
            return cmd_check(cfg, args.role)
        if args.command == "run":
            return cmd_run(cfg, args.role)
        if args.command == "labels":
            return cmd_labels()
        return cmd_status(cfg)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print(f"orca_agent {args.command} fehlgeschlagen: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
