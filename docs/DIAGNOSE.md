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
| A | `--diagnose DIR`: eingebaute Last (Chat-Template, feste Seeds, `ignore_eos`), Phasen Aufwärmen → Decode 1 Stream → Decode 8 Streams → langer Prefill → optional Korrektheit; danach Bericht und Ende | `core/engine_diagnose.cpp`, reine Teile in `core/diag.{h,cpp}`, Flag in `core/config.cpp` | ja |
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

1. **A + B + G** (Grundgerüst, Host-testbar): Flag, Treiber, Schritt-Ring, Bericht, Dashboard.
   Danach liefert `--diagnose` sofort ms/Schritt, Tokens/Schritt, Annahme, TTFT, ITL-Verteilung,
   langsamste Schritte, Placement-Zähler pro Phase.
2. **C** (Census) und `rad-kbench --census` mit Vorhersage.
3. **D + E** (Gerät): Zeitstempel pro Dispatch, Kalibrierung; Prüfung auf epyc durch die Pipeline.
4. **F** (Korrektheitsfenster) und Kausaltest.
5. Was-wäre-wenn und Abstand zur Grenze.

Jeder Schritt einzeln baubar, mit Tests im Host-Backend, und einzeln als PR an Upstream denkbar.

## Messregeln, die der Bericht einhält

- Kernel-Zeit ist echt, Lücken sind eine Obergrenze, solange Messung sie erzeugen kann.
- Für Kernel-Entscheidungen das Minimum, für Schritte Median und Streuung; nie den Mittelwert
  verrauschter Läufe.
- Der Bericht hält fest: Plan-Modus (dynamisch oder `--deterministic`), wirksame Placement-Parameter,
  alle gesetzten `RADIANCE_*`/`R4D_*`/`RAD_*`/`AVX_*`, Sampling der Last. Verbotene Einstellungen aus
  `AGENTS.md` §4 lehnt er ab.
- Die Diagnose ersetzt das Gate nicht. Das Gate bleibt das einzige Abnahmekriterium; die Diagnose
  sagt, wo die Zeit hingeht und was sich lohnen könnte.
