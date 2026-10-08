---
type: pipeline
title: Upstream Codeberg Watcher & Autonomous Triage
description: Architecture of the automated upstream Codeberg watcher, TypeSafe AI (Jev System One) triage, deterministic patch safety auditing, and autonomous GitHub issue/PR creation.
tags: [upstream, codeberg, watcher, triage, jev, safety]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-a340bf0670437f776418bb8a
    resource: repo://scripts/watch_upstream.py
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# Upstream Codeberg Watcher & Autonomous Triage

The Upstream Watcher (`scripts/watch_upstream.py`) continuously tracks updates from the official upstream Radiance repository ([StillDeadcode/radiance](https://codeberg.org/StillDeadcode/radiance)). It screens all pull requests and commits in real-time, triaging their relevance and packaging viable candidates for autonomous testing without manual intervention.

## 1. Zero-Token Deterministic Pre-Filtering

To conserve API calls and maintain zero-cost idle operation:
- **State Deduplication**: `telemetry/upstream_seen.json` records every evaluated commit SHA and PR update timestamp. Polling cycles with no new events consume 0 tokens and perform 0 external AI calls.
- **0-Token Documentation Detection**: Patches modifying only documentation (`docs/`, `*.md`, `licenses/`) or CI configurations are classified deterministically without invoking external classifiers.

## 2. TypeSafe AI (Jev System One) Sub-100ms Triage

When a code PR is detected, metadata is evaluated via `typesafe_triage.py` against four calibrated criteria:
1. **Target Subsystem**: Classifies whether changes touch `gemm`, `gdn`, `qsa`, `moe`, `interconnect`, `drafter`, `tooling`, or `serving`.
2. **RDNA4 Hardware Violation Risk**: Returns a calibrated probability score [0.0, 1.0] flagging hardware incompatibilities (e.g., Nvidia PTX, Wave64 assumptions, >64KB LDS).
3. **Architectural Feasibility**: Evaluates ROCm HIP viability on a 0–4 score.
4. **Performance ROI**: Estimates throughput gains on dual R9700.

## 3. Deterministic Safety & Mergeability Audit

Before a candidate is queued:
- **Anti-Pattern Gate (`scripts/eval_patch_safety.py`)**: The raw `.patch` file is audited for prohibited patterns (unconditional per-thread `__threadfence_system()`, test tolerance tampering, and silent mocks).
- **Clean Mergeability**: `git apply --check` validates whether the patch applies cleanly to current `main` without merge conflicts.

## 4. Automated Candidate Packaging & GitHub Dispatch

Viable upstream contributions are automatically transformed into actionable testing units:
- **Candidate Packaging**: Files are written to `candidates/upstream/pr_{id}_{slug}/` containing `pr.patch`, `lever.patch`, `METADATA.json`, and an isolated testing walkthrough in `README.md`.
- **GitHub Issue Creation**: Qualified candidates automatically generate an issue on `OoguroRyuuya/RadianceMine` tagged with `upstream:candidate` and `status:ready-to-test`.
- **GitHub Draft Pull Request**: If the patch applies cleanly, an isolated git branch (`upstream/pr_{id}_{slug}`) is pushed and a Draft Pull Request is opened for visual diff review.
- **Queue Synchronization**: `candidates/upstream/QUEUE.md` is updated with live status, Jev scores, and issue/PR links.

## 5. Daemon Lifecycle Management

The background daemon is managed via `scripts/upstream_watcher_manager.sh`:
```bash
# Start watcher daemon (polling every 300s)
bash scripts/upstream_watcher_manager.sh start --interval 300

# Inspect daemon health and recent logs
bash scripts/upstream_watcher_manager.sh status

# Stop daemon
bash scripts/upstream_watcher_manager.sh stop
```
