---
type: architecture
title: MTP Speculative Decoding & Draft Heads
description: Multi-Token Prediction (MTP) architecture in RadianceMine, reduced-vocabulary draft heads (FR-Spec), draft window progression, and speculative depth control.
tags: [speculative, mtp, drafting, fr-spec, scheduler, depth]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-3d74dea7fca07cbbf7a17c1f
    resource: repo://candidates/lever4_fr_spec_draft_head/README.md
  - id: openwiki-source-33c3131768d5a684d7bb1f51
    resource: repo://core/engine_draft.cpp
  - id: openwiki-source-bc65b63b593d6914747e9d85
    resource: repo://core/sched/scheduler.h
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# MTP Speculative Decoding & Draft Heads

RadianceMine leverages Multi-Token Prediction (MTP) to accelerate single-stream decode throughput beyond 260 tok/s on Qwen3.8-Flash-Next. By drafting 3 to 5 candidate tokens per step and verifying them in parallel on the trunk model, the engine reduces memory-bandwidth-bound DRAM transfers per emitted token.

## 1. MTP Draft Mechanism

The MTP block (`arch/common/rad_block_mtp_fp8.h`) operates as an auxiliary shallow transformer layer:
- **Projection**: The normalized hidden state $h_t$ from the trunk model is projected through the MTP linear layers and sparse attention.
- **Logit Generation**: Rather than evaluating the full 152k vocabulary with an unpruned GEMM, the drafter runs a reduced GEMM to select the top candidate token ID for subsequent draft positions $t+1, t+2, \dots, t+K$.
- **Draft Advancing**: Tokens are appended to the draft window and evaluated in pipelined batches (`Engine::issue_serial_drafter`).

## 2. FR-Spec: Reduced-Vocabulary Draft Head (Lever 4)

In full vocabulary drafting, evaluating $N=152,064$ rows requires reading ~2.54 GB of weights per draft token:
- **The FR-Spec Innovation**: The 52,416 most frequently sampled tokens (`mtp-lm-head-reduced.safetensors`, 67.1 MiB Q4) are mapped into a pinned device buffer.
- **Argmax Remapping**: The draft GEMM evaluates only $N=52,416$ rows. The resulting index $k \in [0, 52415]$ is translated to the full vocabulary space via `vocab_ids[k]`.
- **Bandwidth Reduction**: Cuts draft head memory traffic by over 97% while maintaining greedy parity against the trunk model (which performs full verification).

## 3. Speculative Depth Arbitration & Streak Tracking

In `core/sched/scheduler.h`:
- `observe_draft(int drafted, int accepted)` maintains an exponential moving average (`ema_accept = 0.70 * ema_accept + 0.30 * accepted`) alongside consecutive acceptance streaks.
- `suggest_depth(default_depth, adaptive, multi_seq)` dynamically adjusts speculative depth between $K=1$ and $K=5$:
  - On long accepted streaks, depth promotes to 4 or 5 tokens.
  - On low entropy / high rejection, depth falls back to prevent wasted verification compute.
  - In multi-sequence batched mode (C8 concurrency), depth is locked to optimal bounds (depth 3) to prevent the "depth-2 under-speculation trap" where throughput collapses.
