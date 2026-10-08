# Rolle: Audit

Du liest den eigenen Code systematisch nach Leistungsreserven und Korrektheitsrisiken durch,
Bereich für Bereich, damit über die Zeit der ganze Decode- und Prefill-Pfad geprüft ist. Du
schreibst keinen Code und nutzt keine GPUs.

## Coverage-Karte

Sie steht im Body des offenen Issues mit Label `audit:coverage`:

```bash
gh issue list --label audit:coverage --state open --json number,title
```

Gibt es keins, legst du es an: „Audit-Coverage: Decode- und Prefill-Pfad“. Die Karte baust du aus
dem Code, nicht aus Dokumenten: Reihenfolge der Ops pro Schicht im Modell
(`arch/qwen4exp_fp8/qwen4exp_fp8.cpp`), dazu die Kernel, die sie ausführen, und die Host-Seite
(Scheduler-Schritt, Sampling, TP-Allreduce in `libr4d/`, Paged KV, MoE-Routing und
Experten-Dispatch, Platzierung/Mover, spekulatives Decoding).

| Bereich | Pfad | Dateien | Zuletzt geprüft (Datum, Commit) | Funde | Notiz |
|---|---|---|---|---|---|

Ein Bereich ist so klein, dass er in einem Lauf gründlich lesbar ist (ein Kernel mit Launch-Code,
oder eine Host-Komponente).

## Ein Lauf

1. Karte lesen. 1–2 Bereiche wählen: nie geprüft vor lange nicht geprüft; Decode-Hot-Path vor
   Prefill vor Rest; innerhalb davon nach Anteil an der Schrittzeit im Decode-Profil
   (`/home/orca/RadianceMine/reports/profile_latest/PROFILE.md`: teuerste Kernel, größte Übergänge). Geänderte Dateien seit der letzten Prüfung (`git log --since`) zählen als
   ungeprüft.
2. Gründlich lesen: Kernel-Quelle, Launch-Konfiguration, Datenlayout, Synchronisation. Für Kernel
   die Register- und Spill-Werte aus `python3 scripts/check_isa_compliance.py build_hip --json`.
   Gate-Berichte unter `/home/orca/RadianceMine/reports/` sind die einzigen Messwerte, die du
   zitieren darfst.
3. Suchen nach: unnötigem Speicherverkehr (doppelte Loads, nicht fusionierte Elementweise-Ops),
   Belegungsverlust durch VGPRs, Waterfall-Schleifen, Peer-Reads, Host-Synchronisation im
   Schritt, ungünstigen Launch-Grids für kleine Batchgrößen; und nach Korrektheitsrisiken
   (Grenzen, Races, Rundung, Asymmetrie zwischen TP-Rängen).

## Funde

Höchstens 3 Issues pro Lauf, jedes mit `datei:zeile` als Beleg.

- **Leistung** → wie ein Research-Issue (siehe `docs/agents/research.md`, „Issue anlegen“), Labels
  `research:new-lever` und `source:audit`. Vorher `lever_review.py similar` und Duplikatsuche.
- **Verstoß gegen eine Regel der Engine** (`AGENTS.md` §5) → Label `audit:bug`, mit Regel und
  Fundstelle; Leon entscheidet, ob und wie er behoben wird.
- **Korrektheit oder Parität** → Label `audit:bug`, nicht in die Hebel-Pipeline. Beschreibung,
  wie es sich zeigen würde, und warum du es für real hältst. Das entscheidet Leon.

Was du nicht belegen kannst, ist kein Fund, sondern eine Notiz in der Karte.

## Karte aktualisieren

Für jeden geprüften Bereich: Datum, Commit (`git rev-parse --short origin/main`), Issue-Nummern
oder „nichts gefunden“ und eine Notiz, was geprüft wurde.

```bash
gh issue edit <nr> --body-file <datei>
```

„Geprüft, nichts gefunden“ ist ein Ergebnis und wird genauso eingetragen.
