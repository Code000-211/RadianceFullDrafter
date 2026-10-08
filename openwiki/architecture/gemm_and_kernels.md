---
type: architecture
title: RDNA4 Kernel Architecture & GEMM
description: Microarchitectural principles of AMD RDNA4 (gfx1201) compute kernels, Wave32 scheduling, 24-VGPR allocation granularity, and W4A8 GEMM optimization.
tags: [rdna4, gfx1201, gemm, wave32, vgpr, lds]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-99ec9b0861eccdfb5d335690
    resource: repo://libr4d/r4d_gemm_w4a8_prefill.hip
  - id: openwiki-source-8afc9001d7a1d5e25f7ac1ee
    resource: repo://scripts/check_isa_compliance.py
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# RDNA4 Kernel Architecture & GEMM

RadianceMine compiles and optimizes compute kernels specifically for AMD RDNA4 (`gfx1201`, AMD Radeon AI PRO R9700). High arithmetic intensity and peak memory bandwidth utilization depend on strict compliance with RDNA4 hardware constraints.

## 1. Wave32 Scheduling & Dual-Issue VOPD

The `gfx1201` compute unit executes in native Wave32 mode (32 threads per wave).
- **Dual-Issue VOPD**: Where independent vector instructions exist, the Dual-Issue Vector Operation (VOPD) unit pairs select ALU operations, executing two independent vector operations per cycle per SIMD.
- **Wavefront Concurrency**: To hide memory latency to the 576 GB/s GDDR6 subsystem, kernels target 8 active waves per SIMD unit.

## 2. The 24-VGPR Allocation Granularity & Occupancy Cliffs

Unlike earlier architectures that allocated Vector General Purpose Registers (VGPRs) in 8- or 16-register increments, RDNA4 allocates VGPRs strictly in **24-VGPR granularities**:
- **Occupancy Boundaries**: Key VGPR cliff thresholds are at 96, 120, 144, 168, and 192 registers.
- **The Occupancy Cliff**: A kernel using 96 VGPRs maintains full 8-wave occupancy. Exceeding this boundary by even a single register (e.g., 97 VGPRs) immediately causes the hardware allocator to reserve 120 VGPRs, dropping maximum occupancy from 8 waves to 6 waves (~25% throughput penalty).
- **Tier 3 ISA Invariant**: The automated quality gate (`scripts/check_isa_compliance.py`) parses ELF disassembly and rejects kernels within 2 registers of an unapproved cliff or kernels that spill to scratch memory.

## 3. LDS 64 KiB Bank Layout & Conflict Avoidance

Each Compute Unit contains 64 KiB of Local Data Share (LDS) structured as 32 independent memory banks (4 bytes per bank).
- **Bank Conflicts**: When multiple lanes within a Wave32 access distinct addresses residing in the same memory bank, requests serialize, stalling the execution pipeline.
- **Swizzling Standard**: Intermediate tiles in prefill GEMM and fused MoE routing use XOR swizzling patterns on LDS indices to ensure zero-conflict parallel reads and writes.

## 4. W4A8 Prefill GEMM Implementation

In `libr4d/r4d_gemm_w4a8_prefill.hip`:
- Weights are packed as INT4 values and activations as FP8/BF16.
- Global memory reads utilize coalesced 128-bit vector loads (`dwordx4`).
- Epilogues deallocate VGPRs early where appropriate via `s_sendmsg(MSG_DEALLOC_VGPRS)` to overlap register reclamation with subsequent AQL queue packet execution.
