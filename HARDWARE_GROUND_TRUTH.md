# Canonical Hardware Ground Truth & Physical Interconnect Manifest
**Repository**: `RadianceMine`  
**Certification Date**: 2026-10-08  
**Verification Method**: Direct physical HIP kernel measurement (`hipEventElapsedTime`) & sysfs hardware telemetry

> [!CAUTION]
> **ANTI-HALLUCINATION INVARIANT: DO NOT ASSUME PCIE GEN 5**  
> While virtualized hypervisor bridges (PVE) may report 32 GT/s capabilities in sysfs, the **PHYSICAL HARDWARE BUS IS PCIE 4.0 x16**.  
> The CPU platform is an AMD EPYC 7402P ("Rome", PCIe Gen 4 only). Physical unidirectional DMA bandwidth is strictly capped at **~28.3 GB/s**, NOT 58+ GB/s.  
> Any architectural calculation (DMA prefetch, MoE chunk transfer, All-Reduce wire latency) assuming PCIe Gen 5 is **invalid and rejected by Tier 0**.

---

## 1. Verified Physical Hardware Specifications

| Component | Physical Hardware Specification | Verified Runtime Telemetry |
| :--- | :--- | :--- |
| **Host CPU** | AMD EPYC 7402P 24-Core (48 threads) Processor | 24C / 48T @ 2.80 GHz (PCIe Gen 4 Root Complex) |
| **Host Memory** | 179.2 GB DDR4 ECC Registered RAM | `MemTotal: 179,200,000 kB` (~170 GiB usable) |
| **GPU Architecture** | Dual AMD Radeon AI PRO R9700 (`gfx1201`, RDNA4) | 64 CUs, Wave32, Dual Compute Units per card |
| **VRAM Per GPU** | 32,768 MiB (32 GiB) GDDR6 | Peak GDDR6 Clock: **1258 MHz** (576 GB/s memory bandwidth) |
| **Physical Interconnect** | **PCIe 4.0 x16 Slot-to-Slot** | **16 GT/s Physical Payload** (EPYC Rome Gen 4 limitation) |
| **Operating System** | Proxmox VE (PVE) Kernel Linux 7.0.2 / Debian 12 | ROCm 10.0 / HIP 6.x runtime (`gfx1201`) |

---

## 2. Empirically Measured Bandwidth & Latency

Measured via `/tmp/measure_pci` using `hipEventElapsedTime` over 256 MiB transfers:

```
MEASURED PHYSICAL BANDWIDTH:
  Host -> GPU0 (PCIe DMA Write): 28.29 GB/s  (3.62 ms per 100 MiB)
  GPU0 -> Host (PCIe DMA Read):  27.97 GB/s  (3.66 ms per 100 MiB)
  GPU0 -> GPU1 (P2P Interconnect): 16.95 GB/s  (5.90 ms per 100 MiB)
```

### Architectural Transfer Budget (Corrected for PCIe 4.0 x16)
* **MoE Expert Chunk (2.5 MiB)**:
  * Over PCIe 4.0 x16 DMA: $\frac{2.5 \text{ MiB}}{28.29 \text{ GB/s}} = \mathbf{92.6\ \mu s}$ (plus ~5 µs queue dispatch overhead $\approx \mathbf{98\ \mu s}$).
  * *Prior Agent Hallucination*: Claimed 25–40 µs assuming PCIe 5.0. **This caused prefetch queues to stall compute waves!**
* **Decode Layer Latency on RDNA4 Wave32**:
  * Layer compute time: $\approx 12–16\ \mu s$.
  * Therefore, hiding a 2.5 MiB PCIe 4.0 transfer requires a lookahead of **$\Delta L \ge 6–8$ layers**, NOT $\Delta L = 4$!
* **TP2 All-Reduce Payload over wht6**:
  * Cross-rank P2P link bandwidth: **16.95 GB/s**.
  * Uncompressed bf16 All-Reduce introduces major wire stalls at batch sizes $\ge 4$.
  * Walsh-Hadamard 6-bit rotation (`--tp-wire wht6`) compresses the wire payload by $2.67\times$, fitting within the 16.95 GB/s physical P2P ceiling.

---

## 3. Mandatory VRAM & Memory Allocation Layout

The engine must strictly conform to the physical 32 GiB VRAM envelope:

* **Static Weights & Resident Expert Slab**: **28.65 GiB**
* **Paged KV Cache Pool**: **1.56 GiB** (`--vram-kv-mib 1600`, FP8 KV dtype)
* **Pre-allocated Headroom**: **64 MiB** (`--gpu-headroom-mib 64`)
* **Pinned Host Pool**: **12.00 GiB** (`--host-pool-mib 12288` in Host DDR4 RAM)
* **Prefix Cache**: Host-tier memory mapped (`--prefix-cache-host-mib 8192`)
* **N-Gram Table (PLE)**: 47.68 GiB zero-copy shared memory (`/dev/shm/rad_shm_blk.*`)

---

## 4. Hardware DPM Clock Invariants

* **Active Inference MCLK**: **1258 MHz** (Full 576 GB/s GDDR6 bandwidth).
* **PowerPlay Throttling Warning**: Between idle curl requests, AMD PowerPlay downshifts MCLK to **96 MHz (DPM 0, 7.6% bandwidth)**.
* **Pre-Flight Rule**: Any benchmark or gate test run while MCLK is at 96 MHz is **invalidated** by Tier 0. Engine warm-up pulses must ensure 1258 MHz boost before timing.
