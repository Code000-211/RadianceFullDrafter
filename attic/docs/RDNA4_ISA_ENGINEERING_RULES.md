# RDNA4 (`gfx1201`) ISA Engineering Rules & Verification Standards

**Target Architecture:** AMD RDNA4 (`gfx1201`, e.g. AMD Radeon AI PRO R9700)  
**Reference Document:** AMD RDNA4 Instruction Set Architecture Specification  
**Status:** Mandatory Engineering Standard for all kernel development, compilation passes, and fusion engines.

---

## Executive Summary

Kernels targeting the AMD RDNA4 architecture (`gfx1201`) operate under strict microarchitectural realities that differ substantially from prior architectures (RDNA3, CDNA2/3) and typical GPU programming heuristics. Assumptions based on powers-of-two (e.g., 128 registers), unified cache behavior, or legacy synchronization instructions lead directly to severe performance cliffs, silent numerical corruption, or hardware exceptions.

This document establishes the **7 Non-Negotiable Engineering Ground Truths** derived directly from the RDNA4 ISA, detailing the microarchitectural rationale, the mathematical constraints, the required code patterns, and the automated verification mechanisms enforced by CI.

---

## Table of Contents
1. [Rule 1: VGPR Allocation Granularity (24 for Wave32)](#rule-1-vgpr-allocation-granularity-24-for-wave32)
2. [Rule 2: Zero-Waterfall Loop Standard](#rule-2-zero-waterfall-loop-standard)
3. [Rule 3: Dual-Issue VOPD Constraints](#rule-3-dual-issue-vopd-constraints)
4. [Rule 4: Canonical K-Ordering for GLOBAL_LOAD_TR](#rule-4-canonical-k-ordering-for-global_load_tr)
5. [Rule 5: Split Cache Temporal Hints (TH)](#rule-5-split-cache-temporal-hints-th)
6. [Rule 6: Independent Wait Counters & `s_wait_alu` Guard](#rule-6-independent-wait-counters--s_wait_alu-guard)
7. [Rule 7: Early Deallocation (`MSG_DEALLOC_VGPRS`)](#rule-7-early-deallocation-msg_dealloc_vgprs)
8. [Automated Compliance & Verification Suite](#automated-compliance--verification-suite)

---

## Rule 1: VGPR Allocation Granularity (24 for Wave32)

### 1.1 Microarchitectural Reality
On RDNA4 (`gfx1201`), each Compute Unit (CU) contains Dual SIMDs. Each SIMD has a physical Vector General Purpose Register (VGPR) file of **1536 32-bit registers** per SIMD (allocated to Wave32 wavefronts).
The hardware allocation boundary for Wave32 is strictly in **multiples of 24 VGPRs**:

$$\text{Allocated VGPRs} = \left\lceil \frac{\text{VGPR count}}{24} \right\rceil \times 24$$

The maximum number of active Wave32 wavefronts per SIMD is capped at 16 (100% theoretical occupancy). Total SIMD register capacity dictates the occupancy boundaries:

$$\text{Max Waves per SIMD} = \min\left(16, \left\lfloor \frac{1536}{\text{Allocated VGPRs}} \right\rfloor\right)$$

### 1.2 The Occupancy Cliff Table
The table below specifies the exact hardware occupancy steps on RDNA4 Wave32:

| VGPR Range (Actual) | Hardware Allocated | Waves / SIMD | Occupancy (%) | Cliff Classification |
|:---:|:---:|:---:|:---:|:---:|
| **1 – 96** | 96 | **16** | **100.0%** | Full Occupancy |
| **97 – 120** | 120 | **12** | **75.0%** | High Occupancy |
| **121 – 144** | 144 | **10** | **62.5%** | Medium-High Occupancy |
| **145 – 168** | 168 | **9** | **56.25%** | Medium Occupancy |
| **169 – 192** | 192 | **8** | **50.0%** | Half Occupancy |
| **193 – 216** | 216 | **7** | **43.75%** | Low Occupancy |
| **217 – 240** | 240 | **6** | **37.5%** | Minimum Bound for Heavy GEMM |
| **241 – 256** | 264 (clipped to 256) | **5** | **31.25%** | Extreme Spill Hazard |

### 1.3 The Power-of-Two Trap (The 128-VGPR Pitfall)
Engineers accustomed to NVIDIA or CDNA hardware frequently tune register usage to conventional powers-of-two, such as 128 VGPRs:
- **Tuning to 128 VGPRs:** The hardware allocates $\lceil 128 / 24 \rceil \times 24 = 6 \times 24 = \mathbf{144 \text{ VGPRs}}$.
- **Occupancy collapse:** 144 VGPRs limits the SIMD to $\lfloor 1536 / 144 \rfloor = \mathbf{10 \text{ waves}}$ (62.5%).
- **Tuning to 120 VGPRs:** The hardware allocates $\lceil 120 / 24 \rceil \times 24 = 5 \times 24 = \mathbf{120 \text{ VGPRs}}$, allowing $\mathbf{12 \text{ waves}}$ (75.0%).
- **The 121-VGPR Disaster:** A single spilled or unoptimized temporary register that pushes usage from 120 to 121 immediately drops occupancy from 75% to 62.5% (a 16.7% relative drop in active wavefronts).

### 1.4 Mandatory Engineering Standard
1. **Never tune to powers-of-two (64, 128, 256).** Always align kernels to the 24-VGPR boundaries: **$\le 96$**, **$\le 120$**, **$\le 144$**, **$\le 168$**, or **$\le 240$**.
2. **Danger Zone Prohibition:** Any kernel using registers in the ranges **97–104** or **121–128** is flagged by CI. These kernels incur full occupancy drops for negligible register gains and must be refactored to fit within 96 or 120 VGPRs.
3. **Launch Bounds Enforcement:** Always specify explicit launch bounds matching the intended quantum:
   ```cpp
   // Target 75% occupancy (12 waves/SIMD, max 120 VGPRs):
   __launch_bounds__(128, 3) // 128 threads/block = 4 waves. 3 blocks = 12 waves/SIMD.
   ```

---

## Rule 2: Zero-Waterfall Loop Standard

### 2.1 The Waterfall Mechanism on `gfx1201`
The RDNA4 ISA does **not** provide divergent vector register indirect addressing modes (`v[lane_idx]`).
When source code attempts to index an array stored in VGPRs using a runtime index that is not proven uniform across the wave, LLVM must emit a **waterfall serialization loop**:
```text
s_mov_b32      s[save_exec], exec_lo
<waterfall_loop>:
v_readfirstlane_b32 s[idx], v[dyn_idx]
s_and_saveexec_b32 s[tmp], s[idx]
v_movrels_b32  v[dst], v[src_base + s[idx]]
...
s_or_b32       exec_lo, exec_lo, s[tmp]
s_cbranch_execnz <waterfall_loop>
```
In a Wave32 wavefront, if all 32 lanes have distinct values for `dyn_idx`, the loop repeats **32 consecutive times serially**. What appears in C++ as a 1-cycle array lookup becomes a loop consuming hundreds to thousands of execution cycles.

### 2.2 Anti-Pattern vs. Standard

#### Anti-Pattern: Dynamic Loop Bounds or Divergent Indexing
```cpp
// DANGEROUS: Compiler cannot prove `n_own` uniform across lanes.
// Generates v_movrels_b32 inside exec-mask waterfall loops.
int n_own = 0;
for (int e = lane; e < n_experts; e += 32) {
    if (active[e]) local_tokens[n_own++] = token_ids[e];
}
// Catastrophic waterfall loop:
for (int i = 0; i < n_own; ++i) {
    accumulate(local_tokens[i]);
}
```

#### Engineering Standard: Compile-Time Constant Bounds
```cpp
// COMPLIANT: Fixed compile-time template bounds with #pragma unroll.
// Indices resolve to literal VGPR names (v0, v1, v2...) with ZERO waterfall.
template <int MAX_TOKENS>
__device__ __forceinline__ void process_tokens(...) {
    #pragma unroll
    for (int i = 0; i < MAX_TOKENS; ++i) {
        if (i < n_own) {
            accumulate(local_tokens[i]);
        }
    }
}
```

### 2.3 Enforcement
- **Hot-Path Zero-Waterfall Standard:** Disassembly of all hot prefill, decode, attention, draft, and GEMM kernels must contain **zero** `v_movrels_b32` or `v_movreld_b32` instructions.
- Automated CI scans reject any build containing waterfall loops on performance-critical paths.

---

## Rule 3: Dual-Issue VOPD Constraints

### 3.1 Architecture & Encoding
RDNA4 features a 64-bit dual-issue Vector ALU instruction format (**VOPD**) capable of issuing two independent 32-bit operations (`OpX` and `OpY`) simultaneously in a single clock cycle on a single SIMD.
- **Wave32 Exclusive:** VOPD is valid **only in Wave32 mode**. Hardware raises an illegal instruction fault if issued in Wave64 mode.
- **Asymmetric Opcode Sets:**
  - **OpX (14 opcodes, 4-bit field):** `FMAC_F32`, `FMAAK_F32`, `FMAMK_F32`, `MUL_F32`, `ADD_F32`, `SUB_F32`, `SUBREV_F32`, `MUL_DX9_ZERO_F32`, `MOV_B32`, `CNDMASK_B32`, `MAX_NUM_F32`, `MIN_NUM_F32`, `DOT2ACC_F32_F16`, `DOT2ACC_F32_BF16`.
  - **OpY (17 opcodes, 5-bit field):** All 14 opcodes of OpX, plus `ADD_NC_U32`, `LSHLREV_B32`, `AND_B32`.

### 3.2 Hardware Port & Register Bank Constraints
VOPD requires strict compliance with physical register port constraints. Hardware fails if these rules are violated:

1. **Destination VGPR Parity (Even/Odd Rule):**
   - In the instruction encoding, `vdstX` is an 8-bit register index, but `vdstY` is a 7-bit field encoding bits `[7:1]`. The least significant bit of `vdstY` is hardwired as:
   $$\text{vdstY}[0] = \sim \text{vdstX}[0]$$
   - **Rule:** One destination VGPR **must be even** and the other **must be odd**. Two even destinations or two odd destinations cannot be dual-issued.

2. **Four-Bank Conflict Rules (`reg % 4`):**
   - The SIMD VGPR file is organized into 4 independent banks:
     $$\text{Bank ID} = \text{VGPR\_INDEX} \pmod 4$$
   - Read port restriction: A bank can service only one `SRC0` read port and one `SRC1` read port per cycle.
   - **Rule:** `SRC0X` and `SRC0Y` must reside in **different banks** ($\text{src0X} \pmod 4 \ne \text{src0Y} \pmod 4$), OR they must be the **exact same VGPR**.
   - **Rule:** `VSRC1X` and `VSRC1Y` must reside in **different banks** ($\text{vsrc1X} \pmod 4 \ne \text{vsrc1Y} \pmod 4$).

3. **Dual-SRC2 Conflict Rule:**
   - Instructions reading a third operand via `SRC2` (`FMAMK_F32`, `FMAC_F32`, `DOT2ACC_F32_F16`, `DOT2ACC_F32_BF16`) share the SRC2 read port.
   - **Rule:** If both OpX and OpY read `SRC2`, **one SRC2 register must be even and the other must be odd**.

4. **Dependency & Hazard Invariant:**
   - The two operations execute in parallel. OpX must not write to any register that is read by OpY. (OpY writing to an OpX input is hardware-tolerated as operands are latched simultaneously).

---

## Rule 4: Canonical K-Ordering for `GLOBAL_LOAD_TR`

### 4.1 Transposed Matrix Loading
RDNA4 introduces hardware matrix transposition instructions: `global_load_tr_b64` (for 8-bit matrices) and `global_load_tr_b128` (for 16-bit matrices). These load a $16 \times 16$ tile from global memory and transpose it directly into VGPR fragments without intermediate LDS staging.

### 4.2 The Canonical Hardware K-Order
The hardware transpose does **not** map the reduction dimension $K$ contiguously across wavefront lanes. Instead, it places elements in AMD Canonical Hardware K-Order:

| Wavefront Lanes | Loaded K Coordinate Indices |
|:---:|:---:|
| **Lanes 0 – 15** | $k = 0, 1, 2, 3, \quad 8, 9, 10, 11$ |
| **Lanes 16 – 31** | $k = 4, 5, 6, 7, \quad 12, 13, 14, 15$ |

### 4.3 The WMMA Invariant & The Silent Corruption Hazard
The matrix multiply-accumulate instruction calculates:

$$D[m][n] = \sum_{k=0}^{15} A[m][k] \times B[k][n]$$

Addition is commutative, so any permutation of the summation indices $k$ produces bit-identical output **if and only if both Operand A and Operand B follow the exact same permutation**.

```text
[CRITICAL HAZARD: SILENT NUMERICAL CORRUPTION]
If Operand A is loaded via GLOBAL_LOAD_TR_B128 (canonical K-order: 0,1,2,3, 8,9,10,11...)
AND Operand B is loaded from LDS or memory in standard linear order (0,1,2,3, 4,5,6,7...),
the WMMA unit multiplies mismatched terms:
  A[m][8] * B[4][n] + A[m][9] * B[5][n] ...
The kernel compiles cleanly, executes without error, but outputs complete garbage!
```

### 4.4 Mandatory Engineering Standard
1. **Identical K-Permutation Contract:** If either operand to a WMMA instruction is loaded via `global_load_tr`, the other operand must be transformed to match the canonical K-order.
2. **Never mix linear LDS layouts with `global_load_tr` without reordering:** All shared memory staging buffers or dequantization unpackers must use the canonical mapping:
   ```cpp
   // Canonical K slot mapping for lane-half h (l / 16) and index j:
   // Lanes 0..15 (h=0) map to {0,1,2,3, 8,9,10,11}
   // Lanes 16..31 (h=1) map to {4,5,6,7, 12,13,14,15}
   __device__ __forceinline__ int canonical_k_index(int lane, int j) {
       int h = lane / 16;
       int base = (j < 4) ? (h * 4 + j) : (8 + h * 4 + (j - 4));
       return base;
   }
   ```
3. **Structured Sparse Hazard:** `v_swmmac` sparse instructions bind selector bits directly to hardware K-groups. `global_load_tr` cannot be used with sparse WMMA unless selector indices are explicitly permuted.

---

## Rule 5: Split Cache Temporal Hints (`TH`)

### 5.1 RDNA4 Multi-Level Cache Architecture
`gfx1201` organizes memory caching into two distinct tiers:
- **Near Cache:** Compute Unit Vector L0 Cache (32 KiB per WGP/CU, high bandwidth, private to CU).
- **Far Cache:** Cluster/Shared L2 Cache (4–8 MiB, shared across all CUs) and Memory/MALL.

The 3-bit Temporal Hint (`TH`) field in memory instructions directly programs line replacement and bypass policies for both near and far caches.

### 5.2 TH Encoding Policies

| Field Value | Mnemonic | Near Cache (L0) Policy | Far Cache (L2) Policy | Recommended Workload |
|:---:|:---:|:---:|:---:|:---|
| **0** | `RT` | Regular Temporal | Regular Temporal | General read-write, high-locality data |
| **1** | `NT` | Non-Temporal (Bypass) | Non-Temporal (Bypass) | Streaming writebacks, single-pass buffers |
| **2** | `HT` | High-Priority Temporal | High-Priority Temporal | Hot lookup tables, frequently reused scalars |
| **3** | `LU` | Last-Use (Discard) | Last-Use (Discard) | Intermediates consumed immediately |
| **4** | `NT_RT` | **Non-Temporal (Bypass)** | **Regular Temporal** | **Weight Streaming (LLM Matrix Weights)** |
| **5** | `RT_NT` | Regular Temporal | Non-Temporal | Private working sets not shared across CUs |
| **6** | `NT_HT` | **Non-Temporal (Bypass)** | **High-Priority Temporal** | **Stationary Layer Weights in Shared L2** |

### 5.3 Weight Streaming vs. Cache Thrashing Standard
In LLM inference, layer weight matrices stream gigabytes of data through the CUs:
- If loaded with default `TH = RT (0)`, weight streaming completely evicts the small 32 KiB L0 vector cache on every wave, flushing hot KV-cache lines and activation intermediates.
- **Rule:** All weight streaming loads across layers must explicitly use **`TH = NT_RT (4)`** or **`NT_HT (6)`**. This bypasses CU L0 to preserve activation/KV cache locality while retaining reusable weight lines in shared L2.
- **Rule:** Last-use activation buffers (read once before kernel termination) must use **`TH = LU (3)`** to evict dirty lines immediately without memory writeback overhead.
- **Rule:** Final output buffers must use streaming non-temporal store hints: **`TH = NT (1)`**.

---

## Rule 6: Independent Wait Counters & `s_wait_alu` Guard

### 6.1 The Deprecation of Unified `s_waitcnt`
Prior AMD architectures relied on the unified `s_waitcnt` instruction with packed bitfields. On RDNA4, `s_waitcnt` is legacy and deprecated.
The ISA provides **independent, decoupled hardware counters**:

| Instruction | Hardware Counter | Tracks Completion Of |
|:---|:---:|:---|
| `s_wait_loadcnt <N>` | `LOADcnt` (6 bits) | Vector memory loads, atomic-with-return (Global, Scratch, Flat, Buffer) |
| `s_wait_storecnt <N>` | `STOREcnt` (6 bits) | Vector memory stores, atomic-without-return |
| `s_wait_dscnt <N>` | `DScnt` (6 bits) | Local Data Share (LDS) loads/stores and Flat LDS ops |
| `s_wait_kmcnt <N>` | `KMcnt` (5 bits) | Constant/Scalar memory loads (SMEM) and `s_sendmsg` completions |
| `s_wait_samplecnt <N>`| `SAMPLEcnt` (6 bits)| Image sampling operations |
| `s_wait_bvhcnt <N>` | `BVHcnt` (3 bits) | Ray-tracing BVH queries |

**Engineering Standard:** Never emit legacy `s_waitcnt`. Always use the explicit instruction matching the resource being synchronized.

### 6.2 The `s_wait_alu` Pipeline Hazard Guard
On `gfx1201`, the hardware scoreboard does not automatically stall for all inter-ALU register dependencies across SALU and VALU boundaries. Software must insert `s_wait_alu` guards when SGPRs or VCC are transferred between ALU pipelines:

1. **VALU write to VCC $\rightarrow$ VALU read of VCC:**
   Must be guarded with:
   ```text
   s_wait_alu 0xFFFD
   ```
2. **VALU write to SGPR $\rightarrow$ VALU read of SGPR:**
   Must be guarded with:
   ```text
   s_wait_alu 0xF1FF
   ```
3. **SALU write to SGPR/VCC $\rightarrow$ SALU or VALU read of SGPR/VCC:**
   Must be guarded with:
   ```text
   s_wait_alu 0xFFFE
   ```
Failure to insert these guards produces non-deterministic pipeline data races that occur only under specific SIMD clock skew conditions.

---

## Rule 7: Early Deallocation (`MSG_DEALLOC_VGPRS`)

### 7.1 The Epilogue Occupancy Stall Problem
In standard kernel epilogues, the wave issues global memory stores and then waits for completion:
```text
global_store_b128  v[addr], v[data]
s_wait_storecnt 0     ; STALL: waits hundreds of cycles for memory acknowledgment
s_endpgm              ; VGPRs held until this instruction retires!
```
While waiting on `s_wait_storecnt 0`, the wavefront is entirely idle, yet it continues to hold its full allocation of up to 256 VGPRs on the SIMD. New wavefronts waiting to be dispatched to the SIMD are blocked by register starvation.

### 7.2 The Early Deallocation Standard
RDNA4 provides the `MSG_DEALLOC_VGPRS` message via `s_sendmsg`:
```text
s_sendmsg sendmsg(MSG_DEALLOC_VGPRS)
```
The microarchitecture permits register deallocation while `STOREcnt` is non-zero, provided all store operands have been latched into memory buffers.

#### Required Epilogue Sequence:
```text
global_store_b128  v[addr], v[data]      ; Final store issued
s_sendmsg          sendmsg(MSG_DEALLOC_VGPRS) ; IMMEDIATELY release all VGPRs
s_wait_storecnt    0                     ; Wait for stores while occupying 0 VGPRs
s_endpgm                                 ; Terminate wavefront
```
**Impact:** Releasing the VGPRs before the store wait allows the SIMD hardware scheduler to immediately launch the next waiting wave, hiding memory commit latency and dramatically increasing sustained occupancy.

---

## Automated Compliance & Verification Suite

To guarantee that no code violating these 7 rules enters production, the project provides an automated compliance engine:

### Script: `scripts/check_isa_compliance.sh`
The compliance checker inspects compiled binaries (`libr4d.so`, `.co` code objects, or `.hip.o` build artifacts) and verifies:
1. **VGPR Cliff Scanner:** Flags all kernels in danger zones ($B < \text{VGPR} \le B + 8$ for $B \in \{96, 120, 144, 168, 192, 216, 240\}$).
2. **Waterfall Disassembly Scanner:** Scans disassembly for `v_movrels` / `v_movreld` instructions and exec-masked serialization loops on hot paths (`decode`, `prefill`, `gemm`, `attn`, `draft`).
3. **Scratch Spill Scanner:** Analyzes `.private_segment_fixed_size` and alerts on any prefill or decode kernel with non-zero scratch memory or spilled registers.

### Shared Architecture Specification Header: `arch/common/rad_rdna4_isa.h`
The 7 core rules and their hardware constants, occupancy calculators, VOPD validators, canonical K-order permutations, and temporal hint definitions are codified into `arch/common/rad_rdna4_isa.h` (accessible via `<arch/rad_rdna4_isa.h>`), providing reusable `constexpr` functions and types for kernel developers and test suites:
- `rad::isa::rdna4::allocated_vgprs_wave32(int vgpr)`
- `rad::isa::rdna4::simd_occupancy_waves(int vgpr)`
- `rad::isa::rdna4::simd_occupancy_pct(int vgpr)`
- `rad::isa::rdna4::is_in_cliff_danger_zone(int vgpr)`
- `rad::isa::rdna4::vopd_valid_dest_parity(int dstX, int dstY)`
- `rad::isa::rdna4::vopd_valid_bank_pairing(int srcX, int srcY)`
- `rad::isa::rdna4::vopd_valid_dual_src2(int src2X, int src2Y)`
- `rad::isa::rdna4::canonical_k_order(int lane, int slot)`
- `rad::isa::rdna4::th_is_weight_streaming(TemporalHint th)`
- `rad::isa::rdna4::th_is_last_use(TemporalHint th)`
- `rad::isa::rdna4::th_is_streaming_store(TemporalHint th)`

### Unit Test Integration: `tests/arch_test`
Core ISA invariants, 24-VGPR occupancy math, VOPD bank conflicts, canonical K-order permutations, and cache hint mappings are asserted directly against `<arch/rad_rdna4_isa.h>` in `tests/arch_test.cpp`.
