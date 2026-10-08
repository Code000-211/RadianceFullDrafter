# Post-mortem: Upstream watcher v1 (auto issues / draft PRs)

**Retired:** 2026-10-08
**Replaced by:** `scripts/watch_upstream.py` v2 (Jev usefulness triage into `candidates/upstream/REVIEW.md`), run as `radiance-upstream-watcher.service`.

## Contents

- `pr_<id>_<slug>/`: candidate packages (`pr.patch`, `lever.patch`, `METADATA.json`, `README.md`) written by v1 for 30 upstream PRs.
- `QUEUE.md`: v1 triage table.
- `upstream_seen.json`: v1 state file (was `telemetry/upstream_seen.json`, git-ignored).

## Why it was retired

1. **Untrusted code on the path to execution.** v1 labelled upstream PRs `status:ready-to-test` once Jev rated them READY and `git apply --check` passed. The ORCA runner picks that label up and runs `cmake`/`ninja` and the engine with no human approval. GitHub issues #5 and #7–#15 were created this way.
2. **Pushed foreign code to origin.** `--create-prs` committed upstream patches on `upstream/*` branches, pushed them and opened draft PRs (#6) regardless of triage status. Changes under `.github/` were classified as "docs/CI" and skipped every check.
3. **The safety check was not a security check.** `eval_patch_safety.py` only looks for performance anti-patterns, and it passed when the script was missing.
4. **Triage saw only the PR title and description.** Jev rated 3- and 4-rank all-reduce PRs (#12, #14, #54, #55) READY_TO_TEST on a 2-GPU box.
5. **Candidate packages were indistinguishable from real levers.** `test_candidate_lever.sh` resolves `candidates/upstream/<slug>`, so these folders were directly runnable by ORCA.

## What v2 does instead

It reads open PRs and their changed-file list from Codeberg and asks Jev a single question: could this be useful for our 2×R9700 / TP2 setup? It writes the answer into a human review list. It does not touch GitHub, branches, worktrees or patches.
