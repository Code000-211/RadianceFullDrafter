# Master Gate

Ein Kandidat (Hebel) gilt als besser, wenn er im **selben Lauf** gegen die aktuelle Baseline
gemessen wurde und dabei nicht schlechter abschneidet. Gespeicherte Baseline-Zahlen von früher
werden nicht verwendet: Sie waren am 2026-10-08 nicht reproduzierbar (Decode −7 %, C8 −16 %
gegenüber `baseline_opt146.json` bei unverändertem Code).

```
bash scripts/gate_check.sh --build-dir <kandidat>/build_hip [--candidate-root <kandidat>] \
     [--baseline-build-dir <baseline>/build_hip] [--abba] \
     [--candidate-arg <engine-flag>]... [--candidate-env KEY=VALUE]...
```

Im Normalfall ruft `scripts/lever_queue.py` das Gate auf (siehe `docs/ORCA_AGENT_WORKFLOW.md`).

## Stufen

| Stufe | Skript | Prüft | Fail-closed |
|---|---|---|---|
| Tier 0 | `check_epistemic_invariants.py --repo-root <kandidat>` | Operatoren haben ELF-Symbole, keine stillen Test-Skips, Seals in `baselines/gate_thresholds.json` stimmen, keine verschluckten Fehler in Gate-Skripten | ja |
| Tier 3 | `isa_diff.py <baseline> <kandidat>` | Bericht: Kernel mit mehr VGPRs, weniger Waves, neuen Spills. Harte Regel nur: keine neuen `v_movrel`-Waterfall-Loops im Hot-Path | nur Waterfall |
| Tier 1 + 2 | `ab_gate.py` | je Block eigene Engine; Parität (Golden-Hashes, Toleranz 0) in jedem Block; BetterBench single-stream + C8 + Prefill mit Zufalls-Nonces; Kandidat gegen Baseline je Metrik innerhalb `tier2.slack_pct` | ja |
| Tier 4 | `ab_gate.py` (nach den Blöcken, nur wenn bis dahin PASS) | `radiance --diagnose` zweimal mit der Baseline und einmal mit dem Kandidaten; zweiter Baseline-Lauf und Kandidat werden je gegen den ersten verglichen: gleiche Prompts (BetterBench-Korpus, sonst der eingebaute), gleiche Seeds, Temperatur 1; Kategorien, Concurrency 1–8, Prefill bis 60k. Die Engine ist zwischen zwei Prozessen nicht bitgenau reproduzierbar (spec §19.7), deshalb gilt Token-Parität nur für Requests, die die Baseline gegen sich selbst reproduziert, und ein Annahme-Einbruch nur dort, wo die Baseline gegen sich selbst keinen zeigt. `DROPPED` scheitert immer; abweichende reproduzierbare Tokens scheitern, außer der Kandidat deklariert `"numerics": "reordered"` (dann PASS mit Vermerk, Leon entscheidet beim Merge) | ja |

Reihenfolge der Blöcke: `A, B` (Standard) oder `A, B, B, A` (`--abba`, zusätzlich A/A-Streuung;
ist sie größer als die Toleranz, ist das Ergebnis INCONCLUSIVE und das Gate scheitert).
Ein Lauf dauert mit A/B etwa 10 Minuten.

Ergebnisse: `<out>/ab/report.md` (Tabelle), `<out>/ab/summary.json` (alle Blöcke mit
Binary-SHA256, Startzeit, MCLK-Anteil, Parität, Metriken), `<out>/isa_diff.json`.

Exit-Codes von `ab_gate.py`: 0 PASS; 2 Kandidat scheitert (Parität, Speed, Diagnose, oder seine
Engine startet nicht — der Bericht enthält dann das Ende des Engine-Logs); 3 Setup-Fehler/Inconclusive
(GPUs belegt, Baseline-Engine startet nicht, Baseline verfehlt selbst die Parität → Goldens veraltet,
Diagnose-Lauf der Baseline ist keine Messung).

Tier 4 liest seine Einstellungen aus einem optionalen Abschnitt `"diagnose"` in
`baselines/gate_thresholds.json` (`enabled`, `tokens`, `runs`, `concurrency`, `prefill`,
`timeout_s`); fehlt er, gelten die Defaults in `ab_gate.py` (`DIAGNOSE_DEFAULTS`). `--no-diagnose`
überspringt die Stufe für einen einzelnen Lauf. Ergebnisse: `<out>/ab/diagnose_baseline/`,
`<out>/ab/diagnose_baseline_again/`, `<out>/ab/diagnose_candidate/` (je `diagnose.md`,
`diagnose.json`, `engine.log`) und der Abschnitt „Tier 4“ in `report.md` mit der Abdeckung (wie
viele Requests die Baseline reproduziert). Ein Diagnose-Lauf dauerte auf epyc 336 s (BetterBench-
Korpus, 3 Läufe je Punkt, Prefill bis 16k); Tier 4 kostet also etwa das Dreifache davon.

## Einstellungen

Alles steht in `baselines/gate_thresholds.json`; Commits, die `baselines/` ändern, blockiert der
Pre-Commit-Hook ohne `RADIANCE_GATE_CHANGE=1`. Die Benchmark-Konfiguration ist
`baselines/bench_config.json` (dieselbe wie bei der Opt-146-Messung) und ebenfalls versiegelt.

## Kalibrierung

Die Toleranzen müssen die Streuung zwischen zwei Engine-Starts desselben Binaries abdecken.
Gemessen mit `ab_gate.py --baseline-build build_hip --candidate-build build_hip --abba`:

A/A-Kalibrierung vom 2026-10-08 (4 Engine-Starts desselben Binaries `f887b255`, Konfiguration
`bench_config.json`, MCLK in allen Blöcken zu 95–97 % auf der höchsten Stufe):

| Metrik | Block 1 | Block 2 | Block 3 | Block 4 | größte Differenz zweier Starts | Toleranz |
|---|---|---|---|---|---|---|
| Decode (Median, tok/s) | 197,6 | 191,1 | 191,6 | 192,6 | 3,4 % | 4 % |
| C8 (tok/s) | 429,4 | 435,5 | 397,0 | 428,3 | 9,7 % | 10 % |
| Prefill 47k (tok/s) | 3960 | 3986 | 3984 | 3981 | 0,7 % | 2 % |
| C1 ITL P99 (ms) | 9,18 | 9,34 | 9,05 | 9,12 | 3,2 % | 4 % |
| C8 ITL P99 (ms) | 18,37 | 18,68 | 18,10 | 18,24 | 3,2 % | 4 % |
| TTFT P50 (ms) | 86,15 | 85,87 | 86,40 | 86,32 | 0,6 % | 2 % |

Folgen:

- Das A/B-Gate erkennt Verschlechterungen ab etwa 4 % (Decode) bzw. 10 % (C8). Kleinere
  Effekte sind mit einem A/B-Paar nicht von der Streuung zu unterscheiden; dafür `--abba`
  verwenden oder den Hebel mehrfach messen.
- C8 streut am stärksten, weil `bench_config.json` nur 16 Requests misst. Mit 48 Requests
  (BetterBench-Standard) sollte die Streuung deutlich sinken, kostet ~40 s je Block; danach
  neu kalibrieren.
- Vier Starts sind eine kleine Stichprobe. Wenn das Gate Kandidaten ohne Codeänderung an der
  betroffenen Stelle ablehnt, ist die Toleranz zu knapp: neu kalibrieren statt Toleranz raten.
- Die Parität war in allen Blöcken bit-identisch. Der erste Paritätslauf nach jedem Start wird
  als Aufwärmlauf verworfen (kalte Engine, Clocks und Experten-Cache noch nicht warm).
