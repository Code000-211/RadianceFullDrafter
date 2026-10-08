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
| Arbeitsablauf der Orca-Automationen, Hebel-Pakete, Issue-Labels | `docs/ORCA_AGENT_WORKFLOW.md` |
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

- Nicht im Primary-Checkout `/home/orca/RadianceMine` auf `main` arbeiten. Orca-Automationen
  bekommen einen eigenen Worktree; manuell: `bash scripts/create_worktree.sh <name>`
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
