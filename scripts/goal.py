#!/usr/bin/env python3
"""goal.py — the optimisation target and whether main has reached it.

    goal.py                 print the current status (reports/goal_status.json)

The target lives in baselines/targets.json (only Leon changes it, like every file in baselines/):

    {"total_score": 900,                       BetterBench composite, scripts/bench_metrics.py
     "at_least": {"decode_med_tps": 120, ...},  optional floors, metric names from bench_metrics
     "at_most":  {"c8_itl_p99_ms": 15, ...}}    optional ceilings

null or a missing key means "no requirement". A target with nothing set is no target.

The lever queue measures every new origin/main with BetterBench (the gate's own benchmark, see
scripts/profile_engine.py) and calls record(). The target counts as REACHED only when the two
latest measurements both meet it: one benchmark run is not more precise than the gate's A/A spread
(docs/GATE.md), and a single lucky run must not stop the optimisation. scripts/orca_agent.py reads
the status: while the target is set and not reached, research and audit keep producing levers;
once reached, they stop, and in-flight work still runs through the gate.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGETS = REPO_ROOT / "baselines" / "targets.json"
STATUS = REPO_ROOT / "reports" / "goal_status.json"
HISTORY_KEEP = 50
SUBSCORE_MAX = {"decode": 1000.0, "prefill": 1200.0, "concurrency": 1000.0, "tail": 1000.0}


def load_targets(path: Path = TARGETS) -> dict[str, Any]:
    if not path.is_file():
        return {}
    t = json.loads(path.read_text(encoding="utf-8"))
    return {"total_score": t.get("total_score"),
            "at_least": {k: v for k, v in (t.get("at_least") or {}).items() if v is not None},
            "at_most": {k: v for k, v in (t.get("at_most") or {}).items() if v is not None}}


def target_set(t: dict[str, Any]) -> bool:
    return bool(t) and (t.get("total_score") is not None or bool(t.get("at_least")) or bool(t.get("at_most")))


def evaluate(metrics: dict[str, Any], t: dict[str, Any]) -> dict[str, Any]:
    """Per requirement: value, limit, met. Plus where the composite's points are left."""
    checks = []
    if t.get("total_score") is not None:
        checks.append({"metric": "total_score", "op": ">=", "limit": t["total_score"],
                       "value": metrics.get("total_score"), "met": (metrics.get("total_score") or 0) >= t["total_score"]})
    for k, v in t.get("at_least", {}).items():
        checks.append({"metric": k, "op": ">=", "limit": v, "value": metrics.get(k),
                       "met": metrics.get(k) is not None and metrics[k] >= v})
    for k, v in t.get("at_most", {}).items():
        checks.append({"metric": k, "op": "<=", "limit": v, "value": metrics.get(k),
                       "met": metrics.get(k) is not None and metrics[k] <= v})
    # Weighted points still to gain per part of the composite, scaled like the composite itself.
    # The tail part also drives the stability factor that multiplies everything, so it is listed
    # with that factor named rather than folded into one number.
    room = []
    subs, weights = metrics.get("subscores") or {}, metrics.get("weights") or {}
    scale = (metrics.get("stability_factor") or 1.0) * (metrics.get("guardrail") or 1.0)
    for part, score in subs.items():
        room.append({"part": part, "subscore": score, "weight": weights.get(part),
                     "weighted_room": round((SUBSCORE_MAX[part] - score) * (weights.get(part) or 0) * scale, 1)})
    room.sort(key=lambda r: -r["weighted_room"])
    return {"checks": checks, "met": bool(checks) and all(c["met"] for c in checks), "room": room,
            "stability_factor": metrics.get("stability_factor"), "guardrail": metrics.get("guardrail")}


def record(sha: str, metrics: dict[str, Any], report_dir: str, status_path: Path = STATUS,
           targets_path: Path = TARGETS) -> dict[str, Any]:
    t = load_targets(targets_path)
    status = json.loads(status_path.read_text()) if status_path.is_file() else {"history": []}
    entry = {"time": time.strftime("%Y-%m-%d %H:%M"), "sha": sha, "report": report_dir,
             "metrics": {k: v for k, v in metrics.items() if k != "categories"}}
    history = (status.get("history") or [])[-(HISTORY_KEEP - 1):] + [entry]
    status = judge(history, t)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=2))
    tmp.replace(status_path)
    return status


def judge(history: list[dict[str, Any]], t: dict[str, Any]) -> dict[str, Any]:
    """Evaluated against the CURRENT targets, so raising the target resumes the optimisation."""
    if not history:
        return {"targets": t, "target_set": target_set(t), "reached": False, "needs_confirmation": False,
                "latest": None, "history": []}
    if target_set(t):
        for h in history[-2:]:
            h["evaluation"] = evaluate(h["metrics"], t)
    latest = history[-1]
    last_two = history[-2:]
    reached = target_set(t) and len(last_two) == 2 and all(h["evaluation"]["met"] for h in last_two)
    return {"targets": t, "target_set": target_set(t), "reached": reached,
            "needs_confirmation": target_set(t) and latest["evaluation"]["met"] and not reached,
            "latest": latest, "history": history}


def load_status(status_path: Path = STATUS) -> dict[str, Any] | None:
    return json.loads(status_path.read_text()) if status_path.is_file() else None


def current(status_path: Path = STATUS, targets_path: Path = TARGETS) -> dict[str, Any]:
    status = load_status(status_path)
    return judge((status or {}).get("history") or [], load_targets(targets_path))


def render(status: dict[str, Any] | None) -> str:
    """Markdown for prompts and the GitHub status issue."""
    if not status or not status.get("latest"):
        return "Noch keine Messung von `main` (`reports/goal_status.json` fehlt)."
    t, latest = status["targets"], status["latest"]
    m = latest["metrics"]
    lines = [f"Messung von `main` `{latest['sha'][:10]}` ({latest['time']}), Bericht `{latest['report']}`.", ""]
    if not status["target_set"]:
        lines.append("Kein Ziel gesetzt (`baselines/targets.json`).")
    else:
        state = "erreicht (zweimal hintereinander)" if status["reached"] else \
            ("erfüllt, Bestätigung durch eine zweite Messung steht aus" if status["needs_confirmation"] else "nicht erreicht")
        lines += [f"**Ziel: {state}.**", "", "| Anforderung | Ziel | Gemessen | erfüllt |", "|---|---|---|---|"]
        for c in latest["evaluation"]["checks"]:
            lines.append(f"| `{c['metric']}` | {c['op']} {c['limit']} | {c['value']} | {'ja' if c['met'] else 'nein'} |")
        room = latest["evaluation"]["room"]
        if room:
            lines += ["", "Wo im Score die meisten Punkte fehlen (Gewicht × Abstand zum Maximum × Stabilität × Guardrail):", "",
                      "| Teil | Teilscore | Gewicht | fehlende gewichtete Punkte |", "|---|---|---|---|"]
            for r in room:
                lines.append(f"| {r['part']} | {r['subscore']} | {r['weight']} | {r['weighted_room']} |")
            lines.append(f"\nStabilitätsfaktor {latest['evaluation']['stability_factor']} (aus 1%-Lows / Median-ITL), "
                         f"Guardrail {latest['evaluation']['guardrail']} (c8 p99 über Grenze).")
    lines += ["", "| Metrik | Wert |", "|---|---|"] + [f"| `{k}` | {v} |" for k, v in m.items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render(current()))
    sys.exit(0)
