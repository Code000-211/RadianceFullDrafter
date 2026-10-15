# HANDOFF: RadianceFullDrafter

Stand: 2026-10-15. Dieses Dokument ist der Einstieg für die Weiterarbeit in diesem Repo. Aussagen sind mit Quelle
oder Messdatei belegt; was nicht belegt ist, steht als **[INFERENCE]** oder unter "Offen".

## 1. Was dieses Repo ist

- Repo: `github.com/OoguroRyuuya/RadianceFullDrafter` (privat), `main` = Commit `51248ae`.
- Lokal: `/home/orca/FullDrafter` (sauberer Klon, gebaut mit `cmake -B build_hip -G Ninja -DCMAKE_BUILD_TYPE=Release
  -DRAD_WITH_HIP=ON -DRAD_GPU_TARGETS=gfx1201 -DRAD_BUILD_TESTS=ON`; `ninja -C build_hip` dauert ca. 140 s, Exit 0).
  `/home/orca/RadianceFullDrafter` ist ein älterer, identischer Klon und kann gelöscht werden.
- Basis: `RadianceMine/main` (`f170dff`, nativer MTP) plus ein Commit mit dem FullDrafter (120 Dateien, +33.399 Zeilen).
  Auf `RadianceMine/main` gibt es keinen FullDrafter-Code. **`main` dieses Repos ist nicht gegen den MTP-Standard
  gemessen und nicht durch `scripts/gate_check.sh` gelaufen.**
- Hardware und Modell: 2x AMD Radeon AI PRO R9700 (gfx1201), TP2, `qwen4exp` (Qwen3.8-Flash-Next FP8/IQ4R-MoE).
  Die Karten laufen aktuell mit 210 W (`power1_cap`). Regeln: `AGENTS.md` (gilt weiter, besonders §3 Gate, §4 Laufzeit).

## 2. Der FullDrafter in einem Absatz

ALoDLM-Drafter mit DLoop "2x4": Stufe 1 schlägt 4 Token vor (Slots 0..3). Übersteigt das Überlebensprodukt der
Konfidenz die Schwelle `RADIANCE_DLOOP_THETA` (Default 0,20), läuft Stufe 2 und liefert 4 weitere (Slots 4..7).
Überspringt der Kernel Stufe 2, schreibt er `SENTINEL_ID` in die Slots 4..11. Die Engine reicht dann nur 4 Token zur
Verifikation, sonst 8 (`libr4d/r4d_fulldrafter.hip:1026-1034, 4321-4328`; `core/engine_draft.cpp:525`;
`core/sched/scheduler.h:105-120`, `core/sched/draft.h:42-49`). **Es gibt keine feste Tiefe 3.** `K=12` ist nur die
Puffergröße, die das Plugin deklariert (`arch/qwen4exp_fp8/qwen4exp_fp8.cpp`).

## 3. Starten, belegtes Rezept

Skript: `scripts/fulldrafter_bench.sh` (startet die Engine, fährt BetterBench Single-Stream, stoppt sie wieder, mit
absoluten Pfaden und Exit-Codes). Die Umgebung darin ist die belegte:

```
HIP_VISIBLE_DEVICES=0,1  NUM_SPECULATIVE_TOKENS=12  ROCM_PATH=/opt/rocm
GPU_HEADROOM_MIB=384     VRAM_KV_MIB=1400
RADIANCE_FULLDRAFTER=1   RADIANCE_TEACHER_TAPS=0   RADIANCE_GDN_ANCHOR=1
RADIANCE_FULLDRAFTER_SIDECAR=/home/orca/drafter_data/checkpoints/flash_next_k12_alodlm_v2/drafter_final.safetensors
RADIANCE_TEACHER_MATRICES=/home/orca/drafter_data/teacher/teacher-matrices.safetensors
```

Engine immer über `scripts/engine_manager.sh start --build-dir <abs> --port 8002 --timeout 900` und
`scripts/engine_manager.sh stop` (stoppt nur die selbst gestartete Prozessgruppe).

**Fallen, alle selbst erlebt:**
- `engine_manager.sh` startet ohne `--port` auf **8000**, nicht 8002. Das erste Smoke-Skript lief deshalb ins Leere.
- `engine_manager.sh` reicht keine zusätzlichen Engine-Argumente durch (nur Env). `--profile-ops` ist so nicht erreichbar.
- Ein EXIT-Trap mit relativem Pfad scheitert nach einem `cd` und lässt die Engine auf den GPUs stehen.
- **Mit den Defaults von `start_engine.sh` (Headroom 96 MiB) stürzte die Engine nach der Kategorie `prose` ab:**
  `HSA_STATUS_ERROR_MEMORY_APERTURE_VIOLATION` auf beiden Karten, danach `request refused: the engine stopped on an
  error`. Der Engine-Log dieses Laufs ist vom nächsten Start überschrieben worden. Erhalten ist der Bericht
  `reports/betterbench_2x4_project_51248ae_20261015_130046.json` (`reasoning` und `summarization` ohne Ergebnis:
  "no content chunks received", dann "Connection refused"). Beim Start meldete der Log: Karte 1 hat nach dem Budget nur
  16,65 MiB frei. Mit `GPU_HEADROOM_MIB=384`, `VRAM_KV_MIB=1400` liefen alle 8 Kategorien fehlerfrei.
  Dass der Headroom die Ursache ist, ist **[INFERENCE]**. Gemessen ist nur: Defaults = Absturz, 384/1400 = kein Absturz,
  je ein Lauf.
- Beide Karten müssen frei sein (`ls /sys/class/kfd/kfd/proc` leer). Nie zwei Engines oder Trainingsläufe gleichzeitig.
- `/home` gehört root, `orca` hat kein sudo. Projekte liegen unter `/home/orca`.

## 4. Messwerte (belegt, Einzelläufe, 210 W, BetterBench 0.6.1, Temperatur 0,7, 1 Warmup + 1 Pass)

Lauf in diesem Repo, Build `51248ae`, Sidecar `drafter_final` (Step 280000), Headroom 384:
`reports/betterbench_2x4_project_51248ae_hr384_20261015_130515.json` (lokal, `reports/` ist gitignoriert).

| Kategorie | decode tok/s | tok/update |
|---|--:|--:|
| chat | 92,6 | 1,67 |
| code | 167,8 | 3,43 |
| file_edit | 169,5 | 3,57 |
| json | 168,5 | 3,64 |
| math | 197,5 | 4,31 |
| prose | 97,2 | 1,72 |
| reasoning | 127,4 | 2,50 |
| summarization | 103,5 | 1,89 |
| **gewichteter Median (BetterBench "Combined")** | **143,0** | |

Referenz aus dem `speed-opt`-Worktree (Step-240000-Checkpoint, 210 W):
`/home/orca/RadianceMine/reports/betterbench_2x4_rank1cs.json`: Mittel 140,21, gewichteter Median 140,46 tok/s;
Vorgänger `betterbench_2x4_wave4_final.json`: 134,12. Der neue Lauf liegt damit im Bereich der Referenz. Mit je 1 Pass
ist der Unterschied von ca. 2 % nicht belastbar (das Gate rechnet mit 4 % Toleranz bei Decode).

Nicht vergleichbare Zahlen im Umlauf: `betterbench_2x4_wave3_wht6_hr96.json` (678 tok/s, Messfehler durch eine
Token-Schleife); `tap_record/TEST_READY.md` ("150 tok/s zertifiziert", belegt nur durch Mock-Läufe mit `dry_run: true`);
`DRAFTER_AGENT_HANDOFF.md` (186 tok/s, Projektion). Nichts davon ist eine Messung.

## 5. Was im Code ist (Hebel, geprüft per grep)

| Hebel | Stelle |
|---|---|
| dflash_conv wave-koalesziert, volles `[5,768]`-LDS-Staging | `libr4d/r4d_dflash_conv_body.h`, `r4d_fulldrafter.hip` |
| Top-16-Schleife mit `m_limit`, Sentinel-Abbruch | `r4d_fulldrafter.hip` |
| Rank-1-Orthogonal-Cauchy-Schwarz-Pruning von `markov_matrix_b`, `use_cs_prune`-Guard | `r4d_fulldrafter.hip:1636, 1663, 2398`; Host-Norm `rad_block_fulldrafter.h:955` |
| Anker-Token ohne zusätzlichen VRAM | `r4d_fulldrafter.hip:222-267`, `qwen4exp_fp8.cpp:1807` |
| Embedding-Tabellen 50/50 über TP2 | `rad_block_fulldrafter.h:303` |
| QSA-Query-Sharding ab `T >= 4` | `arch/common/rad_qsa.h:452` |
| Trunk/Draft-Event-Trennung | `core/engine.cpp` (`trunk_end_`, `draft_end_`) |
| Submit-Politik 4 oder 8 | `scheduler.h:105-120`, `draft.h:42-49` |
| Phasen-Timer ohne Debug-Level: `RADIANCE_PHASE_TIMING=1` | `core/engine.cpp:483-492` |

Numerik der Kernel-Änderungen: verlustfrei, nicht bitgenau. Die 768er-Reduktion läuft als 32-Lane-Wellenreduktion
statt seriell, Akkumulator und Zwischenformate bleiben (`float`/BF16/FP32). Für das Gate: `"numerics": "reordered"`.

## 6. Was fehlt (nächste Hebel)

| Hebel | Stand |
|---|---|
| Baumverifikation (Root-Fork, DARTree-artig) | `fulldrafter_build_root_fork` (`arch/common/rad_fulldrafter_tree.h:81`) hat keinen Aufrufer. `engine_draft.cpp:544` baut nur `build_linear`. `RADIANCE_DARTREE_TOPOLOGY` wird nirgends gelesen. **Die GDN-Kernel haben keinen Zustand je Knoten** (kein Parent-Operand in `rad_block_gdn_fp8.h`; Recurrent- und Conv-Kernel laufen linear). Ein Geschwister-Blatt erbte den Zustand der Vorgängerzeile. Offline-Obergrenze für einen Root-Fork nur mit Blättern: Makro +3,0 / +4,2 / +5,3 % `tau` bei 1 / 2 / 4 Alternativen (Step 280000, `rec_eval_t1`, nicht live gemessen, Kosten der Zusatzzeilen nicht abgezogen). Das Skript liegt nicht im Repo. Die CPU-Referenz `libref/ref_tree_state.h` beschreibt die Eltern-Semantik schon. |
| Kleine Drafter-Kernel fusionieren | nicht gebaut. 17 Launch-Lücken mal 4,5 µs, ca. 78 µs je Stage (**[INFERENCE]**, Obergrenze aus `rocprofv3`). |
| Trunk-Zeit aufschlüsseln | nie gemessen. `collect` (Trunk-Wait) ist 87-89 % des Steps, Drafter nur 8-10 % (`RADIANCE_PHASE_TIMING=1`, TP2, 210 W: Prose 15,8 von 17,7 ms, Code 17,5 von 20,1 ms). Das ist der größte Hebel und für ihn gibt es keine Op-Aufteilung. Dafür muss `engine_manager.sh` Engine-Argumente (`--profile-ops`) durchreichen. |
| `RADIANCE_DLOOP_THETA` pro Kategorie durchfahren | nicht gemessen. |
| Aufgezeichnete Queue (AQL-Tape) für den Drafter-Pass | nicht genutzt. Kein Treffer in `engine_draft.cpp`. Gewinn unklar, der Drafter ist nur ca. 8-10 % des Steps. |

Training (nicht in diesem Repo): Die Änderung mit On-Policy-Terminal-Mode-Zielen und Kategorie-Boost brachte nach
25.000 Steps keinen messbaren Gewinn (`tau_sample` 2,809-2,815 gegen 2,8185, `train_load_v2.log`). Die Läufe wurden bei
Step 308.450 gestoppt. Bester Checkpoint: Step 280000 (`tau_sample` 2,8192).

## 7. Tiefe und Akzeptanz: Korrekturen

- Die Annahme "effective FIXED_DEPTH 3" im Autoresearch-Harness ist **falsch**: `scripts/autoresearch_acceptance.py`
  setzt `RADIANCE_FIXED_DEPTH` nirgends (nur Kommentare auf `:45` und `:102`). Dort wirkt der adaptive Regler des
  `fulldrafter-input-fix`-Builds und begrenzt auf 3 bis 5 Token (`scheduler.cpp:1138`). Die gemessenen ca. 34 % Akzeptanz
  (29 Prompts, Step 92500) gelten für diese unbekannte Tiefe, nicht für 2x4.
- Das 70-%-Ziel (accepted/proposed, Makro über 8 Kategorien) ist nie mit der 2x4-Politik gemessen worden. Dafür braucht
  es ein neues Harness-Segment gegen diesen Build. Das Harness lebt in `RadianceMine` (Branch
  `autoresearch/verbesser-das-modell-so-lange-bis-es-perfekte-me-20261013`), Dateien `scripts/autoresearch_*`.
- Ein kalter Einzel-Request im Smoke-Test zeigte `draft_n` 556, `draft_n_accepted` 61 (11 %). Er ist kein Benchmark.
  Mit den gleichen Einstellungen wie im Rezept lag `tok/update` danach bei 1,7 bis 4,3 je Kategorie.

## 8. Gate

Dieses Repo ist ohne Gate entstanden, auf deine Anweisung (kein Vergleich mit MTP). Wer später nach `RadianceMine/main`
zurückspielen will, braucht `scripts/gate_check.sh` mit `gate.json` (`engine_env` mit den FullDrafter-Variablen aus §3,
`"numerics": "reordered"`), sonst misst das Gate nur den MTP-Standard. Zu beachten: Die gemeinsamen Scheduler-Änderungen
(`scheduler.h:105-120`, `draft.h:42-49`) ändern auch die MTP-Tiefenregeln (Mehrfach-Stream-Boden 4 statt 3).

## 9. Wo was liegt (außerhalb dieses Repos)

| Was | Wo |
|---|---|
| Sidecars, Teacher-Matrizen, Checkpoints, Trainingsdaten | `/home/orca/drafter_data/` |
| Drafter-Training (Python) | `/home/orca/Drafter/` (`scripts/train_flash_next.py`, `research/block_drafter/`) |
| Berichte `betterbench_2x4_*.json`, `between_phase_eval_*` | `/home/orca/RadianceMine/reports/`, `.../worktrees/fulldrafter-speed-opt/reports/` |
| Autoresearch-Harness, Notizen, Läufe | `/home/orca/RadianceMine` (Branch `autoresearch/...`), `reports/autoresearch_acceptance/` |
| Ursprungs-Worktree dieses Codes | `/home/orca/RadianceMine/worktrees/fulldrafter-speed-opt` (Branch `worktree/fulldrafter-speed-opt`) |
| Fremde, uncommittete Baum-Arbeit (GDN-Baum-Operationen, `ref_gdn_tree.*`, `gdn_tree_ops_test.cpp`) | `/home/orca/RadianceMine/worktrees/tap_record`, nicht angefasst, gehört einem anderen Agent |
| Gepinnter Build des Harness | `/home/orca/RadianceMine/worktrees/fulldrafter-input-fix` (110 uncommittete Dateien) |

Nicht ins Repo committen: Zugangsdaten (liegen in `/home/orca/RadianceMine`, per `.git/info/exclude` ausgeschlossen),
Gewichte, `build_hip`, `reports/`.

## 10. Vorschlag für den nächsten Schritt

1. Trunk-Zeit aufschlüsseln (`--profile-ops`), das ist der einzige Hebel, der mehr als ein paar Prozent verspricht.
2. Wenn der Baum gewünscht ist: zuerst den GDN-Zustand je Knoten in einem eigenen Plugin/Op lösen (siehe
   `libref/ref_tree_state.h` als Orakel), erst danach den Root-Fork verdrahten.
3. Für die 70-%-Frage ein neues Harness-Segment mit expliziter Tiefenpolitik gegen diesen Build.
