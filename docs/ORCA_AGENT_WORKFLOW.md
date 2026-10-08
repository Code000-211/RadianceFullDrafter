# Orca-Agent-Workflow für RadianceMine

Diese Datei ist die Arbeitsanweisung für Agents, die von Orca-Automationen gestartet werden.
Sie gilt zusammen mit `AGENTS.md`. Die Rollen-Prompts stehen in `docs/agents/<rolle>.md`;
`scripts/orca_agent.py` wählt Arbeit, Modell und Slot und prüft die Übergabe.

## Wer entscheidet was

| Aufgabe | Wer | Wie |
|---|---|---|
| Ideen finden | Agents `research` (extern) und `audit` (eigener Code) | Issue mit `research:new-lever` |
| Idee annehmen oder verwerfen, Implementierungsplan, Stufe | Agent `plan` (stärkstes Modell) | Plan-Kommentar, `plan:ready` + `tier:*` |
| Patch schreiben, Gate-Fehlschlag beheben | Agent `code` (Modell nach Stufe) | Branch + `candidate:`/`ref:`-Block, `needs-code-review` |
| Patch freigeben | Agent `review` (eine Stufe über `code`) | `status:ready-to-test` oder `changes-requested` |
| Upstream-PR bewerten | Agent `upstream` | `watch_upstream.py --assess` |
| Bauen, Parität prüfen, A/B messen, PASS/FAIL | `scripts/lever_queue.py` (systemd-Dienst `radiance-lever-queue`) | deterministisch, mit den Skripten des Primary-Checkouts `/home/orca/RadianceMine` |
| Gate-Ergebnis ins Issue schreiben, Labels `queued`/`gate-passed`/`needs-review`, PR öffnen | `scripts/gh_bridge.py` | nur dieser Code setzt diese Labels |
| Rundenlimits durchsetzen, Agent ohne Übergabe melden | `scripts/orca_agent.py` | setzt `status:blocked` mit Begründung |
| PR mergen, `status:blocked` aufheben, Gate-Einstellungen ändern, `audit:bug` entscheiden | Leon | |

Ein Agent kann kein PASS erzeugen: Das Gate läuft immer mit den Skripten und Schwellen des
Primary-Checkouts `/home/orca/RadianceMine` (Branch `main`); Änderungen an `scripts/` oder
`baselines/` auf einem Agent-Branch wirken sich auf den Test des eigenen Hebels nicht aus.
Dasselbe gilt für Rollen-Prompts und `scripts/agents/models.json`: `orca_agent.py` liest sie aus
dem Primary-Checkout. Nach einem Merge auf GitHub den Primary-Checkout mit `git pull --ff-only`
nachziehen.

## Zustände eines Hebel-Issues

```
research:new-lever ──(plan)──► plan:ready + tier:*  ──(code)──► needs-code-review ──(review)──► status:ready-to-test
        │                         ▲                      ▲               │                              │
        └─(plan)─► plan:rejected  │                      └───────────────┘ changes-requested            ▼ (Queue)
                   (geschlossen)  └── plan:needs-revision ◄─(code/review)                         status:queued
                                                                                                        │
                                       status:gate-passed (PR offen, Leon merged) ◄────────────────────┤
                                       status:needs-review ──(code: Gate-Fix)──► needs-code-review ◄────┘
```

`status:blocked` (nur Leon hebt es auf) setzt: die Queue nach 3 Gate-Läufen ohne PASS,
`orca_agent.py` bei überschrittenem Rundenlimit oder wiederholtem Lauf ohne Übergabe, ein Agent,
der den Hebel begründet für aussichtslos hält.

## Labels

| Label | Gesetzt von | Bedeutung |
|---|---|---|
| `research:new-lever` | research, audit, Leon | Idee, wartet auf den Planer |
| `source:research`, `source:audit` | research, audit | Herkunft der Idee |
| `plan:ready` | plan | Plan steht (neuester Kommentar mit `<!-- radiance-plan -->`) |
| `tier:light`, `tier:medium`, `tier:heavy` | plan | Schwierigkeit; bestimmt das Modell für code und review |
| `plan:needs-revision` | code, review | Plan passt nicht zum Code oder zum Gate-Ergebnis |
| `plan:rejected` | plan | Idee verworfen, Issue geschlossen |
| `needs-code-review` | code | Branch steht, wartet auf Review |
| `changes-requested` | review | blockierende Befunde, zurück an code |
| `status:*` | Queue/gh_bridge; `status:ready-to-test` auch review; `status:blocked` auch Agents | siehe oben |
| `audit:coverage` | audit | das eine Tracking-Issue mit der Coverage-Karte |
| `audit:bug` | audit | Korrektheits-/Paritätsrisiko, entscheidet Leon |

Anlegen (einmalig, idempotent): `python3 scripts/orca_agent.py labels`.

## Ein Hebel-Paket

Im Orca-Worktree der Automation (Branch `OoguroRyuuya/<name>`, abgeleitet von `origin/main`, `build_hip` ist durch das Setup schon gebaut):

```
candidates/<slug>/
├── README.md     Was, warum, erwartete Wirkung als Hypothese (keine erfundenen Messwerte)
├── lever.patch   git diff gegen origin/main (git diff origin/main -- <dateien> > lever.patch)
└── gate.json     optional: {"engine_args": ["--flag"], "engine_env": {"VAR": "1"}}
```

- `lever.patch` muss mit `git diff` erzeugt sein. Handgeschriebene Patches mit erfundenen
  `index`-Hashes werden von `lever_review.py claims` abgelehnt.
- Hebel, die hinter einem Flag oder einer Umgebungsvariable liegen, brauchen `gate.json`,
  sonst misst das Gate die Standardkonfiguration und damit den Hebel gar nicht.
- Messwerte stehen nur im README, wenn sie aus einem Gate-Bericht stammen (mit Pfad). Bis dahin
  sind Wirkungen als Erwartung formuliert.
- Hardware-Fakten aus `HARDWARE_GROUND_TRUTH.md` verwenden (PCIe 4.0, P2P ~27 GB/s nur beim
  Schreiben in die andere GPU, ~6 GB/s beim Lesen).

Vor dem Abgeben:

```bash
python3 scripts/lever_review.py similar "<Idee in einem Satz>"   # schon versucht?
python3 scripts/lever_review.py claims <slug>                    # Belege, Patch, gate.json
cmake --build build_hip                                          # baut der Patch? (Worktree-Setup hat build_hip schon angelegt)
```

`claims` muss `RESULT: OK` liefern. Ein `similar`-Treffer über 0.8 heißt: erst die gefundene
Stelle lesen und im Issue erklären, was diesmal anders ist.

## Übergabe an das Gate

Der Code-Agent übergibt an das Review, nicht direkt an das Gate (`docs/agents/code.md`):

1. Committen und pushen: neuer Hebel `git push -u origin HEAD`, sonst auf den Branch aus dem
   letzten `ref:`-Block (`git push origin HEAD:<ref>`).
2. Im Issue kommentieren, mit genau diesem Block am Ende (die Queue liest den neuesten):
   ```
   candidate: <slug>
   ref: <branch>
   ```
3. `gh issue edit <nr> --add-label needs-code-review --remove-label changes-requested --remove-label status:needs-review`

Erst die Freigabe des Review-Agents setzt `status:ready-to-test`; danach ändert niemand mehr etwas
am Issue, bis die Queue sich mit dem Ergebnis meldet.

## Nie

- Labels `status:queued` und `status:gate-passed` setzen oder entfernen; `status:blocked` entfernen
  (setzen ist erlaubt, wenn der Hebel aussichtslos ist — mit Begründung im Issue);
  `status:ready-to-test` setzt nur der Review-Agent
- `baselines/`, `scripts/gate_check.sh`, `scripts/ab_gate.py`, `scripts/parity_check.py`,
  `scripts/gate_thresholds.py` im Rahmen eines Hebels ändern (Gate-Änderungen sind ein eigenes
  Issue für Leon)
- PRs mergen, auf `main` pushen, `--no-verify` benutzen
- Engines starten oder stoppen: die GPUs gehören der Queue

## Gate-Bericht lesen

Der Kommentar der Queue enthält `RESULT.md`: Basis-SHA, Kandidaten-SHA, Paritätsergebnis je
Engine-Block und die A/B-Tabelle (Delta gegen Toleranz). Das vollständige Log liegt lokal unter
`/home/orca/RadianceMine/reports/<slug>_<zeit>/` (`run.log`, `gate/ab/summary.json`,
`gate/isa_diff.json`). Bei einem Fehlschlag zuerst feststellen, in welchem Schritt (`apply`,
`build`, `gate`) und bei welcher Metrik; `isa_diff.json` zeigt Kernel mit mehr VGPRs oder
neuen Spills.

## Orca-Automationen

Es gibt keinen eigenen Dispatcher-Dienst: Jede Rolle ist eine Orca-Automation mit neuem Worktree
pro Lauf (Basis `origin/main`, Setup baut `build_hip`). Orca startet den Agent nur, wenn der
Precheck Arbeit findet; `orca_agent.py` sucht dabei auch die Arbeit aus, wählt das Modell und
belegt einen der Slots.

| Automation | Precheck | Agent-Befehl | Intervall (Vorschlag) |
|---|---|---|---|
| Radiance: Plan | `python3 /home/orca/RadianceMine/scripts/orca_agent.py check plan` | `python3 /home/orca/RadianceMine/scripts/orca_agent.py run plan` | 15 min |
| Radiance: Code | `… check code` | `… run code` | 10 min |
| Radiance: Review | `… check review` | `… run review` | 10 min |
| Radiance: Research | `… check research` | `… run research` | 1 h (läuft höchstens alle 24 h) |
| Radiance: Audit | `… check audit` | `… run audit` | 1 h (läuft höchstens alle 12 h) |
| Radiance: Upstream | `… check upstream` | `… run upstream` | 1 h |

Code und Review dürfen mehrfach parallel laufen; dieselbe Automation nimmt nie dasselbe Issue
zweimal (Sperre pro Issue). Precheck: Exit 0 = Arbeit und freier Slot, 1 = nichts zu tun, 2 =
Precheck kaputt.

Ohne Orca (Test oder Notbetrieb): `bash scripts/create_worktree.sh <name>`, im Worktree
`python3 /home/orca/RadianceMine/scripts/orca_agent.py run <rolle>`.

## Modelle

`scripts/agents/models.json` (nur Leon ändert die Zuordnung):

| Rolle | Modell |
|---|---|
| plan | Opus (immer) |
| code | nach `tier:`: light → Gemini Flash (agy), medium → GLM (claude über Z.ai), heavy → Opus |
| review | eine Stufe über dem Code-Agent, höchstens heavy |
| research | Gemini Pro über agy (dort ist alphaXiv angemeldet) |
| audit | Opus |
| upstream | GLM |

Nach jedem Fehlschlag eines Issues (Gate-Lauf ohne PASS, Review mit Änderungswünschen, Lauf ohne
Übergabe) laufen code und review eine Stufe höher. GLM bekommt `ANTHROPIC_BASE_URL` und den
Schlüssel aus `~/.config/zai/api_key` nur im eigenen Prozess; für Opus-Läufe entfernt
`orca_agent.py` diese Variablen ausdrücklich. Ein Backend ohne Modellname, CLI oder Schlüssel ist
gesperrt; der Precheck sagt dann auf stderr, warum nichts startet.

## Grenzen

| Grenze | Wert | Durchgesetzt von |
|---|---|---|
| Agents gleichzeitig | 5 | Slots (`flock`) in `~/.local/state/radiance-agents/` |
| Review-Runden mit Änderungswünschen | 2, danach Freigabe oder `status:blocked` | review-Prompt, `orca_agent.py` |
| Plan-Überarbeitungen | 2 | `orca_agent.py` |
| Läufe einer Rolle ohne gültige Übergabe | 2 | `orca_agent.py` |
| Gate-Läufe ohne PASS | 3 | `gh_bridge.py` |
| offene, unerledigte Ideen | 8; darüber legen research und audit nichts an | `orca_agent.py` |
| Laufzeit pro Agent | je Rolle 45–120 min | `orca_agent.py` (beendet die Prozessgruppe) |
| Nutzungslimit eines Anbieters | 60 min Pause für dieses Backend, Lauf zählt nicht | `orca_agent.py` |

Zustand ansehen: `python3 scripts/orca_agent.py status` (freie Slots, gesperrte Backends, letzte
Läufe). Logs je Lauf: `~/.local/state/radiance-agents/logs/`.

Kommentare in Issues schreiben die Agents auf Deutsch.
