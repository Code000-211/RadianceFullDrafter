# Orca-Agent-Workflow für RadianceMine

Diese Datei ist die Arbeitsanweisung für Agents, die von Orca-Automationen gestartet werden.
Sie gilt zusammen mit `AGENTS.md`.

## Wer entscheidet was

| Aufgabe | Wer | Wie |
|---|---|---|
| Hebel erfinden, Patch schreiben, Fehlschlag analysieren, Upstream-PR bewerten | Agent (Orca-Automation) | in einem eigenen Orca-Worktree, Ergebnis als Branch + Issue-Kommentar |
| Bauen, Parität prüfen, A/B messen, PASS/FAIL | `scripts/lever_queue.py` (systemd-Dienst `radiance-lever-queue`) | deterministisch, mit den Skripten des Primary-Checkouts `/home/orca/RadianceMine` |
| Gate-Ergebnis ins Issue schreiben, Labels `queued`/`gate-passed`/`needs-review`/`blocked`, PR öffnen | `scripts/gh_bridge.py` | nur dieser Code setzt diese Labels |
| Hebel aufgeben (`status:blocked` setzen, mit Begründung im Issue) | Agent oder Queue | |
| PR mergen, `status:blocked` aufheben, Gate-Einstellungen ändern | Leon | |

Ein Agent kann kein PASS erzeugen: Das Gate läuft immer mit den Skripten und Schwellen des
Primary-Checkouts `/home/orca/RadianceMine` (Branch `main`); Änderungen an `scripts/` oder
`baselines/` auf einem Agent-Branch wirken sich auf den Test des eigenen Hebels nicht aus.
Nach einem Merge auf GitHub den Primary-Checkout mit `git pull --ff-only` nachziehen.

## Zustände eines Hebel-Issues

```
research:new-lever ──(Agent "Neue Hebel")──► status:ready-to-test
status:ready-to-test ──(Queue)──► status:queued ──► status:gate-passed  (PR offen, Leon merged)
                                              └──► status:needs-review ──(Agent "Lever-Fix")──► status:ready-to-test
nach 3 Gate-Läufen ohne PASS, oder Agent hält den Hebel für aussichtslos ──► status:blocked (nur Leon hebt das auf)
```

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

1. Committen und den Worktree-Branch pushen: `git push -u origin HEAD` (Name merken: `git branch --show-current`)
2. Im Issue kommentieren (genau dieser Block, die Queue liest den neuesten):
   ```
   candidate: <slug>
   ref: <ausgabe von git branch --show-current>
   ```
3. Label setzen: `gh issue edit <nr> --add-label status:ready-to-test --remove-label status:needs-review`

Danach nichts mehr am Issue ändern; die Queue meldet sich mit dem Ergebnis.

## Nie

- Labels `status:queued` und `status:gate-passed` setzen oder entfernen; `status:blocked` entfernen
  (setzen ist erlaubt, wenn der Hebel aussichtslos ist — mit Begründung im Issue)
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

## Die drei Orca-Automationen

Alle laufen mit `claude` in einem neuen Worktree pro Lauf (Basis `origin/main`, Setup baut
`build_hip`) und starten nur, wenn ihr Precheck Arbeit findet:

| Automation | Precheck | Aufgabe |
|---|---|---|
| Radiance: Lever-Fix | `orca_precheck.py needs-review` | ältestes `status:needs-review`-Issue mit Gate-Kommentar der Queue: Ursache aus dem Gate-Bericht bestimmen, Patch korrigieren und erneut übergeben, oder begründet aufgeben |
| Radiance: Neue Hebel | `orca_precheck.py new-lever` | ältestes `research:new-lever`-Issue ohne Status: Idee prüfen (`similar`, Hardware), Hebel-Paket bauen und übergeben, oder begründet ablehnen |
| Radiance: Upstream-Bewertung | `orca_precheck.py upstream` | bis zu 3 Upstream-PRs aus `REVIEW.md` ohne Bewertung: Diff lesen, gegen unseren Stand prüfen, Bewertung per `watch_upstream.py --assess` hinterlegen. Nichts anwenden, keine Issues |

Kommentare in Issues schreiben die Agents auf Deutsch.
