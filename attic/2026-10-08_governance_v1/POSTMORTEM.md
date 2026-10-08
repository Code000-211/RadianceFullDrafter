# Post-mortem: Governance v1 (GitHub runner, absolute gate, golden archives)

**Retired:** 2026-10-08
**Replaced by:** `scripts/lever_queue.py` + `scripts/gh_bridge.py` (queue driven by GitHub issues),
`scripts/ab_gate.py` (A/B against the current baseline), `scripts/isa_diff.py`, Orca automations
(`docs/ORCA_AGENT_WORKFLOW.md`), `AGENTS.md` as the single rule file.

## What is here

- `scripts/`: `orca_agent_runner.sh`, `dispatch_goal.sh`, `test_candidate_lever.sh`,
  `archive_winner.sh`, `rollback_to_winner.sh`, `check_composite_gate.py`,
  `eval_patch_safety.py`, `verify_rdna4_invariants.sh`, `check_isa_compliance.sh`,
  `collect_telemetry.py`, `generate_agent_context.py`, `suggest_lever.sh`, `locate_code.py`,
  and a duplicate `golden_parity_reference.json`
- `releases/`: the "golden build" archive of Opt 146 and its catalog
- `docs/`: `ENGINEERING_CONSTITUTION.md`, `CODING_WORKFLOW_AND_GOVERNANCE_ARCHITECTURE.md`,
  `MASTER_PLAN.md`

## Why it was retired (all verified against the code on 2026-10-08)

1. **The gate passed without measuring.** Tier 1 was skipped when no server answered and the gate
   still printed "ALL PASSED" with exit 0; `DRY_RUN=1` counted as a pass; Tier 2 compared the
   baseline JSON with itself when no candidate results existed. Tier 0 and Tier 3 checked the
   sources of `main`, not the candidate.
2. **The stored baseline was not reproducible.** Re-running the unchanged `main` five times gave
   decode −7 % and C8 −16 % against `baseline_opt146.json` (measured the day before, before the
   commit it is named after). With 0 % slack every candidate would have failed. Prefill
   numbers depended on BetterBench's seeded nonces hitting the prefix cache (4k vs 75k tok/s).
3. **Floors and seals were self-referential.** Commit `9e8d704` regenerated the golden reference,
   rewrote its SHA-256 "seal" and lowered the reasoning floor from 240 to 210 tok/s in one commit;
   the pre-commit hook skipped every commit that touched only `scripts/`.
4. **The "golden build" contained no binary.** `bin/.reference_build` was an empty placeholder and
   `restore-golden` restarted `main/build_hip` instead of the archive.
5. **The GitHub runner could loop or hang.** Success left `status:ready-to-test` set (re-test every
   30 s); a failing build under `set -e` left issues on `in-progress` forever (issues #3, #4);
   `gh pr create` ran without a push; all `gh` errors were discarded.
6. **Worktree handling destroyed work.** `create_worktree.sh` reset an existing worktree's branch
   with `checkout -f -B … && reset --hard && clean -fd` and copied `main`'s binaries into it.
7. **Six rule documents contradicted each other** (PCIe Gen5 vs 4.0, reasoning floor 240 vs 210,
   3 vs 4 tiers, OpenWiki mandatory vs optional, composite 631.3 vs 673.7 computed).
8. **Jev decided things that can be measured** (ISA verdicts, regression root causes) and routed
   code lookup through a fixed list of 8 files (`locate_code.py`).
9. **Several lever patches were not real patches.** 6 of 12 do not apply (3 corrupt); lever 6 was
   written by a script with a made-up index hash and claims "verified, parity 4/4" without any
   measurement.
