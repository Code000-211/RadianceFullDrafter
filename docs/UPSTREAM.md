# Upstream (Codeberg) übernehmen

Upstream ist `codeberg.org/StillDeadcode/radiance`. Unser Repo ist ein Fork mit gemeinsamer
Historie (abgezweigt bei `d0f639b`, „radiance 1.0.13“); unsere Arbeit steckt bisher direkt in
Upstream-Dateien unter `core/`, `libr4d/`, `arch/`.

Ziel: Die Engine von Upstream laufend übernehmen, auch alles, was uns nicht direkt betrifft
(TP3/TP4, andere Modelle, Server, Tooling), aber nur soweit es unsere Pipeline für
Qwen3.8-Flash-Next auf 2× R9700 nicht verschlechtert oder bricht. Für unser Modell sollen unsere
Kernel gelten. Kein Merge passiert ohne Agent, Review und Gate; `main` ändert nur Leon.

## Zwei Wege von Upstream zu uns

| Was | Werkzeug | Ergebnis |
|---|---|---|
| Offene Upstream-PRs | `scripts/watch_upstream.py` (Dienst `radiance-upstream-watcher`) + Agent `upstream` | Bewertung in `candidates/upstream/REVIEW.md`; Leon entscheidet |
| Neue Commits auf Upstream-`main` | `scripts/upstream_sync.py` (Timer `radiance-upstream-sync`) + Pipeline plan → code → review → Gate | PR mit Merge-Commit; Leon merged |

## Ablauf eines Syncs

```
Timer (alle 6 h) ─► upstream_sync.py               deterministisch, kein LLM, nichts gemerged
    fetch Codeberg main ─► neue Commits? kein offenes Sync-Issue?
    ├─ Spiegel: Branch upstream/main auf GitHub
    └─ Issue „Upstream-Sync …“ (Label upstream:sync): Commits, Konflikte (git merge-tree),
       von beiden Seiten geänderte Dateien, frühere Ausschlüsse
                │
Agent plan (Opus)   Commit für Commit: übernehmen / angepasst übernehmen / ausschließen,
                    Konfliktregeln je Datei, Stufe  ─► plan:ready
Agent code          merged genau den Upstream-Stand aus dem Issue, löst Konflikte nach Plan,
                    schließt Commits per Revert aus  ─► needs-code-review (mode: merge)
Agent review        prüft Merge und Ausschlüsse gegen den Plan  ─► status:ready-to-test
Lever-Queue         Modus merge: testet den Branch selbst (muss origin/main enthalten),
                    A/B gegen main, Parität + Speed  ─► PASS: PR „upstream: …“
Leon                merged mit Merge-Commit (nicht squashen, nicht rebasen)
```

Ein Gate-Fehlschlag geht wie bei einem Hebel an den Code-Agent zurück (Gate-Fix): Er bestimmt aus
dem Bericht, welcher Upstream-Commit die Verschlechterung bringt, und schließt ihn aus oder setzt
`plan:needs-revision`. Es ist immer höchstens ein Sync-Issue offen; was danach auf Upstream
landet, kommt in den nächsten Sync.

## Regeln für die Entscheidung

- **Was unser Gate misst, entscheidet.** Das Gate fährt Qwen3.8-Flash-Next mit TP2 auf beiden
  GPUs. Verschlechtert ein Merge Parität oder Speed, ist das ein Fehlschlag, egal wie gut der
  Commit anderswo ist.
- **Was das Gate nicht misst (TP3/TP4, andere Modelle, CPU-Pfade), wird übernommen**, wenn es
  baut, die CPU-Tests (`ctest -LE gpu`) bestehen und es unseren Pfad nicht berührt.
- **Kernel auf unserem Pfad:** Unsere Fassung bleibt, solange kein Gate-Bericht zeigt, dass die
  Upstream-Fassung bei unseren Formen mindestens gleich schnell und paritätsgleich ist.
  Korrektheitsfixes von Upstream werden in unsere Fassung übertragen.
- **Engine-Kern:** Upstream-Fassung übernehmen und unsere Änderung darauf neu anwenden, nicht
  umgekehrt; so bleibt der nächste Merge klein.
- **Ausschließen** heißt: nach dem Merge `git revert --no-edit <sha>` im Sync-Branch, Commit-Text
  mit Zeile `Upstream-Excluded: <sha> <Grund>`. `upstream_sync.py` listet diese Ausschlüsse im
  nächsten Sync-Issue, damit der Planer sie neu bewerten kann.
- **Goldens:** Ändert Upstream absichtlich die Ausgabe (z. B. Sampling), schlägt die Parität fehl.
  Das ist kein Grund, `baselines/` anzufassen; der Agent beschreibt den Fall im Issue, Leon
  entscheidet.

## Ziel-Architektur: unsere Kernel als eigenes Plugin

Heute stecken unsere Kernel-Änderungen direkt in der Upstream-Bibliothek `libr4d/`: 43 geänderte
Dateien seit dem Abzweig (dazu 45 in `core/`, 9 in `arch/`, `git diff --name-only d0f639b`). Jeder
Upstream-Merge, der dort etwas ändert, wird zum Konflikt. Die Engine ist dafür gebaut, das zu
vermeiden (`spec.md` §2.1, `docs/PLUGIN.md` §13):

- Kernel-Plugins werden in der Hierarchie `--kernels` (bzw. `$RADIANCE_KERNELS`) abgefragt; das
  erste Plugin mit einem passenden Kernel liefert ihn, ein späteres überbietet es nie.
- Constraints eines Kernels (`RadConstraint`) beschränken ihn auf Geometrien, z. B. unsere Formen
  und `world_size == 2`.
- `$RADIANCE_HOME` ist ein Suchpfad; ein eigenes Architektur-Plugin gleichen Namens früher im
  Pfad überdeckt das von Upstream.

Zielbild:

```
--kernels mine,libr4d
  mine    unsere Kernel, nur für die Geometrien von Qwen3.8-Flash-Next (TP2, gfx1201)
  libr4d  unverändert wie Upstream: alles andere, auch TP3/TP4 und andere Modelle
```

Dann übernimmt ein Sync `libr4d/` ohne Konflikt, und unsere Kernel ersetzen die von Upstream genau
für unser Modell. Was in `core/` und `arch/` bleibt, sollte möglichst klein werden; allgemeine
Verbesserungen sind Kandidaten für einen PR an Upstream (Leons Entscheidung).

Der Umbau ist eigene Arbeit für die Pipeline, Kernel für Kernel als Hebel: Der Planer plant je
Op den Umzug nach `mine` (gleiches Op-Schema, Constraints auf unsere Geometrie), das Gate muss
bit-gleiche Parität und gleiche Geschwindigkeit zeigen, danach wird die Datei in `libr4d/` auf
den Upstream-Stand zurückgesetzt. Ein späterer Schritt kann regelmäßig mit `rad_kbench` messen,
ob eine Upstream-Fassung bei unseren Formen inzwischen schneller ist; dann fliegt unser Kernel
aus `mine`.

Risiko: Das Op-Schema legt das erste Plugin in der Hierarchie fest (`spec.md` §2.3). Ändert
Upstream das Schema eines Ops, das `mine` überdeckt, muss `mine` nachziehen; Build und Gate
zeigen das beim Sync.
