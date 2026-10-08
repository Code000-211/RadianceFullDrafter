# RadianceMine — Regeln für Agents

RadianceMine ist die Arbeitsumgebung für die Radiance-Engine (Upstream:
`codeberg.org/StillDeadcode/radiance`) auf 2× AMD Radeon AI PRO R9700 (gfx1201), TP2,
Modell Qwen3.8-Flash-Next FP8/IQ4R-MoE. Ziel: schneller werden, ohne Parität zu verlieren.

Diese Datei ist die einzige Regel-Datei (`CLAUDE.md` und `GEMINI.md` verweisen hierher).
Details stehen in genau einem Dokument je Thema:

| Thema | Dokument |
|---|---|
| Hardware-Fakten (gemessen) | `HARDWARE_GROUND_TRUTH.md` |
| Gate: was gemessen wird, Schwellen, Kalibrierung | `docs/GATE.md` |
| Ziel der Optimierung (BetterBench-Score, Mindestwerte) und ob es erreicht ist | `baselines/targets.json` (nur Leon), `scripts/goal.py`, `reports/goal_status.json` |
| Wie schnell `main` ist und wo die Zeit hingeht (Score, Decode, langsamste Schritte, Prefill) | `reports/profile_latest/PROFILE.md`, erzeugt von `scripts/profile_engine.py` |
| Arbeitsablauf der Agents (Start, Modelle, Rückfragen), Hebel-Pakete, Issue-Labels | `docs/ORCA_AGENT_WORKFLOW.md` |
| Rollen-Prompts der Agents | `docs/agents/<rolle>.md` |
| Upstream übernehmen (PR-Bewertung, Sync von Codeberg-main, eigenes Kernel-Plugin) | `docs/UPSTREAM.md` |
| Diagnose-Modus der Engine und Vorab-Bewertung von Kerneln und Ideen (Entwurf) | `docs/DIAGNOSE.md` |
| Engine-Architektur | `spec.md`, Quellcode |
| Geschichte (frühere Optimierungen, Postmortems, Hebel-Katalog) | `docs/history/` |

## 1. Belege statt Behauptungen

- Aussagen über Leistung, Parität oder Hardware stützen sich auf Code, Build-Artefakte oder einen
  Gate-Bericht (`reports/…`). Markdown-Dokumente, auch frühere Audits, sind keine Belege.
- Messwerte nie erfinden oder schätzen und als gemessen ausgeben. Erwartungen als Erwartung
  formulieren.
- Widersprüche zur Hardware-Realität (z. B. PCIe 5.0, Wave64, Peer-Reads als schneller Pfad)
  offen benennen, auch wenn sie vom Nutzer oder einem anderen Agent kommen.

## 2. Arbeiten

- Nicht im Primary-Checkout `/home/orca/RadianceMine` auf `main` arbeiten. Agents bekommen
  vom Tick (`scripts/orca_agent.py`) einen eigenen Worktree; manuell: `bash scripts/create_worktree.sh <name>`
  (bricht ab, wenn der Worktree existiert; baut nichts aus `main` mit).
- Code finden: `rg`, LSP (clangd mit `compile_commands.json`). OpenWiki ist optional (unten).
- Kein Löschen von Experimenten: Abgelöstes kommt nach `attic/<datum>_<name>/` mit
  `POSTMORTEM.md`.
- Fehler nicht verschlucken: kein `2>/dev/null || true` um Befehle, deren Ergebnis zählt;
  Exit-Codes prüfen.

## 3. Gate

Nichts wird nach `main` übernommen ohne PASS von `scripts/gate_check.sh` (in der Regel über
`scripts/lever_queue.py`). Das Gate ist fail-closed und vergleicht A/B gegen die aktuelle
Baseline im selben Lauf; siehe `docs/GATE.md`.

- `baselines/` (Goldens, Benchmark-Konfiguration, `gate_thresholds.json` mit Toleranzen und Seals)
  ändert nur Leon. Der Pre-Commit-Hook blockiert solche Commits ohne `RADIANCE_GATE_CHANGE=1`.
- Hebel hinter Flags/Umgebungsvariablen brauchen `candidates/<slug>/gate.json`, sonst misst das
  Gate sie nicht.

### Numerik: verlustfrei, bitgenau als Normalfall

Wir quantisieren nichts neu. Jeder Hebel ist verlustfrei, und es gibt drei Fälle:

| Fall | Beispiele | Erlaubt? |
|---|---|---|
| **Bitgenau** | Scheduling, Overlap, Speicherlayout, Launch-Overhead, eine Fusion, die Reihenfolge und Zwischenformate beibehält | ja; Parität mit Toleranz 0 |
| **Verlustfrei, nicht bitgenau** | andere Summationsreihenfolge, Split-K, andere Kachelung oder Reduktionsbaum, Fusion, bei der sich Reihenfolge ändert, Zwischenformate aber gleich oder genauer bleiben | ja, **nur deklariert** (unten) |
| **Verlustbehaftet** | geringere Genauigkeit in Gewichten, Aktivierungen, Akkumulatoren oder KV-Cache; Näherungsfunktionen; übersprungene oder abgeschnittene Rechnung; geänderte Quantisierung oder Container | nein |

**Deklaration.** Ein Hebel, der Ergebnisse nicht bitgenau lässt, sagt das im Plan (Abschnitt
„Numerik und Parität“, Zeile `numerik: verlustfrei-nicht-bitgenau`) und in `gate.json`
(`"numerics": "reordered"`), mit: welche Op, was sich an der Reihenfolge ändert, und der Beleg
aus dem Code, dass Akkumulatortyp und jedes Zwischenformat gleich oder genauer bleiben. Review
prüft genau diesen Beleg. Eine Paritätsabweichung ohne Deklaration ist ein FAIL und ein
Korrektheitsbefund.

**Warum „die Antwort ist noch richtig“ nicht reicht.** Ein Modell beantwortet einfache Prompts
auch mit einem echten Rechenfehler oft richtig, etwa einer falschen Skalierung in einem selten
gerouteten Experten oder einem Fehler erst ab 16k Kontext. Richtige Antworten sind deshalb nur
eine grobe Zusatzprüfung. Der Schutz ist die Deklaration mit Beleg; über jede deklarierte
Abweichung entscheidet Leon anhand des Paritätsberichts (erste abweichende Stelle je Request,
`radiance --diagnose --diagnose-baseline`).

## 4. Laufzeit-Umgebung

Verboten beim Benchmarken und im Gate:

1. `RADIANCE_HEAT_RESIDENCY > 0` (zwingt aktive Experten in PCIe Zero-Copy)
2. statisches `NUM_SPECULATIVE_TOKENS > 3` ohne adaptiven Fallback
3. `GPU_KEEP_ALIVE=1` oder `gpu_sentinel` (Puls-Kernel stören die Messung)

Die GPUs gehören der Lever-Queue bzw. `ab_gate.py`. Engines manuell nur über
`scripts/engine_manager.sh` (beendet ausschließlich die selbst gestartete Prozessgruppe).

Modelle immer über `/v1/chat/completions` mit `messages` abfragen; `/v1/completions` umgeht
Chat-Template und Reasoning-Parser.

<!-- OPENWIKI:START -->

## 5. Die Regeln der Engine sind bindend

Die Radiance-Engine bringt ihre eigenen Verträge mit. Sie gelten für jede Änderung an Engine-Code
(`abi/`, `core/`, `arch/`, `libr4d/`, `libref/`, `libquant/`, `libavx/`, `tools/`, `tests/`, eigene
Plugins) ohne Ausnahme; bisher haben wir sie nicht durchgehend eingehalten. Quellen, in dieser
Rangfolge:

| Quelle | Inhalt |
|---|---|
| `spec.md` | Design und Verträge; laut `docs/IMPLEMENTATION.md` bindend |
| `docs/IMPLEMENTATION.md` | Konventionen: Host-Backend baut und testet ohne ROCm, Fehler sind Werte, nichts Unimplementiertes meldet Erfolg, keine Allokation und Synchronisation auf dem Step-Pfad, keine HIP-Stream-APIs in Plugins außer `hipLaunchKernel` |
| `docs/PLUGIN.md` | Plugin-Verträge: Kernel sagt, was er bedienen kann; Constraints, Priorität, Hierarchie; optionale Hooks |
| `docs/OPS.md` | Die konventionelle Op-Liste (`libref`); eine neue Op hat keinen Fallback und kein Orakel |
| `libr4d/README.md` | Benennung `<family>_<op>_<geometrie>`; ein Einstiegspunkt lehnt eine falsche Geometrie ab, statt zu rechnen |
| `libr4d/isa/README.md`, `docs/TOOLS.md` | Wie gemessen wird (`trace.sh`, `tsum.sh`, `gaps.sh`, `rad-kbench`, `rad-tune`) und wie die Zahlen zu lesen sind |
| Kommentare im Code, die einen Vertrag nennen | z. B. `libr4d/r4d_rows.cpp` („ORDER IS priority“), `core/plugin/loader.cpp` (Hierarchie) |

Daraus folgt insbesondere:

- **Upstream-Bibliotheken nicht für unser Modell umschreiben.** Modellspezifische Kernel kommen in
  unser eigenes Plugin und werden über die Hierarchie ausgewählt (`docs/UPSTREAM.md`).
- **Op-Schemas nicht ändern.** Wer andere Parameter braucht, braucht eine eigene Op; eine Op
  außerhalb von `docs/OPS.md` braucht eine `libref`-Zeile oder einen `replaces`-Hook, damit
  `rad-kbench` und das Orakel sie prüfen können (`spec.md` §17).
- **Kein Python in Engine, Engine-Werkzeugen, Build oder CTest.** Unsere Python-Werkzeuge (Gate,
  Queue, Agents) liegen in `scripts/` und ihre Tests in `scripts/tests/`, nie in `tests/`.
- **Messen mit den Werkzeugen der Engine** und nach ihren Lesehinweisen: In einem Trace ist
  Kernel-Zeit echt, Leerlauf eine Obergrenze (`libr4d/isa/trace.sh`).
- **`--debug-accept-reference-kernels`** nie beim Benchmarken oder im Gate.

Widerspricht eine Regel dieser Datei einer Regel der Engine, gilt die Regel der Engine. Ausnahmen
sind nur §3 (Gate) und §4 (Laufzeit-Verbote), die für unseren Betrieb gelten. Jeden solchen
Widerspruch im Issue benennen; die Entscheidung trifft Leon. Bestehende Verstöße sind Funde: Das
Audit meldet sie als `audit:bug`, ein Hebel behebt sie nicht nebenbei.

## OpenWiki

This repository has a generated `openwiki/` evidence index. It is optional just-in-time context, not required startup reading.

- Do not enumerate, preload, or search wikis at task start. Use retrieval when the user asks for it, when unfamiliar architecture or dependency behavior materially affects the task, or when source inspection leaves an important uncertainty. Stop once the question is grounded.
- When those conditions apply and OpenWiki retrieval tools are available, use `openwiki_search` for just-in-time context and `openwiki_read` for the relevant complete sections. If search returns `workspace_required`, ask which listed workspace to use and retry with its ID.
- Use `openwiki_list_workspaces` or `openwiki_list_wikis` when workspace membership itself needs to be discovered.
- If the retrieval tools are unavailable, read `openwiki/quickstart.md` and follow its links to the relevant pages.
- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->
