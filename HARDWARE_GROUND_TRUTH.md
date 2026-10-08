# Hardware Ground Truth

Gemessene Werte für den Server (LXC CT 107). Neu messen mit `bash scripts/measure_hardware.sh`
(Quelle: `scripts/hwprobe/p2pbw.cpp`, 256 MiB je Transfer, 20 Wiederholungen, 3 Läufe).

**Letzte Messung:** 2026-10-08, Engine geladen aber idle.

## System

| Komponente | Wert |
|---|---|
| CPU | AMD EPYC 7402P (Rome, 24C/48T), nur PCIe 4.0 |
| GPUs | 2× AMD Radeon AI PRO R9700, `gfx1201` (RDNA4), 32 GiB GDDR6, Wave32 |
| GPU-PCI-Adressen | GPU0 `0000:43:00`, GPU1 `0000:c3:00` (verschiedene Root Complexes) |
| Anbindung | PCIe 4.0 x16, kein xGMI/Infinity Fabric Link; **nie mit PCIe 5.0 rechnen** |

## Bandbreiten (gemessen)

| Pfad | GPU0 → GPU1 | GPU1 → GPU0 |
|---|---|---|
| Kopie per Copy-Engine (`hipMemcpyPeerAsync`) | 26,2 GB/s | 26,0 GB/s |
| Kernel **schreibt** in den Speicher der anderen GPU | **27,5 GB/s** | **27,5 GB/s** |
| Kernel **liest** aus dem Speicher der anderen GPU | **5,9 GB/s** | **5,8 GB/s** |

| Pfad | GPU0 | GPU1 |
|---|---|---|
| Host → GPU | 26,4–27,3 GB/s | 26,4–27,3 GB/s |
| GPU → Host | 26,2–27,1 GB/s | 26,0–27,2 GB/s |
| Lokaler VRAM, Kopier-Kernel (Lesen + Schreiben) | 537–553 GB/s | 539–543 GB/s |

Folgerungen:

- Die Verbindung ist **symmetrisch**. Die früher beobachtete „Asymmetrie“ (7,4 vs. 27,8 GB/s)
  ist der Unterschied zwischen Lesen und Schreiben über PCIe: Peer-Reads sind ~4,7× langsamer.
  Datenaustausch zwischen den GPUs (All-Reduce, Gather) muss per **Push** (in die andere GPU
  schreiben) laufen, nie per Pull.
- Die frühere Zahl „16,95 GB/s bidirektional“ passt zu keinem gemessenen Pfad und gilt nicht.
- Transferbudget: 2,5 MiB über PCIe 4.0 ≈ 95–100 µs (Host→GPU oder Peer-Write).
- VRAM: Ein einfacher Kopier-Kernel erreicht ~545 GB/s. Das passt zu 640 GB/s Spitze laut
  Datenblatt (~85 % Effizienz); 576 GB/s würden unplausible ~94 % bedeuten. Für Rooflines mit
  ~545 GB/s erreichbar rechnen.

## Speicheraufteilung der Engine (aus dem Startlog von `scripts/start_engine.sh`)

| Bereich | Größe |
|---|---|
| Gewichte + residente Experten-Slab je GPU | 28,65 GiB |
| Paged KV-Cache (FP8) | 1,56 GiB (`--vram-kv-mib 1600`) |
| Pinned Host-Pool | 12 GiB (`--host-pool-mib 12288`) |
| Prefix-Cache Host-Tier | 8 GiB (`--prefix-cache-host-mib 8192`) |

Zwei Engines passen nicht gleichzeitig in den VRAM; A/B-Messungen laufen deshalb nacheinander
(`scripts/ab_gate.py`).

## Speichertakt

Im Leerlauf fällt MCLK auf 96 MHz (DPM 0); das ist normal und kein Fehler. Entscheidend ist der
Takt **während** der Messung: `ab_gate.py` zeichnet ihn je Engine-Block auf (`mclk` in
`summary.json`).

## Rauschen der Benchmarks

Siehe Abschnitt „Kalibrierung“ in `docs/GATE.md`.
