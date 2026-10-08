# RadianceMine

Arbeitsumgebung für die [Radiance](https://codeberg.org/StillDeadcode/radiance)-Inferenz-Engine
auf 2× AMD Radeon AI PRO R9700 (gfx1201, RDNA4) mit Tensor-Parallelität 2. Neue Optimierungen
(„Hebel“) werden von Orca-Agents geschrieben und von einem deterministischen Gate gegen die
aktuelle Baseline gemessen, bevor sie nach `main` kommen.

## Überblick

```
Codeberg-PRs ──► watch_upstream.py (Jev: nützlich?) ──► candidates/upstream/REVIEW.md ──► Agent upstream (Bewertung)
Codeberg-main ──► upstream_sync.py (kein Merge) ──► Issue upstream:sync ──► Agent plan ──► … wie ein Hebel (Modus merge)

Agent research (Papers, andere Engines) ─┐
Agent audit (Coverage-Karte des Codes) ──┼─► Issue research:new-lever
Leon ────────────────────────────────────┘          │
                                           Agent plan (Opus): verwerfen oder Plan + tier:*
                                                    │ plan:ready
                                           Agent code (Gemini/GLM, tier) ◄──┐ changes-requested
                                                    │ needs-code-review     │
                                           Agent review (eine Stufe höher) ─┘
                                                    │ status:ready-to-test
                         lever_queue.py (systemd) ◄─┘
                         ├─ Worktree auf origin/main + Patch, frischer Build
                         ├─ gate_check.sh: Tier 0 statisch · Tier 3 ISA-Diff · A/B Parität+Speed
                         └─ Ergebnis ins Issue ──► PASS: PR (Leon merged)
                                              └─► FAIL: status:needs-review ──► Agent code (Gate-Fix)
```

Ein systemd-Timer (`scripts/orca_agent.py tick`) wählt Arbeit, Modell und Slot und startet jeden Agent
in einem eigenen Worktree in Orca; Opus plant, Gemini und GLM setzen um.

## Dokumente

| | |
|---|---|
| `AGENTS.md` | Regeln für alle Agents |
| `docs/ORCA_AGENT_WORKFLOW.md` | Ablauf der Automationen, Hebel-Pakete, Labels, Modelle, Grenzen |
| `docs/agents/` | Rollen-Prompts (plan, code, review, research, audit, upstream) |
| `docs/GATE.md` | Was das Gate misst und wie streng |
| `docs/UPSTREAM.md` | Upstream übernehmen: PR-Bewertung, Sync von Codeberg-main, eigenes Kernel-Plugin |
| `HARDWARE_GROUND_TRUTH.md` | Gemessene Hardware-Werte |
| `spec.md` | Engine-Architektur (Upstream) |
| `docs/history/` | Frühere Optimierungsrunden, Postmortems, Hebel-Katalog |

## Häufige Befehle

```bash
python3 scripts/lever_queue.py add <slug>          # Hebel aus candidates/<slug> testen
python3 scripts/lever_queue.py list                # Warteschlange und Ergebnisse
python3 scripts/orca_agent.py status              # Agent-Slots, Backends, letzte Läufe
python3 scripts/lever_review.py claims <slug>      # Belege im Hebel-README prüfen
python3 scripts/lever_review.py similar "<idee>"   # schon versucht?
python3 scripts/watch_upstream.py --done <PR> --verdict useful|not-useful
bash scripts/engine_manager.sh start|stop|status   # Engine manuell
bash scripts/measure_hardware.sh                   # Bandbreiten neu messen
```

## Dienste (systemd, im CT 107)

| Dienst | Aufgabe |
|---|---|
| `radiance-upstream-watcher` | Codeberg-PRs abfragen, `REVIEW.md` pflegen |
| `radiance-lever-queue` | GitHub-Issues `status:ready-to-test` bauen, gaten, Ergebnis zurückmelden |
| `radiance-upstream-sync` (Timer, alle 6 h) | Codeberg-main spiegeln, Sync-Issue anlegen (merged nie selbst) |
| `radiance-agent-tick` (Timer, alle 3 min) | Agents starten: Arbeit, Modell und Slot wählen, Worktree + Orca-Terminal |

Unit-Dateien: `scripts/systemd/` (Queue, Upstream-Watcher, Agent-Tick). Agents: siehe `docs/ORCA_AGENT_WORKFLOW.md`.
