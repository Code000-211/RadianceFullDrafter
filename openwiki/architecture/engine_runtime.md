---
type: architecture
title: Engine Runtime & Decode Pipeline
description: Architectural explanation of RadianceMine's dual-GPU decode loop, AQL packet dispatch, host-device synchronization, and zero-CPU-wait pipelining.
tags: [engine, runtime, decode, aql, synchronization, gpu]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-33c3131768d5a684d7bb1f51
    resource: repo://core/engine_draft.cpp
  - id: openwiki-source-4e906d35dbc2392a87d6954c
    resource: repo://core/engine.cpp
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# Engine Runtime & Decode Pipeline

The engine runtime orchestrates low-latency tensor-parallel inference across dual AMD Radeon AI PRO R9700 (gfx1201) GPUs. To achieve peak throughput (>260 tok/s single-stream decode), the execution model avoids synchronous host-device roundtrips, relying on direct AQL queue dispatch and asynchronous stream pipelining.

## 1. Dual-GPU Execution & Rank Loops

RadianceMine executes in tensor-parallel mode (TP=2) using a dedicated worker thread for each GPU rank.
- **Rank Worker Loop**: Each rank runs `Engine::rank_loop` in parallel, managing command buffers, event synchronization, and GPU queue submissions independently.
- **Host Execution Coordination**: The main coordinator thread runs `Engine::step_loop`, advancing scheduler batches, coordinating draft-verify cycles, and monitoring batch completions without issuing blocking `hipStreamSynchronize` or `hipDeviceSynchronize` calls during the hot decode path.

## 2. AQL Queue Dispatch & Doorbell Ringing

GPU command streams are dispatched via AMD Architected Queuing Language (AQL) packet structures.
- Direct packet construction in pinned host memory avoids driver-level submission overhead.
- Synchronization between compute kernels and inter-GPU communication is achieved through hardware barrier packets (`AQL_PACKET_TYPE_BARRIER_AND`) and hardware signaling events.
- Doorbell registers are rung via memory-mapped I/O once command blocks are sealed.

## 3. The Speculative Decode & Verification Pipeline

During speculative decoding (MTP):
1. **Trunk Step**: The trunk model processes verified tokens, computing new activations and hidden states.
2. **Serial Draft Dispatch**: `Engine::issue_serial_drafter` launches low-latency draft iterations using the speculative draft head.
3. **Pipelined Verification**: `Engine::finish_serial_drafter` evaluates proposed draft tokens against target logits in a pipelined fashion, resolving accepted tokens without interrupting ongoing AQL command queues.

## 4. Zero-CPU-Wait Pipelining Invariant

Under the zero-CPU-wait invariant:
- Host threads must never block on GPU execution within a decode layer.
- Intermediate results (such as MoE routing tables or shared gate logits) are consumed directly on-device via GPU-side kernels.
- Host CPU activity is strictly limited to batch scheduling, token sampling coordination, and HTTP response streaming.
