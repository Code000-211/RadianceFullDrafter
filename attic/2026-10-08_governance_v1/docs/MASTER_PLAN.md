# RadianceMine Master Architectural Plan & Sequential Integration Roadmap

> **Target Baseline**: Radiance Opt 146 (`1a4455d26871100a6a97e1dd3b5c83d4431764b6`)  
> **Hardware Environment**: Dual AMD Radeon AI PRO R9700 (gfx1201, RDNA4, 64 CUs, Wave32, 576 GB/s GDDR6, PCIe Gen5 $\times 16$ `--tp-wire wht6`)  
> **Target Model**: Qwen3.8-Flash-Next / Qwen4Exp (FP8 trunk linears, IQ4R/W4 MoE 512 experts, top-$k=10$, GDN linear attention, MTP Spec 3–5)  
> **Governance Authority**: [`ENGINEERING_CONSTITUTION.md`](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md)

---

## 1. Executive Vision & Objectives

Radiance achieved a certified peak composite score of **631.3 / 685.2 record** at **Opt 146**. The subsequent multi-agent experiments caused severe regressions due to un-gated concurrent changes and toxic runtime flags.

The mission of **RadianceMine** is to methodically admit the 5 qualified candidate levers into the engine, advancing beyond **700+ Composite Score** and targeting **260+ tok/s decode**, **10,000+ tok/s prefill**, and **500+ tok/s C8 concurrency** without a single regression in token exactness, throughput, or latency.

```
       [Opt 146 Baseline] ──► 210.3 tok/s Decode | 631.3 Composite Score
               │
               ▼  (Gate 1, 2, 3 Pass)
     ┌────────────────────────────────────────────────────────┐
     │  Phase 1: Lever 1 (GDN & QSA Fusion)                   │  -14.0 ms/step
     └────────────────────────────────────────────────────────┘
               │
               ▼  (Gate 1, 2, 3 Pass)
     ┌────────────────────────────────────────────────────────┐
     │  Phase 2: Lever 2 (Fused MoE Router)                   │  -96 dispatches
     └────────────────────────────────────────────────────────┘
               │
               ▼  (Gate 1, 2, 3 Pass)
     ┌────────────────────────────────────────────────────────┐
     │  Phase 3: Lever 3 (QSA Offload & KVarN INT4 KV)        │  4x KV Compression
     └────────────────────────────────────────────────────────┘
               │
               ▼  (Gate 1, 2, 3 Pass)
     ┌────────────────────────────────────────────────────────┐
     │  Phase 4: Lever 4 (FR-Spec Reduced Draft Head)         │  3x Faster Drafter
     └────────────────────────────────────────────────────────┘
               │
               ▼  (Gate 1, 2, 3 Pass)
     ┌────────────────────────────────────────────────────────┐
     │  Phase 5: Lever 5 (Adaptive Bandit with Clamped Floor) │  +15-28% Multi-Turn
     └────────────────────────────────────────────────────────┘
               │
               ▼
       [Certified Target] ──► 260+ tok/s Decode | > 700 Composite Score
```

---

## 2. Master Candidate Lever Architectural Matrix

All candidate levers are isolated and preserved with unified patches, standalone sources, and technical documentation inside [`candidates/`](file:///home/orca/RadianceMine/candidates/):

| Lever | Identifier | Target Subsystem | Innovation & Microarchitectural Principle | Expected Latency & VRAM Impact | Safety Gating | Verification Suite |
|---|---|---|---|---|---|---|
| **Lever 1** | [`lever1_gdn_qsa_fusion`](file:///home/orca/RadianceMine/candidates/lever1_gdn_qsa_fusion) | Gated Delta Net & Full Attention | Fuses $[q\|k\|v\|z\|a\|b]$ into single row-sharded FP8 GEMM ($8240 \times 2560$ at TP2); fuses RMSNorm + RoPE + gate into `qk_norm_rope_gate`. | **$-14.0\,\text{ms/step}$** ($\sim 13.4\,\text{ms}$ GDN + $\sim 0.56\,\text{ms}$ QSA); zero intermediate norm VRAM buffers. | Default safe (layer layout fusion) | `tests/arch_test` (`qwen4exp_gdn_in_proj_concat...`) |
| **Lever 2** | [`lever2_fused_moe_router`](file:///home/orca/RadianceMine/candidates/lever2_fused_moe_router) | MoE Routing & Gating | Single-launch router GEMM + shared gate + Top-10 counting sort (`router_gemm_topk_scatter`). Complete fix for upstream atomic arrival stalls. | Eliminates **96 dispatches/step** (144 $\to$ 48 dispatches); zero intermediate logits in LDS fast-path. | `R4D_ROUTER_FUSED=1` (default 0) | `tests/arch_test` (`qwen4exp_fused_router...`) |
| **Lever 3** | [`lever3_qsa_offload_kvarn`](file:///home/orca/RadianceMine/candidates/lever3_qsa_offload_kvarn) | KV-Cache & Context Expansion | $97.5\%$ hit rate combined union prefetch over PCIe Gen5; Fast Walsh-Hadamard (FWHT-256) rotation for outlier-free INT4 KV cache. | Enables **$64\text{k}+$ context** without VRAM exhaustion; **$4\times$ KV compression** ($75\%$ VRAM reduction). | `--kvarn` (`RADIANCE_KVARN=1`), `--qsa-offload` | `tools/qsa_overlap_sim.py`, `tests/ref_test`, `tests/config_test` |
| **Lever 4** | [`lever4_fr_spec_draft_head`](file:///home/orca/RadianceMine/candidates/lever4_fr_spec_draft_head) | MTP Speculative Drafter | Frequency-Ranked Speculative Decoding reducing draft vocab from 152k to 52k ($>99.2\%$ token mass coverage) with INT4 draft weights. | **$3\times$ faster draft head** ($1.8\,\text{ms} \to 0.58\,\text{ms}$ per draft round); reduced head occupies **$<80\,\text{MB}$** VRAM. | Automatic safetensors detection or `RADIANCE_MTP_HEAD_REDUCED` | `tests/fr_spec_test`, `tests/checkpoint_test` |
| **Lever 5** | [`lever5_adaptive_bandit_controller`](file:///home/orca/RadianceMine/candidates/lever5_adaptive_bandit_controller) | Speculative Engine & Scheduler | 4 Pillars: Dynamic range $K \in [1, 6]$, online Multi-Armed Bandit LCB tracking tokens/ms, per-`SchedReq` policies, chain-aware verification. **Clamped floor invariant (min 3)**. | **$+15\%$ to $+28\%$ TPS** on mixed-entropy workloads; zero memory overhead. | `RADIANCE_ADAPTIVE_SPEC=1` | `tests/sched_test` |

---

## 3. The Sequential Integration Protocol

No lever may be combined with another until it has passed all three gates individually. The integration order is strictly linear:

### Phase 1: Integration of Lever 1 (GDN Weight Concat & Fused QSA)
1. **Spawn Worktree**:
   ```bash
   bash scripts/create_worktree.sh lever1_gdn_qsa_fusion
   cd worktrees/lever1_gdn_qsa_fusion
   ```
2. **Apply Candidate Patch**:
   ```bash
   git apply ../../candidates/lever1_gdn_qsa_fusion/lever.patch
   ```
3. **Compile & Unit Test**:
   ```bash
   cmake -B build_hip -S . -DCMAKE_BUILD_TYPE=Release
   cmake --build build_hip --target arch_test -j$(nproc)
   ./build_hip/tests/arch_test qwen4exp_gdn_in_proj_concat_and_qsa_qprep_fusion
   ```
4. **Execute 3-Tier Gate**:
   ```bash
   bash scripts/gate_check.sh --all
   ```
5. **Promotion & Archival**:
   - On 3-Tier PASS:
     ```bash
     bash scripts/archive_winner.sh --name opt147_lever1_gdn_fusion
     ```
   - Fast-forward merge `worktree/lever1_gdn_qsa_fusion` into `main`.

---

### Phase 2: Integration of Lever 2 (Fused MoE Router)
1. **Spawn Worktree from New Main**:
   ```bash
   bash scripts/create_worktree.sh lever2_fused_moe_router
   cd worktrees/lever2_fused_moe_router
   ```
2. **Apply Candidate Patch**:
   ```bash
   git apply ../../candidates/lever2_fused_moe_router/lever.patch
   ```
3. **Compile & Unit Test**:
   ```bash
   cmake --build build_hip --target arch_test -j$(nproc)
   ./build_hip/tests/arch_test qwen4exp_fused_router_single_dispatch_at_decode
   ```
4. **Execute 3-Tier Gate**:
   ```bash
   bash scripts/gate_check.sh --all
   ```
5. **Promotion & Archival**:
   - On 3-Tier PASS:
     ```bash
     bash scripts/archive_winner.sh --name opt148_lever2_fused_router
     ```
   - Fast-forward merge `worktree/lever2_fused_moe_router` into `main`.

---

### Phase 3: Integration of Lever 3 (QSA Host Offload & KVarN INT4 KV)
1. **Spawn Worktree from New Main**:
   ```bash
   bash scripts/create_worktree.sh lever3_qsa_offload_kvarn
   cd worktrees/lever3_qsa_offload_kvarn
   ```
2. **Apply Candidate Patch & Phase 0 Simulation**:
   ```bash
   git apply ../../candidates/lever3_qsa_offload_kvarn/lever.patch
   python3 ../../candidates/lever3_qsa_offload_kvarn/tools/qsa_overlap_sim.py
   ```
3. **Compile & Unit Test**:
   ```bash
   cmake --build build_hip --target ref_test config_test -j$(nproc)
   ./build_hip/tests/ref_test
   ```
4. **Execute 3-Tier Gate**:
   ```bash
   bash scripts/gate_check.sh --all
   ```
5. **Promotion & Archival**:
   - Archive new golden release and advance `main`.

---

### Phase 4: Integration of Lever 4 (FR-Spec Reduced-Vocab Draft Head)
1. **Spawn Worktree from New Main**:
   ```bash
   bash scripts/create_worktree.sh lever4_fr_spec_draft_head
   cd worktrees/lever4_fr_spec_draft_head
   ```
2. **Apply Candidate Patch**:
   ```bash
   git apply ../../candidates/lever4_fr_spec_draft_head/lever.patch
   ```
3. **Compile & Unit Test**:
   ```bash
   cmake --build build_hip --target fr_spec_test checkpoint_test -j$(nproc)
   ./build_hip/tests/fr_spec_test
   ```
4. **Execute 3-Tier Gate**:
   ```bash
   bash scripts/gate_check.sh --all
   ```
5. **Promotion & Archival**:
   - Archive new golden release and advance `main`.

---

### Phase 5: Integration of Lever 5 (SOTA MTP Adaptive Bandit Controller)
1. **Spawn Worktree from New Main**:
   ```bash
   bash scripts/create_worktree.sh lever5_adaptive_bandit_controller
   cd worktrees/lever5_adaptive_bandit_controller
   ```
2. **Apply Candidate Patch with Strict Floor Enforcement**:
   - Verify that the speculative floor clamp `std::min(depth, 3)` is preserved to prevent the post-146 degradation!
   ```bash
   git apply ../../candidates/lever5_adaptive_bandit_controller/lever.patch
   ```
3. **Compile & Unit Test**:
   ```bash
   cmake --build build_hip --target sched_test -j$(nproc)
   ./build_hip/tests/sched_test
   ```
4. **Execute 3-Tier Gate**:
   ```bash
   bash scripts/gate_check.sh --all
   ```
5. **Promotion & Archival**:
   - Archive zenith release and celebrate passing the 700+ Composite Score record!

---

## 4. Emergency Rollback & Triage Protocol

If at any point a regression or instability occurs:
1. Immediately run:
   ```bash
   bash scripts/rollback_to_winner.sh --latest
   ```
2. Verify restoration in $<5\text{ seconds}$.
3. Isolate the failing patch, compile telemetry, and document the root cause in `attic/`.
