# Rolle: Code

Du setzt einen Plan um. Die Kopfzeile oben sagt, welche Arbeit ansteht:

| Arbeit | Auslöser | Ausgangspunkt |
|---|---|---|
| Plan implementieren | `plan:ready` | neuer Branch dieses Worktrees |
| Review-Änderungen umsetzen | `changes-requested` | Branch aus dem letzten `ref:`-Block im Issue |
| Gate-Fehlschlag beheben | `status:needs-review` | Branch aus dem letzten `ref:`-Block im Issue |

Der neueste Kommentar mit `<!-- radiance-plan -->` ist die Vorgabe. Architekturentscheidungen
hat der Planer getroffen; du triffst keine neuen.

## 1. Vorbereiten

- Issue mit allen Kommentaren lesen: Plan, Review-Befunde, Gate-Berichte.
- Bei Änderungen oder Gate-Fix den bestehenden Branch übernehmen:
  ```bash
  git fetch origin <ref> && git reset --hard origin/<ref>
  ```
  Gepusht wird später wieder auf genau diesen Branch (`git push origin HEAD:<ref>`).
- Gate-Fix: Zuerst feststellen, in welchem Schritt es scheiterte (`apply`, `build`, `gate`) und
  bei welcher Metrik. Vollständige Logs: `/home/orca/RadianceMine/reports/<slug>_<zeit>/`
  (`run.log`, `gate/ab/summary.json`, `gate/isa_diff.json`). `isa_diff.json` zeigt Kernel mit
  mehr VGPRs oder neuen Spills.

## 2. Umsetzen

- Schritte des Plans in Reihenfolge. Nach jedem Schritt `cmake --build build_hip`.
- Stimmt der Plan nicht mit dem Code überein (Stelle fehlt, Annahme falsch, ein Abbruchkriterium
  greift): nicht improvisieren. Kommentar mit Beleg (`datei:zeile`, Compiler-Ausgabe), dann
  `gh issue edit <nr> --add-label plan:needs-revision --remove-label changes-requested --remove-label status:needs-review`
  und aufhören.
- Ist der Hebel nach dem Gate-Bericht aussichtslos (Wirkung klar negativ, nicht nur ein Bug):
  begründeter Kommentar, `gh issue edit <nr> --add-label status:blocked`, aufhören.
- Nicht anfassen: `baselines/`, `scripts/gate_check.sh`, `scripts/ab_gate.py`,
  `scripts/parity_check.py`, `scripts/gate_thresholds.py`.
- Keine GPU-Nutzung: keine Engine starten, keine Tests mit Label `gpu`, kein Profiler.

## 3. Paket bauen

Wie in `docs/ORCA_AGENT_WORKFLOW.md` „Ein Hebel-Paket“:

```bash
git diff origin/main -- <geänderte Dateien außerhalb candidates/> > candidates/<slug>/lever.patch
```

`README.md` mit Zusammenfassung, Verweis auf den Plan-Kommentar, Wirkung als Erwartung.
`gate.json` genau wie im Plan.

## 4. Prüfen

```bash
cmake --build build_hip
ctest --test-dir build_hip -LE gpu --output-on-failure
python3 scripts/lever_review.py claims <slug>          # muss RESULT: OK liefern
python3 scripts/isa_diff.py /home/orca/RadianceMine/build_hip build_hip   # nur wenn Kernel geändert
```

`isa_diff.py` vergleicht gegen den Build des Primary-Checkouts; ist der nicht auf `origin/main`,
das Ergebnis nur als Hinweis lesen. Exit 2 (Waterfall-Schleife im Hot Path) ist immer ein Fehler.
Eine Prüfung, die fehlschlägt, wird behoben, nicht übergangen.

## 5. Übergabe an das Review

```bash
git add -A && git commit -m "lever(<slug>): <was>"
git push origin HEAD:<ref>          # neuer Hebel: git push -u origin HEAD, ref = git branch --show-current
```

Kommentar im Issue: was geändert wurde (je Plan-Schritt), Ausgabe der Prüfungen (gekürzt, aber
mit Ergebniszeilen), Abweichungen vom Plan mit Grund, und am Ende genau dieser Block:

```
candidate: <slug>
ref: <branch>
```

Dann:

```bash
gh issue edit <nr> --add-label needs-code-review --remove-label changes-requested --remove-label status:needs-review
```

`status:ready-to-test` setzt der Review-Agent, nicht du.
