# Orca-Agent-Workflow für RadianceMine

Diese Datei ist die Arbeitsanweisung für die Agents von RadianceMine. Sie gilt zusammen mit
`AGENTS.md`. Die Rollen-Prompts stehen in `docs/agents/<rolle>.md`; `scripts/orca_agent.py`
wählt Arbeit, Modell und Slot, startet jeden Agent in einem eigenen Worktree in Orca und prüft
die Übergabe.

## Wer entscheidet was

| Aufgabe | Wer | Wie |
|---|---|---|
| Ideen finden | Agents `research` (extern) und `audit` (eigener Code) | Issue mit `research:new-lever` |
| Idee annehmen oder verwerfen, Implementierungsplan, Stufe, Rückfragen beantworten | Agent `plan` (Opus, als einzige Rolle) | Plan-Kommentar, `plan:ready` + `tier:*` |
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
| `upstream:sync` | `upstream_sync.py` | Codeberg-main zusammenführen; läuft durch plan → code → review → Gate (`docs/UPSTREAM.md`) |
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
└── gate.json     optional: {"engine_args": ["--flag"], "engine_env": {"VAR": "1"},
                            "numerics": "bitexact" | "reordered"}   (AGENTS.md §3, Numerik)
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
cmake --build build_hip -j "$RADIANCE_BUILD_JOBS"                # baut der Patch? (Worktree-Setup hat build_hip schon angelegt)
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

## Start der Agents

Orca-Automationen nehmen nur einen Prompt und einen Provider; ein Modell pro Lauf oder einen
eigenen Befehl kennen sie nicht. Deshalb entscheidet ein deterministischer Tick ohne LLM, und Orca
stellt Worktree und Terminal, in dem der Agent sichtbar läuft:

```
systemd-Timer (alle 3 min) ─► orca_agent.py tick
    ├─ alte Agent-Worktrees ohne ungesicherte Arbeit entfernen (nach 12 h)
    └─ je Rolle mit Arbeit und freiem Slot:
         orca-ide worktree create --repo <id> --name agent-<rolle>-<issue>-<zeit> --setup skip
             (Basis origin/main laut Orca-Repo-Einstellung; erscheint in Orcas Seitenleiste)
         orca-ide terminal create --worktree id:<wt> --command "orca_agent.py run <rolle> --issue <nr>"
                └─► run: Slot + Issue sperren, Worktree bauen (code/review/audit),
                         EINE frische Agent-Session mit dem Modell der Stufe, Übergabe prüfen
```

Reihenfolge im Tick: review, code, plan, upstream, audit, research (laufende Arbeit vor neuer).
Auf epyc läuft Orca ohne Fenster (`orca-serve` unter xvfb); Terminals laufen dann im Hintergrund
und werden erst sichtbar, wenn ein Orca-Client verbunden ist (`orca-ide terminal focus`). Das Log
jedes Laufs liegt unabhängig davon unter `~/.local/state/radiance-agents/logs/`.
Installation: `scripts/systemd/radiance-agent-tick.{service,timer}`. Ohne Orca-Runtime:
`"launcher": "detached"` in `scripts/agents/models.json`, dann laufen die Agents als
Hintergrundprozesse (Log unter `~/.local/state/radiance-agents/logs/`).

Diagnose: `python3 scripts/orca_agent.py check <rolle>` zeigt, was der Tick jetzt starten würde;
`python3 scripts/orca_agent.py status` zeigt Slots, gesperrte Backends, letzte Läufe, offene Fragen.

## Kontext: frische Session, nur das Nötige

- Jeder Lauf ist ein neuer CLI-Prozess ohne Resume, also eine neue Session. Nichts wird zwischen
  Läufen im Modellkontext mitgenommen.
- Agents lesen nicht das ganze Issue. `run` hängt an den Rollen-Prompt einen Übergabe-Block mit
  genau dem, was die Rolle braucht:

| Rolle / Arbeit | Übergabe-Block |
|---|---|
| plan, neue Idee | Issue-Text |
| plan, Überarbeitung | Issue-Text, letzter Plan, alles seit dem letzten Plan |
| code, implementieren | Issue-Text, neuester Plan, Antworten auf Rückfragen |
| code, Review-Änderungen | dazu letzter Review-Kommentar und letzte eigene Übergabe |
| code, Gate-Fix | dazu letzter Gate-Bericht und letzte eigene Übergabe |
| review | Issue-Text, Plan, Übergabe des Code-Agents, vorige Review-Runde, Antworten |

- Dafür beginnen die Kommentare mit Markierungen: `<!-- radiance-plan -->` (Planer),
  `<!-- radiance-handoff -->` (Code), `<!-- radiance-review -->` (Review),
  `<!-- radiance-qa -->` (Rückfrage, schreibt `orca_agent.py`), `<!-- radiance-gate-result -->`
  (Queue). Was ohne Markierung im Issue steht, sieht kein Agent automatisch.

## Rückfragen

Code- und Review-Agents fragen den Planer, statt zu raten:

```bash
python3 /home/orca/RadianceMine/scripts/orca_agent.py ask "<frage>"
```

Der Befehl startet eine frische Opus-Session, die nur den Plan, frühere Rückfragen und die Frage
sieht und den Worktree des Fragenden lesen, aber nicht ändern darf. Die Antwort kommt als Ausgabe
des Befehls zurück (Wartezeit bis 4 min, danach `orca_agent.py answer <id>`), der fragende Agent
arbeitet in derselben Session weiter. Frage und Antwort landen im Issue und stehen beim nächsten
Lauf im Übergabe-Block. Beginnt die Antwort mit `PLAN-FEHLER:`, setzt der Fragende
`plan:needs-revision`.

Orcas eigene Orchestration (`orca orchestration ask`) schickt Fragen an einen Coordinator, der
selbst ein Agent sein müsste, und ist experimentell. `ask` erreicht dasselbe ohne dauerhaft
laufenden Coordinator.

## Modelle

`scripts/agents/models.json` (nur Leon ändert die Zuordnung). Opus nur für das Planen; alles
andere läuft auf Gemini und GLM, Opus springt bei Code erst nach mehreren Fehlschlägen ein:

| Stufe | Backend |
|---|---|
| light | Gemini Flash 3.8 (agy) |
| medium | Gemini Flash 3.8 (agy); eigene Stufe für ein späteres Gemini 4 |
| heavy | GLM 5.3 (claude über Z.ai) |
| fallback | Opus |

| Rolle | Modell |
|---|---|
| plan, Antworten auf Rückfragen | Opus |
| code | nach `tier:` des Planers; nach jedem Fehlschlag das nächststärkere Modell (Gemini → GLM → Opus) |
| review | das nächststärkere Modell über dem Code-Agent, höchstens GLM |
| research, upstream | Gemini Flash 3.8 (alphaXiv ist in Antigravity angemeldet) |
| audit | GLM |

Ein Eskalationsschritt wechselt immer das Modell: Stufen mit demselben Backend wie die Stufe
darunter werden übersprungen. Deshalb geht `light` nach einem Fehlschlag direkt auf GLM, und das
Review läuft nie auf dem Modell des Code-Agents (außer bei GLM-Code, wo GLM die Obergrenze ist).
Gemini Pro (3.1) wird bewusst nicht genutzt; bei Gemini 4 nur den Modellnamen im Backend `gemini`
tauschen oder ein eigenes Backend für `medium` eintragen.

Fehlschlag eines Issues: Gate-Lauf ohne PASS, Review mit Änderungswünschen, Lauf ohne Übergabe.
Ist ein Backend gesperrt (kein Modellname, keine CLI, kein Schlüssel, Nutzungslimit), weicht
die Rolle auf die nächsthöhere Stufe aus, aber nie deswegen auf Opus
(`"availability_fallback": false`). GLM bekommt `ANTHROPIC_BASE_URL` und den Schlüssel aus
`~/.config/zai/api_key` nur im eigenen Prozess; für Opus-Läufe entfernt `orca_agent.py` diese
Variablen ausdrücklich.

## Ziel: weiter, bis es erreicht ist

Leon setzt das Ziel in `baselines/targets.json`: einen BetterBench-Gesamtscore und/oder Mindest-
und Höchstwerte einzelner Metriken (`scripts/goal.py`). Die Lever-Queue misst jeden neuen `main`,
wenn sie frei ist (`lever_queue.py run --auto-profile`), mit demselben BetterBench wie das Gate,
und trägt das Ergebnis in `reports/goal_status.json` und das Issue mit Label `goal:status` ein.

- Solange das Ziel gesetzt und nicht erreicht ist, halten research und audit die Pipeline gefüllt
  (Abstand 2 h statt 24/12 h, begrenzt durch die offenen Ideen). Planer, research und audit
  bekommen den Zielstand in den Prompt und richten sich nach dem Teil des Scores, in dem die
  meisten Punkte fehlen.
- Erreicht ist das Ziel erst, wenn zwei Messungen von `main` hintereinander es erfüllen; die erste
  Erfüllung löst eine zweite Messung desselben `main` aus.
- Danach legen research und audit nichts mehr an; was schon in der Pipeline ist, läuft zu Ende.
  Fällt ein späterer `main` unter das Ziel oder hebt Leon es an, geht es automatisch weiter.

## Grenzen

| Grenze | Wert | Durchgesetzt von |
|---|---|---|
| Agents gleichzeitig | 5 (Rückfrage-Sessions zählen nicht) | Slots (`flock`) in `~/.local/state/radiance-agents/` |
| Review-Runden mit Änderungswünschen | 2, danach Freigabe oder `status:blocked` | review-Prompt, `orca_agent.py` |
| Plan-Überarbeitungen | 2 | `orca_agent.py` |
| Läufe einer Rolle ohne gültige Übergabe | 2 | `orca_agent.py` |
| Rückfragen pro Lauf | 3 | `orca_agent.py ask` |
| Gate-Läufe ohne PASS | 3 | `gh_bridge.py` |
| offene, unerledigte Ideen | 8; darüber legen research und audit nichts an | `orca_agent.py` |
| Abstand zwischen research- bzw. audit-Läufen | 2 h, solange ein Ziel gesetzt und nicht erreicht ist; ohne Ziel 24 h bzw. 12 h; bei erreichtem Ziel keine | `orca_agent.py` |
| Laufzeit pro Agent | je Rolle 45–120 min, Antwort 8 min | `orca_agent.py` (beendet die Prozessgruppe) |
| Nutzungslimit eines Anbieters | 60 min Pause für dieses Backend, Lauf zählt nicht | `orca_agent.py` |

Kommentare in Issues schreiben die Agents auf Deutsch.
