# RadianceMine ⚡

> **Pristine, Production-Grade Inference Engine & Architectural Governance System for AMD RDNA4 (gfx1201)**

[![Target Baseline: Opt 146](https://img.shields.io/badge/Baseline-Opt%20146%20(1a4455d)-blue.svg)](#the-golden-baseline)
[![Dual AMD R9700](https://img.shields.io/badge/Hardware-Dual%20R9700%20gfx1201-orange.svg)](#hardware-specification)
[![3-Tier Zero-Regression Gate](https://img.shields.io/badge/Quality%20Gate-3--Tier%20Zero--Regression-green.svg)](ENGINEERING_CONSTITUTION.md)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-lightgrey.svg)](LICENSE)

---

## 1. Overview & Mandate

**RadianceMine** is the hardened, regression-proof successor to Radiance, engineered specifically for dual **AMD Radeon AI PRO R9700 (gfx1201)** workstations.

Following the forensic analysis of post-Opt146 performance regressions (where un-gated concurrent experiments and toxic runtime flags caused throughput to crash from 210.3 tok/s to 75.6 tok/s), RadianceMine institutes an **inviolable 4-rule Engineering Constitution**, an **automated 3-Tier hardware regression gate**, and a **bulletproof worktree workflow**.

---

## 2. The Golden Baseline: Opt 146

- **Commit**: `1a4455d26871100a6a97e1dd3b5c83d4431764b6`
- **Model**: Qwen3.8-Flash-Next / Qwen4Exp (FP8 trunk linears, IQ4R/W4 MoE 512 experts, top-$k=10$, GDN linear attention, MTP Spec 3–5)
- **Certified Performance**:
  - **Combined Decode Median**: `210.3 tok/s` (Code: 238.7, JSON: 264.5, Math: 228.3, File Edit: 233.7)
  - **Cold 64k Context Prefill**: `9,331.8 tok/s`
  - **C8 Concurrency Aggregate**: `448.2 tok/s`
  - **Composite Score**: `631.3 / 1000` (Zenith record: 685.2)

---

## 3. The Four Immutable Engineering Laws

All contributors and autonomous agents are strictly bound by [`ENGINEERING_CONSTITUTION.md`](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md) and [`AGENTS.md`](file:///home/orca/RadianceMine/AGENTS.md):

1. **Rule 1: The Zero-Regression Invariant (Push/Merge Gate)**  
   No code is merged into `main` unless it passes all 3 tiers on physical GPUs:
   - **Tier 1**: Parity Check Gate (`scripts/parity_check.py --suite full`): Greedy bit-exact tokens (0 divergence); Code $\ge 230$ tok/s, Reasoning $\ge 240$ tok/s, Math $\ge 210$ tok/s.
   - **Tier 2**: BetterBench Composite Score Gate (`scripts/check_composite_gate.py`): Score $\ge$ baseline; zero throughput regression; strict latency guardrails (C1 P99 $\le 4.5\,\text{ms}$, C8 P99 $\le 15.0\,\text{ms}$, TTFT $\le 100\,\text{ms}$).
   - **Tier 3**: RDNA4 ISA & Hardware Invariants (`scripts/verify_rdna4_invariants.sh`): Zero LDS 32-bank conflicts; VGPR count $\le 84$ (optimal) / $\le 96$ (cliff ceiling); 128-bit coalesced global memory access; zero CPU-GPU synchronous spinlocks in decode.
2. **Rule 2: Mandatory Full Standalone Build Archival for Winning Arms**  
   Every winning arm is frozen with executables, `radiance_home` kernels, configs, commit SHA, and environment variables into `releases/golden_builds/<arm>.zip` with SHA256 hashes and an instant $<5\text{-second}$ rollback wrapper.
3. **Rule 3: Strict Worktree Isolation**  
   Trunk (`main`) is permanently frozen to the latest winning build. All work happens in dedicated, isolated Git worktrees (`worktrees/<feature>`).
4. **Rule 4: Zero Destructive Deletions**  
   Deprecated or failed experiments are never deleted; they are quarantined in `attic/` or preserved in `candidates/` with full post-mortem documentation.

---

## 4. Repository Structure

```
/home/orca/RadianceMine/
├── ENGINEERING_CONSTITUTION.md  # Binding 4-rule constitution & 3-tier gate specifications
├── AGENTS.md                    # Operational directives and machine rules for AI agents
├── MASTER_PLAN.md               # Master architectural roadmap & sequential integration order
├── README.md                    # This master overview
│
├── scripts/                     # Bulletproof automation toolchain
│   ├── gate_check.sh            # Automated 3-tier regression gate runner
│   ├── parity_check.py          # Tier 1 greedy exactness & throughput floor verifier
│   ├── check_composite_gate.py  # Tier 2 BetterBench composite score & latency validator
│   ├── verify_rdna4_invariants.sh # Tier 3 RDNA4 ISA & hardware invariant checker
│   ├── check_isa_compliance.py  # RDNA4 kernel binary & disassembly inspector
│   ├── archive_winner.sh        # Complete build archival with SHA256 & instant rollback wrapper
│   ├── rollback_to_winner.sh    # Instant < 5-second rollback engine
│   └── create_worktree.sh       # Isolated git worktree provisioner
│
├── baselines/                   # Certified performance baselines
│   ├── baseline_opt146.json     # Opt 146 calibrated ladder benchmark results
│   └── golden_parity_reference.json # Bit-exact greedy token reference vectors
│
├── candidates/                  # Standalone candidate levers for sequential integration
│   ├── README.md                # Master index of candidate levers
│   ├── POST_OPT146_FORENSIC_AUDIT_AND_EVALUATION.md # Forensic autopsy of regressions
│   ├── lever1_gdn_qsa_fusion/   # Lever 1: GDN Weight Concat & Fused QSA op_qprep
│   ├── lever2_fused_moe_router/ # Lever 2: Fused MoE Router (router_gemm_topk_scatter)
│   ├── lever3_qsa_offload_kvarn/# Lever 3: QSA Host Offload & KVarN INT4 KV
│   ├── lever4_fr_spec_draft_head/# Lever 4: FR-Spec Reduced-Vocab Draft Head
│   └── lever5_adaptive_bandit_controller/ # Lever 5: SOTA MTP Adaptive Bandit Controller
│
├── releases/golden_builds/      # Archived standalone winning builds with SHA256 & restore.sh
├── attic/                       # Quarantined failed experiments and post-mortems
├── worktrees/                   # Dedicated staging for isolated git worktrees
│
├── arch/                        # Model architecture definitions (qwen4exp, qwen35, etc.)
├── core/                        # Engine scheduler, allocator, and dispatch core
├── libr4d/                      # RDNA4 HIP/assembly kernel library
└── tests/                       # Unit and architecture test suites
```

---

## 5. Quickstart & Workflow Guide

### Spawning a Clean Worktree
```bash
# Provision isolated worktree branched from golden baseline main
bash scripts/create_worktree.sh lever1_gdn_qsa_fusion
cd worktrees/lever1_gdn_qsa_fusion
```

### Applying a Candidate Lever
```bash
# Apply clean candidate patch
git apply ../../candidates/lever1_gdn_qsa_fusion/lever.patch

# Build and run unit tests
cmake -B build_hip -S . -DCMAKE_BUILD_TYPE=Release
cmake --build build_hip --target arch_test -j$(nproc)
./build_hip/tests/arch_test qwen4exp_gdn_in_proj_concat_and_qsa_qprep_fusion
```

### Running the 3-Tier Regression Gate
```bash
# Executes Tier 3 (ISA), Tier 2 (BetterBench), and Tier 1 (Parity)
bash scripts/gate_check.sh --all
```

### Archiving a New Winner
```bash
# Once certified by gate_check.sh:
bash scripts/archive_winner.sh --name opt147_lever1_gdn_fusion
```

### Instant 5-Second Rollback
```bash
# List available golden releases:
bash scripts/rollback_to_winner.sh --list

# Instantly restore latest certified golden build:
bash scripts/rollback_to_winner.sh --latest
```

---

## 6. Sequential Integration Order

Per [`MASTER_PLAN.md`](file:///home/orca/RadianceMine/MASTER_PLAN.md), candidate levers must be admitted in strict linear sequence:
1. **Phase 1: Lever 1** — GDN Weight Concat & Fused QSA (`-14.0 ms/step`)
2. **Phase 2: Lever 2** — Fused MoE Router (`-96 dispatches/step`)
3. **Phase 3: Lever 3** — QSA Host Offload & KVarN INT4 KV (`4x KV compression`)
4. **Phase 4: Lever 4** — FR-Spec Reduced-Vocab Draft Head (`3x faster draft head`)
5. **Phase 5: Lever 5** — SOTA MTP Adaptive Bandit Controller (`+15-28% TPS`)
