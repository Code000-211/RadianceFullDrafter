---
type: pipeline
title: Upstream Codeberg Watcher (Review List)
description: Upstream Codeberg watcher that asks Jev whether open PRs could be useful and writes a human review list. No GitHub issues, PRs or code execution.
tags: [upstream, codeberg, watcher, triage, jev, review]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-a340bf0670437f776418bb8a
    resource: repo://scripts/watch_upstream.py
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# Upstream Codeberg Watcher (Review List)

`scripts/watch_upstream.py` polls the open pull requests of the upstream Radiance repository ([StillDeadcode/radiance](https://codeberg.org/StillDeadcode/radiance)) and maintains a reading list for a human. It does not dispatch anything.

## 1. What it does per PR

1. Fetches title, description and the changed-file list (`/pulls/{n}/files`) from the Codeberg API.
2. Asks Jev one `noul` question: could this PR plausibly be useful for our setup (2× R9700, gfx1201, PCIe 4.0, TP world size 2, ROCm only, Qwen FP8 MoE)? PRs that only matter for 3+ GPUs, CUDA or other model families should score low.
3. Stores the result in `telemetry/upstream_review.json`. A PR is re-classified only when its title, description or file list changes.

## 2. Review list

`candidates/upstream/REVIEW.md` has three sections:
- **Ansehen**: usefulness ≥ 0.5 (`--threshold`), or unclassified because Jev failed.
- **Von Jev aussortiert**: below the threshold, kept visible so misjudgements can be spotted.
- **Bereits angesehen**: marked with `python3 scripts/watch_upstream.py --done <PR> ...`. A PR moves back to *Ansehen* if it changes upstream.

## 3. What it never does

It never creates GitHub issues, labels, branches or PRs, and never downloads, applies, builds or runs upstream patches. Turning an upstream PR into a candidate lever is a manual decision. The earlier auto-dispatch design was retired on 2026-10-08 (`attic/2026-10-08_upstream_watcher_v1/POSTMORTEM.md`).

## 4. Operation

It runs as the systemd service `radiance-upstream-watcher` (unit: `scripts/systemd/radiance-upstream-watcher.service`, `Restart=always`, interval 300 s). The unit runs as `orca` with no GitHub credentials, no docker socket and write access only to `telemetry/` and `candidates/upstream/`. A file lock (`telemetry/watcher.lock`) prevents a second daemon.

```bash
systemctl status radiance-upstream-watcher
journalctl -u radiance-upstream-watcher -f      # root or systemd-journal group
python3 scripts/watch_upstream.py --pr 56       # re-classify one PR now
python3 scripts/watch_upstream.py --done 56 51  # mark as reviewed
```

`scripts/upstream_watcher_manager.sh` remains as a nohup fallback for hosts without the unit and refuses to start when the unit is enabled.
