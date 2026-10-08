---
type: architecture
title: Dual-GPU P2P Interconnect & All-Reduce
description: Architecture of peer-to-peer All-Reduce across dual AMD Radeon AI PRO R9700 cards, WHT6 wire encoding, unified virtual addressing, and store-drain barrier synchronization.
tags: [interconnect, p2p, all-reduce, pcie, wht6, fences]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-85622e4970abb84e5757f84b
    resource: repo://libr4d/r4d_ar_entry.hip
  - id: openwiki-source-8a8ee568d86e03124fb41627
    resource: repo://scripts/eval_patch_safety.py
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# Dual-GPU P2P Interconnect & All-Reduce

Dual AMD Radeon AI PRO R9700 (gfx1201) systems communicate across a dedicated PCIe 4.0 x16 slot-to-slot interconnect. Inter-card communication delivers ~28.29 GB/s DMA and ~16.95 GB/s bidirectional Peer-to-Peer (P2P) throughput.

## 1. Single-Process Unified Virtual Addressing

Unlike multi-process runtime architectures that require `hipIpcGetMemHandle` serialization and handle marshalling:
- **Unified Address Space**: RadianceMine executes as a single process with dedicated POSIX threads per rank.
- **Direct P2P Mapping**: When `hipDeviceEnablePeerAccess` executes during engine initialization, device pointers allocated on GPU Rank 0 become directly readable and writable by GPU Rank 1 without address translation or IPC handle overhead.
- **Rendezvous Contract**: Rank synchronization handshakes occur via peer signal buffers allocated in device memory before step execution begins.

## 2. WHT6 Two-Rank One-Shot All-Reduce

The tensor-parallel All-Reduce (`r4d_rad_ar_oneshot_2rank_wht6`) utilizes a one-shot collective strategy:
- Rather than a traditional two-phase Reduce-Scatter followed by All-Gather, Rank 0 and Rank 1 stream complementary halves of the hidden activation directly into each other's reduction buffers.
- **WHT6 Rotation**: For select activations, Walsh-Hadamard 6-bit rotation reduces numerical quantization variance across the bus without compromising gradient precision.

## 3. Memory Fences & The Store-Drain Invariant

A critical hardware performance hazard on PCIe 4.0 interconnects is broadcast memory fence saturation:
- **The Per-Thread Fence Hazard**: Calling `__threadfence_system()` across all 1024 threads in a workgroup broadcasts 1024 concurrent memory fences across PCIe, stalling both compute waves and the memory controller.
- **The Store-Drain Standard**: Synchronization must be executed by the workgroup leader (`if (threadIdx.x == 0)`) paired with `s_wait_storecnt` or atomic peer flag release.
- **Automated Verification**: `scripts/eval_patch_safety.py` deterministically scans all incoming patches and rejects unconditional per-thread `__threadfence_system()` invocations.
