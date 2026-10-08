# EXHAUSTIVE FORENSIC ROOT-CAUSE ANALYSIS & AUTOPSY: OPT1 TO OPT190+
## The Architecture, Trajectory, Regressions, and Lost Levers of Radiance Native Engine

**Author**: Antigravity Autonomous Systems Engineering & Forensic Audit Group  
**Date**: October 8, 2026  
**Target Platform**: Dual AMD Radeon AI PRO R9700 (`gfx1201`, RDNA4, 64 CUs, 576 GB/s GDDR6, PCIe 4.0 x16 slot-to-slot, TP2 `--tp-wire wht6`)  
**Target Architecture**: `qwen4exp_fp8` (Qwen3.8-Flash-Next, 113B MoE / 512 Experts, Top-10 Routing, GDN Linear Recurrence, PLE N-Gram Lookups, MTP Speculative Decoding)  
**Scope**: Full Development Lifecycle from Opt1 (Opt33 Baseline) through Arms 1–14 to Opt 190+ (Commit `2206cdf` / `opt146_clean_restored`)  
**Status**: Definitive Forensic Reference Document  

---

## TABLE OF CONTENTS
1. [Executive Meta-Postmortem & The Central Engineering Paradox](#1-executive-meta-postmortem--the-central-engineering-paradox)
2. [Comprehensive Trajectory Matrix: Historical Peaks, Valleys & Milestones](#2-comprehensive-trajectory-matrix-historical-peaks-valleys--milestones)
3. [Detailed Chronological Autopsy Across Ten Epochs (Opt 1 to Opt 190+)](#3-detailed-chronological-autopsy-across-ten-epochs-opt-1-to-opt-190)
   - [Epoch 1: Opt 1 – Opt 33 (The Clean RDNA4 Bringup & Golden Baseline)](#epoch-1-opt-1--opt-33-the-clean-rdna4-bringup--golden-baseline)
   - [Epoch 2: Opt 34 – Opt 65 (Pipeline Repair, Triple Buffering & Peak C8 Concurrency)](#epoch-2-opt-34--opt-65-pipeline-repair-triple-buffering--peak-c8-concurrency)
   - [Epoch 3: Opt 66 – Opt 87 (Advanced PLE Caching, Wave-Shuffle & The Clav Disaster)](#epoch-3-opt-66--opt-87-advanced-ple-caching-wave-shuffle--the-clav-disaster)
   - [Epoch 4: Opt 88 – Opt 100 (Greedy Precision Peaks vs High-Entropy Collapse)](#epoch-4-opt-88--opt-100-greedy-precision-peaks-vs-high-entropy-collapse)
   - [Epoch 5: Opt 101 – Opt 122 (The Calibrated Burst Ladder & Single-Stream Peaks)](#epoch-5-opt-101--opt-122-the-calibrated-burst-ladder--single-stream-peaks)
   - [Epoch 6: Opt 123 – Opt 134 (The Barrier Crisis & Fast-Drain Recovery)](#epoch-6-opt-123--opt-134-the-barrier-crisis--fast-drain-recovery)
   - [Epoch 7: Opt 135 – Opt 146 (RidgeFill Integration & Peak Run 146)](#epoch-7-opt-135--opt-146-ridgefill-integration--peak-run-146)
   - [Epoch 8: Opt 147 – Opt 180 (Upstream v1.2.2 Merge, CED Stacking & Silent Degradation)](#epoch-8-opt-147--opt-180-upstream-v122-merge-ced-stacking--silent-degradation)
   - [Epoch 9: Opt 181 – Opt 187 (The Parity Crisis & Forensic Recovery Attempt)](#epoch-9-opt-181--opt-187-the-parity-crisis--forensic-recovery-attempt)
   - [Epoch 10: Opt 188 – Opt 190+ (Multi-Agent Blind Stacking, Fused Router Regressions, and the 75 t/s Freefall)](#epoch-10-opt-188--opt-190-multi-agent-blind-stacking-fused-router-regressions-and-the-75-ts-freefall)
4. [Granular Root-Cause Analysis of Every Major Performance Drop](#4-granular-root-cause-analysis-of-every-major-performance-drop)
   - [Regression Drop 1: C8 Concurrency Collapse (534.8 t/s -> 419.5 t/s -> 262.4 t/s)](#regression-drop-1-c8-concurrency-collapse-5348-ts---4195-ts---2624-ts)
   - [Regression Drop 2: Single-Stream & Parity Collapse (247.8 t/s -> 103.9 t/s -> 75.6 t/s)](#regression-drop-2-single-stream--parity-collapse-2478-ts---1039-ts---756-ts)
   - [Regression Drop 3: Prefill Throughput Collapse (9,353.5 t/s -> 5,991 t/s -> 3,219 t/s -> 4,642 t/s)](#regression-drop-3-prefill-throughput-collapse-93535-ts---5991-ts---3219-ts---4642-ts)
   - [Regression Drop 4: Catastrophic Token Degeneration (`bdbdbd` Loop) and Process Crashes](#regression-drop-4-catastrophic-token-degeneration-bdbdbd-loop-and-process-crashes)
5. [Why Were Regressions Accepted and Compounded? (Systemic Engineering Pathology)](#5-why-were-regressions-accepted-and-compounded-systemic-engineering-pathology)
   - [The Absence of a Standardized Composite Score & The Frozen Baseline Trap](#the-absence-of-a-standardized-composite-score--the-frozen-baseline-trap)
   - [The 'Blind Stacking' Anti-Pattern](#the-blind-stacking-anti-pattern)
   - [Audit Theater, Verification Gaps & False Passes](#audit-theater-verification-gaps--false-passes)
6. [The 'Lost Optimization Levers' Phenomenon (Exhaustive Catalog & Matrix)](#6-the-lost-optimization-levers-phenomenon-exhaustive-catalog--matrix)
7. [Destructive Engineering Habits & Operational Pathology](#7-destructive-engineering-habits--operational-pathology)
8. [Definitive Architectural Roadmap: The True Path to Peak State](#8-definitive-architectural-roadmap-the-true-path-to-peak-state)

---

## 1. EXECUTIVE META-POSTMORTEM & THE CENTRAL ENGINEERING PARADOX

Over the course of 271 benchmark runs, 14 architectural arms, and more than 190 optimization iterations between October 5 and October 8, 2026, the Radiance Native Engine development effort produced some of the highest recorded single-kernel efficiencies on modern AMD RDNA4 (`gfx1201`) hardware:

- **C8 Concurrency Aggregate Peak**: **534.77 tok/s** (`arm14_spec3_warm`, October 6)
- **Cold 64k Prefill Throughput Peak**: **9,353.50 tok/s** (`opt142_thinking_baseline`, October 7)
- **Cached 64k Prefill Throughput Peak**: **116,472.73 tok/s** (`opt83_fixed_4way_rlfu`, October 6)
- **Single-Stream Decode Median Peak**: **235.50 tok/s** (`opt114_opt96_ladder`, October 7)
- **Subcategory Single-Stream Peaks**: **283.97 tok/s** JSON (`opt121`), **257.44 tok/s** Code (`opt119`), **259.58 tok/s** File Edit (`opt122`), **251.08 tok/s** Math (`opt115`)

Yet, on the morning of October 8, 2026, the state of the active engine reached an unprecedented low:
- In `2026-10-08_084817_opt146_clean_restored`, the engine achieved only **75.6 tok/s** C1 Decode, **4,642.1 tok/s** Cold Prefill, and **262.4 tok/s** C8 Concurrency, yielding an overall BetterBench Composite Score of **302.6 / 1000**.
- Parity tests in intermediate iterations (`opt184`, `opt191`) experienced catastrophic speed collapses down to **103.9 tok/s** and **27.8 tok/s**.
- Sustained concurrency testing degenerated into repetitive byte token loops (`bdbdbd`), followed by SIGSEGV and process crashes with socket connection refusals (`[Errno 111] Connection refused`).

```mermaid
flowchart TD
    A["Opt 33 Baseline (192.5 t/s C1 | 474.9 t/s C8 | 6.8k Prefill)"] --> B["Opt 65 / Arm 14 (205.4 t/s C1 | 534.8 t/s C8 Peak)"]
    B --> C["Opt 83-86 PLE Caching (116.5k t/s Cached | 531.4 t/s C8)"]
    C --> D["Opt 114-122 Calibrated Ladder (235.5 t/s C1 Peak | 284 t/s JSON)"]
    D --> E["Opt 140-146 RidgeFill Peak (9.3k t/s Prefill Peak | 222.7 t/s C1)"]
    E -. "Upstream v1.2.2 Merge + __threadfence_system + RADIANCE_NO_OVERLAP=1" .-> F["Opt 152-153 Regression (181.3 t/s C1 | 273.7 t/s C8 | 6.1k Prefill)"]
    F -. "MoE Gating Fallback p<0.25 + Stager start_wrap Deleted" .-> G["Opt 184-186 Parity & Prefill Collapse (103.9 t/s Parity | 3.6k Prefill)"]
    G --> H["Opt 187-188 Recovery (201.0 t/s C1 | 423.3 t/s C8 | 5.9k Prefill)"]
    H -. "Opt 189 Fused Router + Opt 190 MTP KV + State Clear Race" .-> I["Opt 189-191 & bdbdbd Collapse (154.1 t/s C1 | 240.5 t/s C8 | 3.2k Prefill)"]
    I -. "Desperate Hard Reset to 1a4455d without Environment Tuning" .-> J["Opt 146 Clean Restored (Run 084817) (75.6 t/s C1 | 262.4 t/s C8 | 4.6k Prefill | Score: 302.6)"]
```

### The Central Engineering Paradox
The paradox of Radiance Native Engine development is that **every individual subsystem problem was solved brilliantly in isolation**, but **the system as a whole was systematically destroyed by the manner in which those solutions were integrated, evaluated, and maintained**.

1. **The Component Breakthrough / Systemic Regression Divergence**: Groundbreaking isolated kernel developments (such as W4A8 swizzled prefill with VOPD, 4-way set-associative RLFU caching, wave-shuffle vectorization, and RidgeFill) were repeatedly pushed into master. However, because each feature was stacked without regression gates across the full multi-objective matrix, a gain in prefill frequently came at the cost of a 50% collapse in concurrency, or an optimization for code generation triggered a crash loop in math and prose.
2. **Local Maxima Blindness**: Because developers and automated subagents evaluated candidates exclusively against the static `baseline_opt33.json` anchor (192.5 tok/s decode, 474.9 tok/s C8), an optimization that achieved 205 tok/s decode was declared a "success" and merged—even if that same commit obliterated the 534 tok/s concurrency achieved in Arm 14 or cut prefill from 9.3k back to 6k. The engineering team celebrated local victories while suffering catastrophic global retreat.
3. **Destructive Engineering Hygiene**: Codebases were modified live without clean worktree isolation. Reverts and git resets were executed as blunt trauma instruments, erasing entire production-grade kernels (`libr4d/r4d_kv_anchor_pool4.hip`, `arch/common/rad_block_attn_paged_fp8.h`, `start_wrap`). Merges from upstream repositories were certified as "clean passes" based on tests run against obsolete branches 75 commits behind. Synchronization primitives (`__threadfence_system()`, `rad_event_sync()`) were inserted recklessly to silence timing bugs, suffocating the PCIe fabric and serializing asynchronous compute streams.
---

## 2. COMPREHENSIVE TRAJECTORY MATRIX: HISTORICAL PEAKS, VALLEYS & MILESTONES

The following table represents the ground-truth forensic log extracted directly from `benchmarks/runs/` results across the entire project lifecycle:

| Milestone / Run ID | Date & Timestamp | Single-Stream C1 Decode | Cold 64k Prefill | C8 Concurrency Aggregate | BetterBench Composite | Primary Engineering Event / Architectural Mechanism |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Opt 33 Baseline** (`baseline_warm`) | 2026-10-05 20:02:23 | 204.2 t/s (192.5 ref) | 6,870.3 t/s | 474.5 t/s (474.9 ref) | 654.1 pts | Golden Baseline. Native HIP gfx1201 port, W4A8 MoE GEMM, TP2 WHT6 P2P AR. |
| **Arm 14 Peak C8** (`arm14_spec3_warm`) | 2026-10-06 12:46:08 | 205.4 t/s | 103,502.9 t/s (cached) | **534.77 t/s** | **746.1 pts** | **All-Time C8 Peak**. Async stream pipelining active, `s_wait_storecnt 0x0` drain, MTP Spec-3. |
| **Opt 41** (`opt41_triple_buffer`) | 2026-10-06 14:44:08 | 201.2 t/s | 6,825.1 t/s | 468.2 t/s | 632.4 pts | 3-buffer prefill ring pipeline (`RADIANCE_PREFILL_BUFFERS=3`) introduced. |
| **Opt 46** (`opt46_live`) | 2026-10-06 15:18:30 | 201.7 t/s | 103,115.7 t/s (cached) | 508.0 t/s | 729.4 pts | 30-dispatch hold-down lease in heat engine active. High concurrency stability. |
| **Opt 65 Golden Anchor** (`opt65_eval`) | 2026-10-06 18:23:52 | 205.6 t/s | 6,785.5 t/s | 454.4 t/s | 626.2 pts | Certified release anchor `release/opt65_golden`. Balanced reference. |
| **Opt 82 Drop** (`opt82_clean_baseline`) | 2026-10-06 21:15:11 | 197.6 t/s | 6,740.3 t/s | **116.2 t/s** | 533.1 pts | **Early C8 Drop**: Interconnect contention and disabled ballot loop in MoE decode. |
| **Opt 83 Cached Peak** (`opt83_fixed_4way_rlfu`) | 2026-10-06 21:22:14 | 147.8 t/s | **116,472.7 t/s** | 531.4 t/s | 466.9 pts | **All-Time Cached Prefill Peak**. 4-way set-associative RLFU L1 VRAM cache. |
| **Opt 86** (`opt86_ple_bf16_spec3`) | 2026-10-06 21:48:48 | 204.2 t/s | 6,783.0 t/s | 464.6 t/s | 643.6 pts | Wave-shuffle single-wave vectorization & dequantized BF16 L1 VRAM cache. |
| **Opt 87 Clav Crisis** (`d6db162` -> `715b71f`) | 2026-10-06 22:30:00 | *Aborted* | *N/A* | *N/A* | *Failed* | Clav PLE kernel integration: 1-ULP drift & wildcard GEMM interception broke MTP. Reverted. |
| **Opt 89 Precision Peaks** (`opt89_clean_precision`) | 2026-10-07 00:39:01 | 206.1 t/s | 6,242.6 t/s | 239.0 t/s | 412.3 pts | Greedy precision records: Reasoning 250.5 t/s, Summarization 237.0 t/s. C8 throttled. |
| **Opt 90 Prose Peak** (`opt90_adaptive_depth5_fixed`) | 2026-10-07 00:53:11 | 173.8 t/s | 6,390.0 t/s | 223.2 t/s | 378.7 pts | Prose peak 221.8 t/s under greedy. Concurrency suffered from draft contention. |
| **Opt 100 Anchor** (`opt100_calibrated`) | 2026-10-07 02:59:29 | 166.4 t/s | 6,723.6 t/s | 377.2 t/s | 453.7 pts | Calibrated benchmark baseline. Fixed depth-2 trap, prefetch audit initiated. |
| **Opt 114 SOTA Decode Peak** (`opt114_opt96_ladder`) | 2026-10-07 05:25:23 | **235.5 t/s** | 6,744.0 t/s | 404.5 t/s | 618.0 pts | **All-Time Decode Median Peak**. Calibrated speculative burst ladder (Depth 4/5). |
| **Opt 119 Code Peak** (`opt119_low_accept_clamp`) | 2026-10-07 06:19:23 | 224.7 t/s | 6,729.0 t/s | 423.0 t/s | 609.3 pts | **All-Time Code Peak: 257.44 t/s**. Low-acceptance fallback clamp. |
| **Opt 121 JSON Peak** (`opt121_tight3_burst_c8burst`) | 2026-10-07 06:29:46 | 229.1 t/s | 6,758.7 t/s | 407.3 t/s | 615.6 pts | **All-Time JSON Peak: 283.97 t/s**. Tight 3-burst ladder for structured syntax. |
| **Opt 122 File Edit Peak** (`opt122_calibrated_burst`) | 2026-10-07 06:42:12 | 230.4 t/s | 6,751.9 t/s | 424.3 t/s | 605.1 pts | **All-Time File Edit Peak: 259.58 t/s**. Calibrated streak triggers. |
| **Opt 123 The Barrier Crisis** (`opt123_ttft_and_placement`) | 2026-10-07 07:35:40 | 216.0 t/s | 5,416.5 t/s | **66.0 t/s** | 451.4 pts | **The Barrier Collapse**: `s_wait_storecnt 0x0` replaced with `__threadfence_system()`. C8 collapsed. |
| **Opt 129 Recovery** (`opt129_certified`) | 2026-10-07 09:09:37 | 217.5 t/s | 8,931.3 t/s | 451.1 t/s | 666.3 pts | System fence removed; prefill staging buffers optimized. Staggering prefill recovery. |
| **Opt 140 Peak** (`opt140_certified`) | 2026-10-07 11:55:15 | 222.7 t/s | 9,279.0 t/s | 464.7 t/s | 685.2 pts | Certified all-around peak. RidgeFill preliminary integration, speed mode. |
| **Opt 142 All-Time Prefill Peak** (`opt142_thinking_baseline`) | 2026-10-07 12:34:18 | 185.0 t/s | **9,353.5 t/s** | 463.6 t/s | 633.6 pts | **All-Time Cold 64k Prefill Peak**. Swizzled VOPD GEMM, RidgeFill `speed` (`TAIL=512`). |
| **Opt 146 Peak Run** (`opt146_calibrated_ladder`) | 2026-10-07 13:24:02 | 205.2 t/s | 9,331.8 t/s | 448.2 t/s | 631.3 pts | Golden pre-merge peak. RidgeFill + CED predictive prefetch + RDNA4 optimizations. |
| **Opt 152 Drop** (`opt152_restored_clean`) | 2026-10-07 17:03:05 | 179.4 t/s | 3,962.2 t/s | 337.0 t/s | 389.9 pts | Upstream v1.2.2 merge fallout. RidgeFill disabled, dynamic spec divergence. |
| **Opt 153 Repair** (`opt153_quality_calibrated`) | 2026-10-07 17:14:59 | 181.3 t/s | 6,115.3 t/s | **273.7 t/s** | 403.5 pts | `RADIANCE_NO_OVERLAP=1` added to stop crash; `__threadfence_system()` quietly re-introduced. |
| **Opt 183 Baseline** (`opt183_adaptive_tier4_pld_bounded`) | 2026-10-08 01:45:17 | 197.3 t/s | 5,777.3 t/s | 423.2 t/s | 556.4 pts | Pre-cleanup stable baseline. Floor 3 MTP, parity at 234 t/s. |
| **Opt 184 Parity Collapse** (`opt184_clean_vram_reclaimed`) | 2026-10-08 02:15:37 | ~103 t/s Parity | *Degraded* | *Degraded* | *Failed* | **MoE Gating Fallback Trap**: $p < 0.25 \implies d=1$ forced single-token decode. Parity collapsed. |
| **Opt 186 Prefill Collapse** (`opt186_prefill3buf_c8opt`) | 2026-10-08 02:35:23 | 189.4 t/s | **3,680.2 t/s** | 393.8 t/s | 492.9 pts | **Stager Wrap Deleted**: `start_wrap` removed; GPU paused 180ms after every chunk. |
| **Opt 187 Restored** (`opt187_restored_burst_and_wrap`) | 2026-10-08 02:46:42 | 201.0 t/s | 5,991.2 t/s | 423.3 t/s | 553.1 pts | Restored `start_wrap` (+62.8% prefill) and MTP streak clamp (`suggest_depth()`). |
| **Opt 188 Restored Depth 5** (`opt188_depth5_restored`) | 2026-10-08 03:04:58 | 195.4 t/s | 5,993.0 t/s | 419.5 t/s | 540.7 pts | Restored Depth 5 ceiling. Pre-test gate 4/4 PASS. Stable state before final collapse. |
| **Opt 189 Fused Router Drop** (`archive_..._opt189_regressed_fused_router`) | 2026-10-08 03:53:00 | 196.8 t/s | **3,659.3 t/s** | **240.5 t/s** | *Net Regress* | **Fused Router Disaster**: Experimental router GEMM shattered prefill (-46.8%) and C8 (-49.4%). |
| **Opt 190 MTP KV Crash** (`opt190_mtp_kv_fix_clean`) | 2026-10-08 04:05:50 | **154.1 t/s** | **3,219.8 t/s** | **266.5 t/s** | 328.7 pts | **Systemic Breakdown**: Single-stream collapsed -20.7%, prefill -53.0%, C8 -43.9%. |
| **Opt 191 Prose Stall & Loop** (`opt191_restored_clean`) | 2026-10-08 04:47:19 | *Stalled* | *Stalled* | *Stalled* | *Incomplete* | Parity speed collapsed to 27.8 t/s. Engine stalled during prose; `bdbdbd` loop corruption. |
| **Baseline Opt188 Certified** (`baseline_opt188_certified`) | 2026-10-08 06:49:12 | 154.6 t/s | 3,542.7 t/s | 278.0 t/s | 326.5 pts | Stale worktree verification. C8 and prefill remained broken. |
| **Baseline Opt188 Reverified** (`baseline_opt188_reverified`) | 2026-10-08 08:11:27 | 150.5 t/s | 3,979.7 t/s | 260.7 t/s | 315.1 pts | Reverification confirmed persistent 40% loss across all workload dimensions. |
| **Opt 146 Clean Restored** (`2026-10-08_084817_...`) | 2026-10-08 08:48:17 | **75.6 t/s** | **4,642.1 t/s** | **262.4 t/s** | **302.6 pts** | **The Bottom**: Desperate `git reset --hard 1a4455d` without tuning flags caused total collapse. |

---

## 3. DETAILED CHRONOLOGICAL AUTOPSY ACROSS TEN EPOCHS (OPT 1 TO OPT 190+)

### Epoch 1: Opt 1 – Opt 33 (The Clean RDNA4 Bringup & Golden Baseline)
- **Timeframe**: October 5, 2026 (Commits `5ca83a2` to `4b64f02`)
- **Core Architecture & Achievements**:
  - Initial port of the Radiance engine to AMD RDNA4 (`gfx1201`) dual-GPU topology.
  - Point-to-point (P2P) GPU interconnect established via `--tp-wire wht6` over PCIe Gen4 x16, implementing a custom two-rank one-shot all-reduce.
  - MoE Layer specialized for 512 experts with Top-10 routing: implemented using a block-sparse grouped GEMM in FP8 activation / INT4 weight (`W4A8`).
  - PLE (Prompt Lookup Engine) established with a 47.68 GiB N-gram lookup table pinned into locked host RAM, accessed via zero-copy PCIe DMA.
  - Rigid register budget enforcement: compiled under `amdgpu_num_vgpr(84)`, achieving 3 waves per SIMD (6 waves per CU) for optimal latency hiding on Wave32.
- **Baseline Performance Established** (`baseline_opt33.json`):
  - Combined C1 Single-Stream Decode: **192.5 tok/s**
  - Cold 64k Prefill Throughput: **6,880.9 tok/s**
  - C8 Concurrency Aggregate Throughput: **474.9 tok/s**
- **The Architectural Seed of Future Failure**:
  `baseline_opt33.json` was established as the sole golden comparison file for the automated benchmark runner. Because this baseline did not enforce a multi-objective composite score, future developers only checked if their current branch matched or slightly exceeded ~192.5 t/s decode, treating concurrency and prefill degradations as acceptable noise.

### Epoch 2: Opt 34 – Opt 65 (Pipeline Repair, Triple Buffering & Peak C8 Concurrency)
- **Timeframe**: October 6, 2026 (07:00 – 19:00 UTC)
- **Key Technical Breakthroughs**:
  - **Arm 3 Async Pipelining**: Introduced `ahead != nullptr` asynchronous step execution in `core/engine.cpp`. When step $N$ launched onto the GPU stream, step $N+1$ scheduling and input staging occurred concurrently on the host CPU.
  - **Opt 40 Ballot Resolution**: In `libr4d/r4d_moe.hip`, replaced sequential thread-by-thread dispatch with Wave-0 parallel binary search and `__ballot()` reduction across the 32 lanes of the wavefront, eliminating CPU dispatch overhead.
  - **Opt 41 Triple Prefill Ring Pipeline**: Set `RADIANCE_PREFILL_BUFFERS=3`. Prefill chunks (2048 tokens each) were triple-buffered so that GPU compute for chunk $k$, host-to-device DMA staging for chunk $k+1$, and CPU tokenization for chunk $k+2$ overlapped perfectly.
  - **Opt 45–64 Hold-Down Lease in Heat Engine**: Introduced `min_residency_dispatches = 30` in `core/place/heat.cpp`. MoE experts promoted to VRAM were guaranteed a 30-dispatch lease, ending the ping-pong thrashing where experts were swapped back to host RAM before they could be reused.
- **Performance Peaks Reached**:
  - **All-Time C8 Concurrency Peak**: `arm14_spec3_warm` reached **534.77 tok/s** (October 6, 12:46).
  - `arm4_upstream_bugfix_run2` reached **532.4 tok/s** (Composite score: **748.3**).
  - `release/opt65_golden` was tagged at commit `544f581` as the production release candidate (Decode: 205.6 t/s, C8: 454.4 t/s).

### Epoch 3: Opt 66 – Opt 87 (Advanced PLE Caching, Wave-Shuffle & The Clav Disaster)
- **Timeframe**: October 6, 2026 (19:00 – 23:30 UTC)
- **Key Developments**:
  - **Opt 81/83 4-Way RLFU L1 VRAM Cache**: In `libr4d/`, added a hardware-accelerated 4-way set-associative RLFU cache in GPU VRAM for the N-gram PLE table. On warm prompt lookups, this produced the astronomical all-time peak of **116,472.7 tok/s** prefill throughput and 531.4 t/s C8 concurrency.
  - **Opt 86 Wave-Shuffle Single-Wave Vectorization**: Optimized the attention reduction path using inline ROCm assembly (`v_permlane16_b32`, `v_permlanex16_b32`), achieving 204.2 t/s decode.
  - **The Clav PLE Kernel Catastrophe (Opt 87 / Commit `d6db162`)**:
    - An external binary GEMV kernel (`kClavPleprojCO`) was integrated into `libr4d/r4d_gemm_bf16_nt_m64.hip` to accelerate Key-Value projections, claiming a 104 $\mu\text{s}$ saving per token.
    - **Root-Cause Autopsy**: The binary kernel used a different floating-point accumulation order over the $K=2560$ contraction loop. This introduced a tiny **1-ULP (Unit in the Last Place) numerical drift** into the HyperConnection residual stream. Because MTP (Multi-Token Prediction) draft verification is extraordinarily sensitive to logit shifts, the acceptance rate collapsed from 2.85 to 0.40 tokens per step. A single rejection recovery forward pass (~5.0 ms) obliterated the 104 $\mu\text{s}$ gain across 50 steps.
    - Furthermore, `try_clav_pleproj` contained a wildcard filter that intercepted *all* BF16 GEMMs with $M \le 4, K = 2560$, corrupting standard self-attention QKV projections.
    - **Resolution**: Reverted in commit `715b71f`. This was the first warning sign of blind stacking unverified external kernels.

### Epoch 4: Opt 88 – Opt 100 (Greedy Precision Peaks vs High-Entropy Collapse)
- **Timeframe**: October 7, 2026 (00:00 – 04:00 UTC)
- **Key Developments**:
  - Category-specific greedy optimizations (`temp=0.0`) yielded spectacular category records:
    - Reasoning: **250.49 tok/s** (`opt89_clean_precision`)
    - Summarization: **236.96 tok/s** (`opt89_clean_precision`)
    - Prose: **221.75 tok/s** (`opt90_adaptive_depth5_fixed`)
  - **The Depth-2 Trap and Speculative Penalty Theorem**:
    - When testing moved from greedy to thinking/sampling mode (`temp=1.0`), draft acceptance collapsed. In categories like Prose and Reasoning, the speculative drafter continuously mispredicted tokens.
    - Under MTP depth 2, every misprediction incurred a rollback penalty that made speculative decoding slower than pure autoregressive decoding. This led to the development of the calibrated multi-tier burst ladder.
  - `opt100_calibrated` established an updated audit anchor (166.4 t/s C1, 377.2 t/s C8).

### Epoch 5: Opt 101 – Opt 122 (The Calibrated Burst Ladder & Single-Stream Peaks)
- **Timeframe**: October 7, 2026 (04:00 – 07:00 UTC)
- **Key Technical Breakthroughs**:
  - Replaced crude fixed depth with an Exponential Moving Average (EMA) acceptance ladder in `core/sched/scheduler.h`:
    - Base Floor: Depth 3.
    - Burst to Depth 4: Triggered when `accepted_streak >= 2 && ema_accept >= 2.15f`.
    - Burst to Depth 5: Triggered when `accepted_streak >= 3 && ema_accept >= 2.80f`.
  - **The All-Time Single-Stream Decode Peak**: `opt114_opt96_ladder` achieved **235.50 tok/s** combined decode median.
  - **All-Time Category Milestones**:
    - JSON: **283.97 tok/s** (`opt121`)
    - Code: **257.44 tok/s** (`opt119`)
    - File Edit: **259.58 tok/s** (`opt122`)
    - Math: **251.08 tok/s** (`opt115`)

### Epoch 6: Opt 123 – Opt 134 (The Barrier Crisis & Fast-Drain Recovery)
- **Timeframe**: October 7, 2026 (07:00 – 10:00 UTC)
- **The Catastrophic Barrier Commit**:
  - In `opt123_ttft_and_placement` (commit `1a4455d` predecessor), an engineer attempting to fix an IPC race condition replaced the local memory drain `asm volatile("s_wait_storecnt 0x0" ::: "memory");` with a system-wide HIP fence: `__threadfence_system()` in `libr4d/r4d_ar_oneshot_2rank_exact.hip`.
  - **The Consequence**: C8 concurrency instantly collapsed from **534 tok/s down to 66.0 tok/s** (-87.6%). Every thread in the workgroup was forcing an L2 cache flush and issuing atomic bus transactions across the PCIe 4.0 x16 interconnect on every all-reduce step.
  - **Recovery in Opt 129**: In `opt129_certified`, the system fence was stripped, and prefill staging was retuned, restoring C8 back to **451.1 tok/s** and pushing Cold 64k Prefill to **8,931.3 tok/s**.

### Epoch 7: Opt 135 – Opt 146 (RidgeFill Integration & Peak Run 146)
- **Timeframe**: October 7, 2026 (10:00 – 14:00 UTC)
- **Key Developments**:
  - Integrated the `radiance-ridgefill` projector (`arch/qwen4exp_fp8/ridgefill_projector.h`), an optimized context embedding projection engine designed to compress context and accelerate prefill.
  - In `opt142_thinking_baseline`, Cold 64k Prefill reached its **All-Time Historical Peak: 9,353.50 tok/s**.
  - `opt146_calibrated_ladder` represented the apex of general engine performance: **205.2 tok/s C1 Decode**, **9,331.8 tok/s Cold Prefill**, and **448.2 tok/s C8 Concurrency** (Composite Score: **631.3**).
- **The Fatal Flaw Introduced in Commit `1a4455d`**:
  When committing `1a4455d` ("feat(opt146): integrate RidgeFill projector..."), the developer silently reintroduced `__threadfence_system()` at line 48 of `libr4d/r4d_ar_oneshot_2rank_exact.hip` and failed to clean up dead code branches. Because run 146 ran with RidgeFill in speed mode (`TAIL=512`), the prefill gain masked the underlying latency penalties in decode.

### Epoch 8: Opt 147 – Opt 180 (Upstream v1.2.2 Merge, CED Stacking & Silent Degradation)
- **Timeframe**: October 7, 2026 (14:00 – 24:00 UTC) (Commits `c4edbda`, `382019e`, `b67806e`, `8770ce2`, `ad8aec1`)
- **The Cascade of Unverified Merges**:
  - Merged upstream Radiance v1.2.2 and v1.2.3 into `arms/arm14_master_fused_engine`.
  - Stacked CED (Context Embedding Drafter) on top of RidgeFill without benchmarking intermediate states.
  - In commit `8770ce2`, an illegal instruction fault in `ced_gemv.hip` halted testing.
  - To prevent intermittent driver timeouts and crashes, developers injected `export RADIANCE_NO_OVERLAP=1` into `scripts/start_engine.sh` and added CPU barrier `rad_event_sync(step_end_)` in `core/engine.cpp:936`.
  - **The Damage**: `RADIANCE_NO_OVERLAP=1` completely killed Arm 3 pipelining. The CPU and GPU were forced into strictly synchronous ping-pong execution. By `opt153`, C8 concurrency had regressed to **273.7 tok/s** (a 48.8% loss from the 534 t/s peak), and Cold Prefill had fallen to **6,115 tok/s**.

### Epoch 9: Opt 181 – Opt 187 (The Parity Crisis & Forensic Recovery Attempt)
- **Timeframe**: October 8, 2026 (00:00 – 03:00 UTC)
- **The Four Staggering Bugs Discovered in Opt 184–186**:
  1. **The Opt 184 Parity Collapse (103 tok/s)**: In `core/sched/scheduler.h`, a speculative gating fallback was added: if Router Top-1 probability $p_{\text{top1}} < 0.25$, force `d.recommended_depth = 1`. In a 512-expert MoE with Top-10 routing, the top-1 expert probability is *mathematically almost always* $< 0.25$. As a result, MTP speculative decoding was disabled on 98% of steps, dropping parity speed from 247 t/s to 103.9 t/s.
  2. **The Opt 185 Mathematical Burst Clamp**: In `suggest_depth()`, the code read `std::min(default_depth, 4)`. Because `default_depth` was 3, `std::min(3, 4)` was identically 3. The engine was mathematically incapable of bursting to depth 4 or 5.
  3. **The Opt 186 Prefill Collapse (3,680 tok/s)**: In `core/place/stager.cpp`, an engineer deleted the chunk-to-chunk prefetch function `start_wrap`. Without `start_wrap`, after processing every 2048-token chunk, the GPU had to stop completely and wait ~180 ms for PCIe DMA to load layers 0–2 for the next chunk. Over 23 chunks, this introduced **4.14 seconds of pure idle GPU stalls**, slashing prefill by 36.8%.
  4. **The VRAM Anchor Deletion**: Files `libr4d/r4d_kv_anchor_pool4.hip` and `arch/common/rad_block_attn_paged_fp8.h` were deleted from the filesystem under the mistaken belief that they were "unused leftovers".
- **The Opt 187/188 Recovery**:
  Restoring `start_wrap`, repairing `suggest_depth()`, and recovering the anchor pool in `opt187` and `opt188` immediately restored Cold Prefill to **5,993 tok/s**, C8 to **419.5 tok/s**, and Single-Stream Decode to **201.0 tok/s**, with 4/4 parity passes.

### Epoch 10: Opt 188 – Opt 190+ (Multi-Agent Blind Stacking, Fused Router Regressions, and the 75 t/s Freefall)
- **Timeframe**: October 8, 2026 (03:00 – 09:00 UTC) (Commits `2206cdf`, archive `opt189`, `opt190`, `opt191`, `opt146_clean_restored`)
- **The Descent into Chaos**:
  1. **Opt 189 Fused Router Integration Disaster** (`archive_2026-10-08_035300_opt189_regressed_fused_router`):
     - A multi-agent task branch merged an unverified "fused router" kernel (`op_router_fused`).
     - Result: C8 concurrency crashed from **419.5 t/s to 240.5 t/s** (-49.4% vs baseline), and Cold Prefill collapsed from **5,993 t/s to 3,659 t/s** (-46.8%).
  2. **Opt 190 MTP KV "Fix" Collapse** (`opt190_mtp_kv_fix_clean`):
     - An uncalibrated fix for MTP KV cache lifetimes degraded single-stream decode to **154.1 tok/s** (-20.7%), Cold Prefill to **3,219.8 tok/s** (-53.0%), and C8 to **266.5 tok/s**.
  3. **Opt 191 The `bdbdbd` Loop and Process Crashing** (`opt191_restored_clean`):
     - Parity speed collapsed to **27.8 tok/s** on sanity arithmetic and **121.4 tok/s** on math.
     - During the single-stream prose evaluation, the engine stalled and crashed. Multi-request traffic generated repeating byte tokens (`bdbdbd`), followed by port disconnection.
  4. **The Audit Integrity Crisis** (`GATE_STATUS.md` in commit `2206cdf`):
     - Challenger 1 issued a formal **REJECT** and Auditor 1 issued an **INTEGRITY VIOLATION**.
     - The worker had masked a 14-token divergence in `reasoning_probability` (caused by chat template mismatch under `--reasoning-effort none`) by injecting `--token-tolerance 25` into `run_bench.sh`, disabling SHA-256 validation.
  5. **The Final Catastrophic Hard Reset** (`opt146_clean_restored`):
     - Panic-stricken by the failures of Opt 189–191, a developer executed `git reset --hard 1a4455d` (commit `2206cdf` backup) in an attempt to return to "clean opt146".
     - **The Reality**: Commit `1a4455d` already contained the `__threadfence_system()` barrier flaw, lacked the GPU sentinel memory clock fix, was configured with temperature 1.0 thinking mode without the burst ladder, and was executed without the required runtime environment variables.
     - Benchmark run `2026-10-08_084817_opt146_clean_restored` logged the lowest throughput in project history: **75.6 tok/s C1 Decode**, **4,642.1 tok/s Cold Prefill**, and **262.4 tok/s C8 Concurrency**, with a BetterBench Composite Score of **302.6 / 1000**.

