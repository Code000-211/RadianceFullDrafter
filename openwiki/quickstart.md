---
type: guide
title: Quickstart & Developer Operations
description: Developer guide for building, testing, and operating RadianceMine on dual AMD Radeon AI PRO R9700 hardware under the Engineering Constitution.
tags: [quickstart, build, testing, operations, rocm, worktrees]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-91f9fdba61d086179001fdd2
    resource: repo://scripts/create_worktree.sh
  - id: openwiki-source-ea1f955f0beebd6b790e7cde
    resource: repo://scripts/engine_manager.sh
  - id: openwiki-source-72ad8968cc39197079aa5d36
    resource: repo://scripts/gate_check.sh
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# Quickstart & Developer Operations

Welcome to **RadianceMine**, the high-performance, regression-proof LLM inference engine optimized specifically for dual AMD Radeon AI PRO R9700 (gfx1201, RDNA4) GPUs running Qwen3.8-Flash-Next.

## 1. Environment & Prerequisites

RadianceMine targets physical AMD RDNA4 hardware running ROCm:
- **ROCm Toolchain**: ROCm 6.2+ installed at `/opt/rocm` (`hipcc`, `llvm`, `rocm-smi`).
- **Build System**: CMake 3.25+, Ninja, Clang 18+.
- **Environment Variables**:
  ```bash
  export ROCM_PATH=/opt/rocm
  export HIP_PATH=/opt/rocm
  export PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH
  ```

## 2. Rule 3: Strict Worktree Isolation

Under Rule 3 of the [Engineering Constitution](repo://ENGINEERING_CONSTITUTION.md), **never develop on `main` directly**. `main` is permanently sealed to the latest certified golden baseline.

To develop a new optimization or test a feature:
```bash
# 1. Create an isolated worktree branched from golden baseline
bash scripts/create_worktree.sh my_optimization_lever

# 2. Switch to the isolated workspace
cd worktrees/my_optimization_lever

# 3. Build HIP kernels incrementally (<3.0 seconds)
ninja -C build_hip
```

## 3. Rule 1: The 4-Tier Master Gate

No code may be merged into `main` without passing all four automated quality tiers on the physical GPUs:
```bash
# Run complete 4-tier gate check
bash scripts/gate_check.sh

# Or run individual verification tiers:
bash scripts/verify_ground_truth.sh           # Tier 0: Epistemic Ground Truth
python3 scripts/parity_check.py --suite full   # Tier 1: Parity & Greedy Exactness
python3 scripts/check_composite_gate.py        # Tier 2: Composite Score
bash scripts/verify_rdna4_invariants.sh build_hip # Tier 3: RDNA4 ISA Compliance
```

## 4. Engine Lifecycle & Serving

Manage the background inference server via `scripts/engine_manager.sh`:
```bash
# Start engine on dual GPUs (PORT 8000)
bash scripts/engine_manager.sh start

# Check engine health and VRAM allocation
bash scripts/engine_manager.sh status

# Stop engine and free GPU VRAM
bash scripts/engine_manager.sh stop
```

## 5. Repository Documentation & Subsystems

Explore the architecture pages to understand each subsystem:
<!-- openwiki: broken internal link [/openwiki/architecture/engine_runtime.md] link "/openwiki/architecture/engine_runtime.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
- [Engine Runtime & Decode Pipeline](/openwiki/architecture/engine_runtime.md) — Decode loop, AQL queues, and zero-wait pipelining.
<!-- openwiki: broken internal link [/openwiki/architecture/gemm_and_kernels.md] link "/openwiki/architecture/gemm_and_kernels.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
- [RDNA4 Kernel Architecture & GEMM](/openwiki/architecture/gemm_and_kernels.md) — Wave32, 24-VGPR granularity, LDS swizzling, and W4A8 GEMM.
<!-- openwiki: broken internal link [/openwiki/architecture/p2p_interconnect.md] link "/openwiki/architecture/p2p_interconnect.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
- [Dual-GPU P2P Interconnect & All-Reduce](/openwiki/architecture/p2p_interconnect.md) — Unified virtual addressing, WHT6 wire, and PCIe store drain.
<!-- openwiki: broken internal link [/openwiki/architecture/speculative_mtp.md] link "/openwiki/architecture/speculative_mtp.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
- [MTP Speculative Decoding & Draft Heads](/openwiki/architecture/speculative_mtp.md) — Multi-Token Prediction, FR-Spec 52k head, and adaptive depth.
<!-- openwiki: broken internal link [/openwiki/governance/quality_gates.md] link "/openwiki/governance/quality_gates.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
- [The 4-Tier Master Quality Gate & Epistemic Laws](/openwiki/governance/quality_gates.md) — Zero-regression governance and anti-hallucination laws.
<!-- openwiki: broken internal link [/openwiki/pipeline/upstream_watcher.md] link "/openwiki/pipeline/upstream_watcher.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
- [Upstream Codeberg Watcher & Autonomous Triage](/openwiki/pipeline/upstream_watcher.md) — Automated upstream monitoring and Jev System One triage.
