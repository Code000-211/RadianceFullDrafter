# Diagnose-Modus und Vorab-Bewertung (Entwurf)

Ziel: `radiance --diagnose <dir>` führt alle Messungen, die wir heute von außen machen
(`scripts/profile_engine.py`, BetterBench-Teile, `rocprofv3` + `tsum.sh`/`gaps.sh`, Orakel/Repeat),
in der Engine selbst aus, schreibt einen Bericht (JSON + Markdown) und zeigt ihn im Dashboard. Dazu
Werkzeuge, die einen Kernel oder eine Idee **vor** Implementierung und Gate bewerten.

Gebaut wird generisch für Upstream (keine Annahmen über unser Modell oder TP2 im Code); wo wir etwas
auf uns zuschneiden müssen, hat das Vorrang und steht in einem eigenen Abschnitt des Berichts. Es
gelten die Regeln der Engine (`AGENTS.md` §5). Grundlage ist eine Kartierung des Codes mit
Fundstellen; die wichtigsten stehen unten.

## Was der Code vorgibt (bestimmt den Entwurf)

1. **Der eingeschwungene Decode läuft aus aufgezeichneten Pässen.** `PlayRun::put` spielt
   AQL-Pakete ab (`core/device/aql.cpp:899-946`), nicht `rad_issue`. Ein Messinstrument nur im
   Issue-Pfad sieht den Betrieb nicht oder erzwingt Live-Issue, und das ist eine andere Engine
   (Barrier-Bit auf jedem Paket, kein Überlappen). `--profile-ops` hat genau dieses Problem
   (`ctx.cpp:150`). Zeitmessung pro Dispatch gehört deshalb in die Abspiel-Schicht des AQL-Backends.
2. **Ein Paket hat genau ein `completion_signal`.** Zeitsignale nur in die Queue-Kopie, nach der
   Tape-Aufnahme, aus einem vorab angelegten Satz (nicht aus `SigPool`: Mutex und Allokation,
   `aql.cpp:1289-1327`). Auslesen verzögert und nicht blockierend (GPU_ONLY-Signale können keinen
   Host-Wait beenden, `aql.cpp:992-995`).
3. **Nichts darf die aufgezeichneten Pässe verändern, ohne im `pass_key` zu stehen**, sonst schlägt
   das Tape-Audit mit `RAD_E_STATE` zu (`ctx.cpp:1349-1369`). Verzögerungs- oder Barrier-Pakete
   werden außerhalb der Aufnahme geschrieben und tragen das Barrier-Bit (`aql.cpp:628-650`).
4. **Profiling, Orakel, Repeat und Tapes sind ab `Ctx::prepare` fest** (`ctx.cpp:60, 139-152`). Ein
   Diagnose-Lauf mit Leistungs- und Korrektheitsteil braucht eine Arm/Disarm-API pro Schrittfenster,
   angewandt auf allen Rängen gleichzeitig bei geparkten Rank-Threads (Repeat startet `all_reduce`
   neu; asymmetrisch hängt TP2 bis zum Trap nach 4e9 Spins, `r4d_ar_oneshot_2rank_exact.hip:108-118`).
5. **Der Treiber hat ein Vorbild:** der KL-Modus (`core/engine_kld.cpp:76-131`). Requests mit
   `server::Sink` direkt an `Scheduler::add_all`, ohne HTTP, auf dem Main-Thread.
6. **Kernel-Auswahl, Instanzen und Scratch sind ab dem Binden fest** (`core/plugin/select.cpp`). Ein
   Kandidat-Kernel lässt sich nicht zur Laufzeit tauschen; Vorab-Bewertung von Kerneln läuft über
   `rad-kbench` mit den aufgezeichneten Formen der Engine.
7. **Host-Backend:** kein Kernel-Dispatch, keine Tapes, Events sind `steady_clock`. Alles Reine
   (Treiber, Schritt-Ring, Census, Statistik, Bericht, Was-wäre-wenn) baut und testet ohne ROCm;
   alles Gerätespezifische ist ein abschaltbarer Eintrag, der `RAD_E_UNSUPPORTED` liefert und im
   Bericht als „nicht verfügbar“ steht, nie als 0.

## Bausteine

| # | Baustein | Wo | Host-testbar |
|---|---|---|---|
| A | `--diagnose DIR`: eingebaute Last (Chat-Template, Server-Sampling mit festen Seeds). Messpunkte: Decode nach Kategorie (code, reasoning, prose, json, file_edit, summarization; Korpus eingebaut oder `--diagnose-corpus`), Concurrency-Sweep (`--diagnose-concurrency`, Default 1,2,4,8), Prefill-Sweep mit Decode in der jeweiligen Tiefe (`--diagnose-prefill`, Default 1k–64k), ein Prompt, der in laufende Streams kommt (TTFT unter Last, Stall der laufenden Streams). Jeder Punkt 1× unbewertet, dann `--diagnose-runs`× (Default 3); Median mit Spanne | `core/engine_diagnose.cpp`, reine Teile in `core/diag.{h,cpp}`, Flags in `core/config.cpp` | ja |
| B | Schritt-Ring: pro Schritt Phase, `n_seq`, `n_tok`, akzeptierte Draft-Tokens, Phasenzeiten, Host-Syncs, Joins, Commit-Zeitstempel. Daraus ms/Schritt, Tokens/Schritt, Annahmequote, langsamste gegen typische Schritte, ITL pro Schritt | `Scheduler::step_finished` (`scheduler.cpp:1674-1712`), vorab angelegter Ring | ja |
| C | Issue-Census: jede (Op, Band, Domain, `n`) mit Aufrufen pro Schritt und Operandenformen; Export als Datei für `rad-kbench` | `Ctx::issue_body` nach `++n_issues_` (`issue.cpp:817`), Speicher in `bind_*` | ja |
| D | Zeitmessung pro Dispatch auf jedem N-ten Schritt im Abspiel- und Live-Pfad, Zuordnung zu Op über eine beim Aufzeichnen gespeicherte Record→Op-Tabelle; Auswertung wie `tsum.sh`/`gaps.sh` in C++ (Union-Busy, Lücke vor dem nächsten Kernel, Joins) | `aql.cpp` PlayRun::put/dispatch, Sammler außerhalb des Step-Pfads | Zuordnung ja, Zeit nein |
| E | Kalibrierung im Lauf: VRAM- und Link-Bandbreite (`aql_copy16`, `aql_copy_link`), Peer-Schreiben/-Lesen, Launch-Boden pro Dispatch; immer mit Basis (Kernel, Grid, R+W) | Bringup bzw. Diagnose-Phase vor dem Pool-Sizing | nein |
| F | Korrektheitsfenster: Repeat und Orakel für ausgewählte Ops über ein Schrittfenster statt für den ganzen Prozess; Ops ohne `libref`-Zeile als „NICHT GEPRÜFT“ | `oracle.cpp` arm API, angewandt bei geparkten Rängen | ja |
| G | Dashboard: Tab „Diagnose“ liest den letzten Bericht; `GET /diagnose` | `core/server/dashboard.cpp`, Route in `server.cpp` | ja |

## Vorab-Bewertung

| Werkzeug | Frage | Grundlage |
|---|---|---|
| Kernel-Vorhersage | Bringt Kernel X auf unseren echten Formen etwas? | Census (C) → `rad-kbench --census` misst alt gegen Kandidat auf genau diesen Formen; Vorhersage Δ Schritt = Σ Aufrufe × Δ Zeit, getrennt nach Decode 1/8 und Prefill. Heute fehlt dafür: kbench deklariert TP1, `n_seq=1`, `max_tok 512` (`tools/rad_kbench.cpp`) |
| Was-wäre-wenn | Was bringt Op k doppelt so schnell, oder A+B fusioniert? | Zeitleiste pro Rang (D) plus Abhängigkeits-DAG, den `Ctx::haz_mark` schon berechnet (`ctx.cpp:1125-1201`); All-Reduce als Kopplung beider Ränge, nicht als eigene Kosten |
| Kausaltest | Liegt Op k auf dem kritischen Pfad? | Verzögerungs-Kernel (Spin auf REALTIME-Takt) nach Op k auf beiden Rängen, abwechselnd mit/ohne; Änderung der Schrittzeit / eingefügte Zeit = Empfindlichkeit |
| Abstand zur Grenze | Wie viel Luft hat Op k? | Bytes aus dem Census (Operandengrößen × dtype), gemessene Bandbreite aus (E). FLOPs bräuchten einen ABI-Hook oder eine Tabelle über die Op-Liste: Entscheidung für Leon bzw. Upstream (ABI ist eingefroren, nur anhängen) |
| Placement-Ideen | Was bringen andere Heat-/Budget-/Prefetch-Parameter? | Routing-Histogramme des Laufs aufzeichnen, offline durch `HeatEngine` mit einfachem Mover-Modell spielen (C++-Werkzeug); liefert Schranken, keine Schrittzeiten |

## Reihenfolge

1. **A + B** (fertig, Host-getestet): Flag, Treiber, Schritt-Ring, Bericht mit Kategorien,
   Concurrency- und Prefill-Sweep, Interferenz. **1b + G**: Placement-Zähler pro Phase, Dashboard.
2. **C** (Census) und `rad-kbench --census` mit Vorhersage.
3. **D + E** (Gerät): Zeitstempel pro Dispatch, Kalibrierung; Prüfung auf epyc durch die Pipeline.
4. **F** (Korrektheitsfenster) und Kausaltest.
5. Was-wäre-wenn und Abstand zur Grenze.

Jeder Schritt einzeln baubar, mit Tests im Host-Backend, und einzeln als PR an Upstream denkbar.

## Damit die Messung real ist

| Störgröße | Was der Diagnose-Lauf tut |
|---|---|
| Prefix-Cache (VRAM, Host- und Disk-Tier) | Jeder Prompt trägt am Anfang ein Tag, eindeutig pro Prozess und Request (die Tiers überleben einen Neustart, also enthält das Tag Zeit und PID). Cache vor jedem Lauf geleert. Nach jedem Lauf wird `n_cached` jedes Requests geprüft; ein Treffer macht das Urteil „NOT A MEASUREMENT“ und den Exit-Code ungleich 0. Der Cache bleibt an, damit Lookup, Publizieren und Checkpoints wie im Betrieb bezahlt werden. `--no-prefix-cache` geht auch, steht dann als Warnung im Bericht |
| Erste Ausführung einer Form (Tape-Aufnahme, Code-Objekte laden) | Jeder Messpunkt läuft einmal unbewertet vorher, in derselben Form |
| `ignore_eos` erzeugt Text nach dem EOS, auf dem der Drafter anders trifft | Kategorien enden auf dem EOS des Modells (Anzahl wird berichtet); nur Concurrency und Prefill nutzen `ignore_eos`, damit alle Streams die ganze Zeit dekodieren |
| Greedy oder falsches Sampling verfälscht die Annahmequote | Temperatur 1 (Betriebstemperatur, auf die das adaptive MTP abgestimmt wird), top_k/top_p/min_p aus den Server-Defaults, feste Seeds pro Request |
| Reasoning an/aus ändert die Ausgabeverteilung | Deployment-Default (`--reasoning-effort`), im Bericht festgehalten |
| Decode-Geschwindigkeit hängt von der Kontexttiefe ab | Prefill-Sweep misst Decode in jeder Tiefe |
| Rauschen von Lauf zu Lauf | `--diagnose-runs`, Median mit Min–Max |
| Host-Last (Agent-Builds auf epyc!) | Load-Average am Anfang und Ende im Bericht, Warnung bei Last > CPUs/4. Diagnose nur laufen lassen, wenn die Queue die GPUs hat und keine Builds laufen |
| Dynamische Platzierung driftet mit der Last | Plan-Modus im Bericht; für Vergleiche `--deterministic` oder gleiche Reihenfolge der Punkte. Placement-Zähler pro Phase: Schritt 1b |
| HTTP, Detokenisierung, SSE | Nicht enthalten (steht im Bericht). Der Abstand zu BetterBench ist genau dieser Anteil |
| Verbotene Einstellungen (`AGENTS.md` §4) | Warnung im Bericht (`RADIANCE_HEAT_RESIDENCY`, `--profile-ops`) |

Für die BetterBench-Kategorien mit denselben Prompts: deren Korpus einmal als JSONL exportieren
(`{"category", "messages"}` pro Zeile) und mit `--diagnose-corpus` übergeben. Gewichtung und Score
bleiben außerhalb der Engine (`scripts/bench_metrics.py`), sie lesen `diagnose.json`.

## Parität über die ganze Last

Das Salz ist ein Zähler, kein Zeitstempel: Zwei Builds bekommen dieselben Prompts und dieselben
Seeds, und jeder Request schreibt seine Tokens in den Bericht. Bitgleiche Logits ergeben bei jeder
Temperatur dieselben Tokens. `--diagnose-baseline ALT/diagnose.json` vergleicht deshalb Kategorien,
Concurrency und Prefill Token für Token, nennt je abweichendem Request die erste abweichende Stelle
und beendet den Lauf mit Fehler. Interferenz wird nicht verglichen (Abbruchzeitpunkt hängt am
Timing). Vorher die Baseline zweimal gegen sich selbst laufen lassen: Weicht sie dort ab, ist ein
Pfad nicht deterministisch und taugt nicht für Bitparität. Daneben die Draft-Annahme je Punkt: insgesamt
per gepaartem t-Test über die Requests (Drafts in einem Text sind nicht unabhängig), je Position
per gepooltem z, korrigiert um die Dispersion der Requests; so unwahrscheinlich wie z < −3 heißt
`DROPPED` und lässt den Lauf scheitern.

**Erster Lauf auf epyc (8.10.2026, c7b9795, Gate-Konfiguration):** zwei Prozesse desselben Builds
waren nur bei 43 von 141 Requests tokengleich, oft ab Token 0, in allen Punkten. Der Seed ist es
nicht (zählerbasiert über Seed und Position, `core/sample/accept.cpp`); der Prefill selbst liefert
also zwischen Prozessen verschiedene Logits. `--tp-wire wht6` ist verlustbehaftet, aber
deterministisch. Verdächtig sind zeitabhängige Pfade (dynamische Platzierung und Mover, Ridgefill,
adaptive Spekulation); Bisektion steht aus. Der alte gepoolte z-Test meldete zwischen den beiden
Läufen `DROPPED` (C8 Position 3), daher der Test auf Request-Ebene. Regel für nicht bitgenaue Hebel und Annahme-Einbrüche: `AGENTS.md` §3, Numerik.

## Messregeln, die der Bericht einhält

- Kernel-Zeit ist echt, Lücken sind eine Obergrenze, solange Messung sie erzeugen kann.
- Für Kernel-Entscheidungen das Minimum, für Schritte Median und Streuung; nie den Mittelwert
  verrauschter Läufe.
- Der Bericht hält fest: Plan-Modus (dynamisch oder `--deterministic`), wirksame Placement-Parameter,
  alle gesetzten `RADIANCE_*`/`R4D_*`/`RAD_*`/`AVX_*`, Sampling der Last. Verbotene Einstellungen aus
  `AGENTS.md` §4 lehnt er ab.
- Die Diagnose ersetzt das Gate nicht. Das Gate bleibt das einzige Abnahmekriterium; die Diagnose
  sagt, wo die Zeit hingeht und was sich lohnen könnte.
