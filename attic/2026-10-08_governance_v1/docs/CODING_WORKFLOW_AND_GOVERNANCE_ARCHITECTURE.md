# RadianceMine: Autonomous Coding Workflow & Governance Architecture
**Classification**: Master Engineering Blueprint & System Specification  
**Authority**: [ENGINEERING_CONSTITUTION.md](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md) & [AGENTS.md](file:///home/orca/RadianceMine/AGENTS.md)  
**Target Hardware**: Dual AMD Radeon AI PRO R9700 (gfx1201, RDNA4, TP2 PCIe 4.0 x16)  
**Baseline Anchor**: Opt 146 (Commit `1a4455d26871100a6a97e1dd3b5c83d4431764b6`)  
**Date**: October 2026

---

## Executive Summary: The Forensic Imperative

Between Build 33 and Build 191 of the Radiance engine, dozens of AI agents and human developers pushed performance experiments. Despite individual reports claiming "breakthroughs," the system suffered a catastrophic, compound regression:
- Concurrency C8 throughput collapsed from **534 tok/s** down to **262 tok/s** (-51%).
- Parity Check speed collapsed from **262 tok/s** down to **116 tok/s** (-55%).
- Cold 64k prefill throughput collapsed from **9,331 tok/s** down to **4,600 tok/s** (-50%).

An exhaustive forensic root-cause analysis ([FULL_OPT1_TO_OPT190_POSTMORTEM_AND_ROOT_CAUSE_ANALYSIS.md](file:///home/orca/RadianceMine/FULL_OPT1_TO_OPT190_POSTMORTEM_AND_ROOT_CAUSE_ANALYSIS.md) and [HOW_HALLUCINATIONS_CORRUPTED_THE_WORKTREE_AND_CONTEXT_MODE_POSTMORTEM.md](file:///home/orca/RadianceMine/HOW_HALLUCINATIONS_CORRUPTED_THE_WORKTREE_AND_CONTEXT_MODE_POSTMORTEM.md)) revealed four structural failure modes:
1. **The Subagent Telephone Game**: Hypotheses written in markdown scratchpads were cited by subsequent agents as verified physical code, leading to phantom optimizations (e.g. CED prefetch, non-existent FWHT kernels, placebo VGPR flags).
2. **Context Window Exhaustion & Blind Sweeps**: Agents dumped thousands of lines of raw C++/HIP code and grep logs into conversation memory, exhausting their reasoning capacity and suffering baseline amnesia.
3. **Silent Skips & Test Theater**: Tests used `if (!sel) return;` or arithmetic tautologies that passed without executing a single GPU assertion.
4. **Toxic Runtime Pollution**: Environment variables (`RADIANCE_HEAT_RESIDENCY > 0`, static `NUM_SPECULATIVE_TOKENS=5`, `gpu_sentinel`) locked memory, forced PCIe starvation, and degraded throughput by up to 60%.

To permanently eliminate these pathologies, **RadianceMine** was founded on a zero-regression, physically grounded architecture. This document defines the end-to-end engineering lifecycle, governance rules, and verification systems governing all development.

---

## System Architecture Overview

```
                                  ┌───────────────────────────────────────────────┐
                                  │   UPSTREAM CODEBERG WATCHER DAEMON (300s)     │
                                  │  0-Token Dedup + Jev System One Triage + Auto │
                                  │  GitHub Issue (#) & Draft Pull Request (PR)   │
                                  └──────────────────────┬────────────────────────┘
                                                         │
                                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                           TIER 1: MACRO ARCHITECTURE & GROUNDING                                │
│                          OpenWiki Knowledge Graph + Jev System One                              │
│                      python3 scripts/locate_code.py "<task_or_query>"                           │
│              (Resolves exact Subsystem, Architectural Invariants & Verified Claims)             │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                        TIER 2: MICRO RELATIONSHIPS & CALL-GRAPH TRACING                         │
│                           pi-lens MCP / clangd LSP / AST-Grep                                   │
│            • References & Call Sites: pilens_lsp_navigation({ operation: "references" })        │
│            • Call Hierarchy (Callers): pilens_lsp_navigation({ operation: "incomingCalls" })    │
│            • Warm Word Index:         pilens_symbol_search({ query: "..." })                    │
│            • Verbatim Symbol Extract: pilens_read_symbol (Zero whole-file dumps)               │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                           ISOLATED WORKTREE LIFECYCLE (TRUNK IMMUTABILITY)                      │
│                  bash scripts/create_worktree.sh <lever_or_feature_name>                        │
│                   Apply patch: git apply candidates/<lever>/lever.patch                         │
│                    Compile: cmake --build build_hip --target arch_test                          │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 4-TIER MASTER QUALITY GATE                                      │
│                               bash scripts/gate_check.sh                                        │
│  ├─► TIER 0: Epistemic Ground Truth Gate (check_epistemic_invariants.py - 6 Invariants)        │
│  ├─► TIER 1: Parity & Greedy Exactness Gate (parity_check.py --suite full - Tolerance: 0)       │
│  ├─► TIER 2: BetterBench Composite Score Gate (check_composite_gate.py - Composite >= Baseline) │
│  └─► TIER 3: RDNA4 ISA & Hardware Invariants Gate (verify_rdna4_invariants.sh - Wave32/VGPR)   │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        ▼                                                 ▼
               [PASS: NEW WINNER]                                  [FAIL: REGRESSION]
      1. bash scripts/archive_winner.sh                     1. Failure telemetry to GitHub Issue
      2. SHA-256 Release Catalog Update                     2. Label: regression:detected
      3. Fast-Forward Merge to main                         3. Rollback: rollback_to_winner.sh
```

---

## 1. The Seven Constitutional Rules (`ENGINEERING_CONSTITUTION.md`)

The [ENGINEERING_CONSTITUTION.md](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md) is the supreme legal and operational authority in the repository.

### Rule 1: The Zero-Regression Invariant (Push/Merge Gate)
No commit is ever merged into `main` unless it physically passes all 4 tiers of `scripts/gate_check.sh` on the physical dual AMD Radeon AI PRO R9700 GPUs. Any regression in single-stream decode (<210.3 tok/s), concurrency (<448 tok/s), 64k prefill (<9,331 tok/s), or greedy bit-exact parity is an immediate, unconditional block.

### Rule 2: Mandatory Full Standalone Build Archival for Winning Arms
Whenever a candidate lever beats the golden baseline:
- The entire build is frozen: compiled binaries, `radiance_home` (kernels, shared libraries, architectures), configuration files, git commit SHA, and BetterBench JSON telemetry.
- Packed into a standalone zip in `releases/golden_builds/` and sealed with SHA-256.
- An instant rollback script (`scripts/rollback_to_winner.sh`) is generated to restore that exact binary state in $<5$ seconds.

### Rule 3: Strict Worktree Isolation (Trunk Immutability)
`main` is strictly read-only and frozen to certified winning releases. All development, research, and experimentation occurs in isolated Git worktrees (`worktrees/<name>`). Agents must never edit files on `main` directly.

### Rule 4: Zero Destructive Deletions
Code, failed kernels, scripts, or test runs must never be deleted with `rm` or `git rm`. Superseded code is preserved in `attic/<date>_<name>/` accompanied by a forensic post-mortem explaining why it failed.

### Rule 5: The Seven Epistemic Invariants (Anti-Hallucination Law)
1. **Zero Markdown Hearsay**: Claims must link to physical C++/HIP code and binary ELF symbols (`nm -D`).
2. **Strict Binary Grounding**: Operators declared in headers must export matching physical symbols in compiled `.so` objects.
3. **Anti-Silent-Skip Policy**: Tests must never use `if (!sel) return;` or placeholder assertions.
4. **Absolute Immutability of Test Tolerances**: Greedy parity tolerance is strictly 0; speed floors cannot be lowered. Baselines are cryptographically sealed with SHA-256.
5. **Hardware Clock & DPM Transparency**: GPU memory clocks must be verified at 1258 MHz (DPM 5) before benchmarking; DPM 0 (96 MHz idle) throttled runs are invalid.
6. **Mandatory Endpoint Contract**: Chat models must be queried via `/v1/chat/completions` with Jinja templates to prevent artificial discrepancies.
7. **Transparent Context-Mode Logging**: Subprocesses must preserve `stderr` and check return codes.

### Rule 6: Prohibition of Toxic Runtime Flags
Contaminated environment variables are barred by automated pre-flight checks:
- `RADIANCE_HEAT_RESIDENCY > 0`: Banned (locks MoE experts, starves PCIe).
- Static `NUM_SPECULATIVE_TOKENS > 3`: Banned (wastes compute on rejected MTP drafts; adaptive bandit required).
- `GPU_KEEP_ALIVE=1` or `gpu_sentinel`: Banned (pulse kernels inject PCIe contention during benchmarks).

### Rule 7: Mandatory OpenWiki & Two-Tier Code Intelligence (Zero-Blind-Exploration Law)
- Agents are legally and technically prohibited from blind file sweeps or multi-file text greps.
- Code exploration must strictly follow the Two-Tier Protocol: OpenWiki for macro architecture, and `pi-lens`/LSP for micro relationships.

---

## 2. The 4-Tier Master Quality Gate (`scripts/gate_check.sh`)

Every candidate must pass the 4-Tier Master Gate sequentially before merge approval:

```
[Candidate Branch] ──► [Tier 0: Epistemic Gate] ──► [Tier 1: Parity Gate] ──► [Tier 2: Composite Gate] ──► [Tier 3: ISA Gate] ──► [Merge Approval]
```

### Tier 0: Epistemic Ground Truth Gate (`scripts/check_epistemic_invariants.py`)
Executed before hardware touch. Enforces 6 physical invariants:
1. **Binary Symbol Grounding**: Validates operator declarations against `nm -D` ELF symbols in `build_hip/radiance_home/kernels/*.so`.
2. **Anti-Silent-Skip Checker**: Scans test sources to eliminate dummy mocks and unasserted test bodies.
3. **Cryptographic Baseline Seal**: Validates SHA-256 hashes of `baselines/golden_parity_reference.json` and `baselines/baseline_opt146.json`.
4. **Hardware Clock Pre-Flight**: Inspects sysfs `pp_dpm_mclk` to ensure GPUs are not throttled at 96 MHz.
5. **Context-Mode Transparency Guard**: Detects and fails on silent `> /dev/null 2>&1` command suppressions.
6. **OpenWiki Knowledge & Claims Integrity**: Validates all 7 canonical OpenWiki architecture pages, 7 atomic `.claims/` definitions, `locate_code.py`, and constitutional rules.

### Tier 1: Parity & Greedy Exactness Gate (`scripts/parity_check.py`)
- **Greedy Parity**: `--token-tolerance 0` against Opt 146 reference completions across coding, reasoning, and mathematics suites.
- **Speed Floors**:
  * Code TPS: $\ge 230.0\,\text{tok/s}$
  * Reasoning TPS: $\ge 240.0\,\text{tok/s}$
  * Math TPS: $\ge 210.0\,\text{tok/s}$

### Tier 2: BetterBench Composite Score Gate (`scripts/check_composite_gate.py`)
Evaluates holistic throughput using the certified composite formula:
$$\text{Composite} = 0.40 \cdot \text{Decode}_{\text{median}} + 0.35 \cdot \text{Concurrency}_{C8} + 0.25 \cdot \left(\frac{\text{Prefill}_{64k}}{10}\right)$$
- Composite Score must exceed baseline ($\ge 631.3$).
- Hard individual guardrails: C1 Decode $\ge 210.3\,\text{t/s}$, C8 Concurrency $\ge 448.2\,\text{t/s}$, Cold 64k Prefill $\ge 9,331.8\,\text{t/s}$.
- Strict latency P99 limits: C1 P99 $\le 4.5\,\text{ms}$, C8 P99 $\le 15.0\,\text{ms}$, TTFT $\le 100.0\,\text{ms}$.

### Tier 3: RDNA4 ISA & Hardware Compliance Gate (`scripts/verify_rdna4_invariants.sh`)
- Disassembles all 1,600+ compiled objects using `llvm-objdump`.
- Flags VGPR cliff danger zones: $[94, 96]$ and $[118, 120]$ VGPRs.
- Verifies zero scratch memory spills (`scratch: 0 bytes`).
- Verifies XOR LDS swizzling across 32 banks (0 bank conflicts).
- Uses TypeSafe AI (Jev System One) for sub-100ms architectural hazard resolution.

---

## 3. Two-Tier Code Intelligence & Exploration Protocol

To eliminate context bloating, hallucinated call graphs, and token exhaustion:

### Tier 1: Macro Architecture (OpenWiki + Jev System One)
- **Fast Code Locator**:
  ```bash
  python3 scripts/locate_code.py "<question, subsystem, or task>"
  ```
- **Execution Speed**: $<100\,\text{ms}$, 0 LLM tokens consumed.
- **Output**: Subsystem classification, confidence score, exact canonical OpenWiki documentation page, and verified physical code spans (`repo://path#L...`).
- **OpenWiki MCP Retrieval**: When detailed architectural background is required, agents use native MCP tools `openwiki_search` and `openwiki_read`.

### Tier 2: Micro Relationships & Semantic Call Graph (`pi-lens` / LSP / clangd)
When tracing function callers, usages, or cross-file dependencies, agents MUST NOT use text greps or open multi-thousand-line files. They use the `pi-lens` MCP server:

```
┌───────────────────────────────────────┬────────────────────────────────────────────────────────────────────────┐
│ Objective                             │ pi-lens Tool & Syntax                                                  │
├───────────────────────────────────────┼────────────────────────────────────────────────────────────────────────┤
│ Find All Call Sites (References)      │ pilens_lsp_navigation({ operation: "references", file, line, col })   │
│ Trace Call Hierarchy (Callers)        │ pilens_lsp_navigation({ operation: "incomingCalls", file, line, col }) │
│ Fast Identifier Lookup (Word Index)   │ pilens_symbol_search({ query: "<SymbolName>" })                        │
│ Extract Symbol Source (Zero File Dump)│ pilens_read_symbol({ file: "<path>", symbol: "<name>" })              │
│ Smallest Enclosing Scope              │ pilens_read_enclosing({ file: "<path>", line: <number> })              │
│ Semantic AST Structural Search        │ pilens_ast_grep_search({ lang: "cpp", pattern: "RAD_ISSUE_N($$$)" })   │
│ Module Structure Outline              │ pilens_module_report({ file: "<path>" })                               │
│ Fallback (Non-MCP CLI)                │ clangd via compile_commands.json symlink in workspace root             │
└───────────────────────────────────────┴────────────────────────────────────────────────────────────────────────┘
```

---

## 4. The Autonomous GitHub Control Plane & Orca Agent Runner (`scripts/orca_agent_runner.sh`)

To eliminate informal chat promises, context loss across turns, and unverified code merges, RadianceMine anchors its entire operational lifecycle in **GitHub Issues and Pull Requests as an asynchronous, durable state machine**.

The autonomous daemon on the host (`orca` user / system runner) is **`scripts/orca_agent_runner.sh`**, which continuously coordinates between GitHub and the physical dual AMD Radeon AI PRO R9700 GPUs.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        AUTONOMOUS GITHUB & ORCA CONTROL PLANE                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   Human / Agent Goal                                                                   │
│   (dispatch_goal.sh)                                                                   │
│           │                                                                            │
│           ▼                                                                            │
│   GitHub Issue Created                                                                 │
│   [research:new-lever] ────────► Claude / Research Agent                               │
│                                  (OpenWiki + pi-lens LSP + AlphaXiv)                   │
│                                  Packages lever in candidates/<slug>/                  │
│                                           │                                            │
│                                           ▼                                            │
│   GitHub Issue Labeled                                                                 │
│   [status:ready-to-test]                                                               │
│           │                                                                            │
│           ▼                                                                            │
│   Orca Daemon Runner (scripts/orca_agent_runner.sh, poll interval: 30s)                │
│           │                                                                            │
│           ├─► Labels issue: [status:in-progress]                                       │
│           ├─► Step 0: eval_patch_safety.py (Deterministic static safety audit)         │
│           ├─► Step 1: scripts/create_worktree.sh (Isolated Git worktree)               │
│           ├─► Step 2: git apply lever.patch (Clean patch application)                  │
│           ├─► Step 3: ninja -C build_hip (ROCm C++/HIP gfx1201 compilation)            │
│           ├─► Step 4: scripts/engine_manager.sh restart (Hot-swap dual GPUs)           │
│           └─► Step 5: scripts/gate_check.sh (Executes 4-Tier Master Quality Gate)       │
│                       │                                                                │
│         ┌─────────────┴────────────────────────┐                                       │
│         ▼                                      ▼                                       │
│   [GATE PASSED (RC=0)]                   [GATE FAILED (RC!=0)]                         │
│   1. scripts/archive_winner.sh           1. engine_manager.sh restore-golden           │
│      (SHA256 golden bundle)                 (Immediate GPU rollback)                   │
│   2. gh pr create                        2. collect_telemetry.py &                     │
│      (Head: worktree/<slug>, Base: main)    typesafe_triage.py classify-regression     │
│   3. gh issue edit                       3. gh issue comment (Diagnostic failure dump) │
│      [status:gate-passed]                4. gh issue edit                              │
│   4. Human reviews & merges PR              [status:needs-review, regression:detected] │
│                                          5. Re-routed to Claude for Root Cause Analysis│
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 The GitHub Issue State Machine

Every task, optimization hypothesis, and upstream evaluation is represented as a GitHub Issue with explicit, mutually exclusive status labels:

| Issue Label | Meaning & Active Owner | Next Transition |
|---|---|---|
| `research:new-lever` | High-level goal registered. Active Owner: **Research Agent (Claude)**. | Moves to `status:ready-to-test` once packaged in `candidates/<slug>/`. |
| `status:ready-to-test` | Candidate lever packaged with `README.md` and `lever.patch`. Active Owner: **Orca Runner**. | Orca picks up the issue, transitions to `status:in-progress`. |
| `status:in-progress` | Isolated worktree active, candidate building or running on dual R9700 GPUs. | Moves to `status:gate-passed` or `status:needs-review`. |
| `status:gate-passed` | 4-Tier Master Gate passed cleanly. Pull Request opened against `main`. | Human review & merge into `main`. |
| `status:needs-review` | Master Gate failed or compiler error. Telemetry attached. Active Owner: **Claude**. | Claude inspects `REGRESSION_REPORT.md`, updates patch, resets to `status:ready-to-test`. |
| `regression:detected` | Flags that the candidate regressed speed, parity, or ISA invariants. | Remains until fixed or candidate rejected to `attic/`. |

### 4.2 Dispatching Objectives: `scripts/dispatch_goal.sh`

Any agent or human engineer can trigger the autonomous pipeline by executing:
```bash
./scripts/dispatch_goal.sh "<Goal Description>" [candidate_lever_slug]
```
- If an existing candidate package matches (e.g. `lever6_fast_store_drain_p2p_ar`), it generates a structured issue labeled `status:ready-to-test` and immediately triggers `test_candidate_lever.sh`.
- If it is a new research idea, it creates an issue labeled `research:new-lever` populated with context via `scripts/generate_agent_context.py --role research`.

### 4.3 The Orca Autonomous Runner: `scripts/orca_agent_runner.sh`

The Orca daemon runs in the background on the host system:
```bash
# Continuous daemon mode (polls every 30s)
./scripts/orca_agent_runner.sh

# One-shot mode (processes current queue once and exits)
ONE_SHOT=1 ./scripts/orca_agent_runner.sh
```
Key Invariants enforced by Orca:
1. **Trunk Immutability**: Orca never checks out or compiles on `main`. All operations occur in `worktrees/<candidate_slug>`.
2. **GPU Engine Protection**: If a candidate engine crashes on startup or hangs during testing, Orca immediately executes `scripts/engine_manager.sh restore-golden` to bring the healthy baseline back online.
3. **Structured Failure Telemetry**: Gate failures trigger `collect_telemetry.py` and `typesafe_triage.py classify-regression` (Jev System One), diagnosing whether the issue is LDS bank conflict, PCIe bus contention, parity drift, or compilation failure.

---

## 5. Upstream Watcher (Review List Only)

The upstream repository ([StillDeadcode/radiance](https://codeberg.org/StillDeadcode/radiance)) is polled by a background service that only prepares a reading list for a human:

```
Codeberg REST API (open PRs + changed files) ──► Jev: "could this be useful for us?" ──► candidates/upstream/REVIEW.md
```

1. **Service**: `radiance-upstream-watcher.service` (systemd, `Restart=always`, unit file in `scripts/systemd/`). Runs as `orca` without GitHub credentials or docker socket and may write only to `telemetry/` and `candidates/upstream/`. `scripts/upstream_watcher_manager.sh` is only a fallback for hosts without the unit.
2. **Triage**: one Jev `noul` question per PR (title, description, changed-file list, our 2×R9700 / TP2 setup). PRs are re-classified only when title, description or file list change. State: `telemetry/upstream_review.json`.
3. **Review list**: `candidates/upstream/REVIEW.md` with sections *Ansehen* (usefulness ≥ 0.5 or unclassified), *Von Jev aussortiert* and *Bereits angesehen*. Mark reviewed with `python3 scripts/watch_upstream.py --done <PR> ...`; a PR returns to the list if it changes upstream.
4. **No automation beyond the list**: the watcher never creates issues, labels, branches or PRs, and never applies, builds or runs upstream code. Promoting an upstream PR into a candidate is a manual decision.

The previous auto-dispatch design is retired; see `attic/2026-10-08_upstream_watcher_v1/POSTMORTEM.md`.

---

## 6. Candidate Lever Packaging Standard

Every proposed optimization lever must be self-contained and isolated in `candidates/lever<N>_<name>/`:

```
candidates/lever<N>_<name>/
├── README.md        # Mathematical roofline, RDNA4 Wave32 mapping, expected ROI
├── lever.patch      # Clean git patch diff against golden baseline (Opt 146)
└── src/             # (Optional) Standalone modified kernel or header sources
```

### Mandatory `README.md` Specification Standard:
1. **Metadata**: Status (`Verified Candidate`), Baseline (`Opt 146`), Target Files, References.
2. **Expected Impact**: Quantified gains in tok/s and latency ($\mu\text{s}$).
3. **Architectural & Mathematical Principles**: Equations, arithmetic intensity, memory bandwidth formulas.
4. **AMD RDNA4 (gfx1201) Hardware Mapping**: LDS usage ($\le 64\,\text{KiB}$, XOR swizzle), VGPR occupancy ($\le 84-96$), PCIe 4.0 bus safety.
5. **Exact Implementation**: Clean C++/HIP diff.
6. **Master Gate Verification Protocol**: Exact commands to execute and pass criteria.

---

## 7. Multi-Agent Roles & Collaboration Protocol

Directives for all agents are unified in [AGENTS.md](file:///home/orca/RadianceMine/AGENTS.md), with `CLAUDE.md` and `GEMINI.md` maintained as symbolic links to eliminate duplication:

```
CLAUDE.md ──► AGENTS.md ◄── GEMINI.md
```

### Division of Responsibilities:
- **Research Agents (Claude / Literature Miners)**:
  * Academic literature mining (alphaXiv).
  * Open-source kernel analysis (GitHub: vLLM, SGLang, FlashAttention-3, DeepSeek, AsmEvo, CUTLASS).
  * Macro-architecture exploration via OpenWiki (`openwiki_search`, `openwiki/quickstart.md`).
  * Micro-call site exploration via `pi-lens` / LSP `clangd` (`pilens_read_symbol`, `pilens_ast_grep_search`).
  * Mathematical roofline modeling and candidate lever packaging (`candidates/lever<N>_<slug>/`).
  * Issue creation with label `research:new-lever`.
- **Execution Agents (Antigravity / Engineering Agents)**:
  * Worktree management (`create_worktree.sh`).
  * HIP/C++ compilation (`ninja -C build_hip`).
  * Execution of the 4-Tier Master Quality Gate on the dual R9700 GPUs.
  * Standalone build archival (`archive_winner.sh`) and Pull Request creation (`gh pr create`).
- **Autonomous Daemons (Orca Runner & Upstream Watcher)**:
  * **Orca Runner (`scripts/orca_agent_runner.sh`)**: Background poller (30s interval) monitoring GitHub Issues for `status:ready-to-test`. Executes isolated worktree testing, engine hot-swapping, and gate verification.
  * **Upstream Watcher (`scripts/watch_upstream.py`)**: 24/7 polling of upstream Codeberg. Writes a human review list (`candidates/upstream/REVIEW.md`); no issues or PRs.
- **Asynchronous Communication Bridge**: GitHub Issues (`gh issue create`, `gh issue comment`) and Draft PRs serve as the official durable boundary between all agents.

### Empirical Skepticism & Anti-Sycophancy:
- The user's instructions or hypotheses are treated as technical propositions, not infallible laws.
- Agents have the explicit duty to challenge any suggestion violating physical hardware reality (e.g. PCIe 4.0 vs 5.0, RDNA4 Wave32, LDS bank layouts) using verified data and documentation.

---

## 8. The Complete End-to-End Operational Lifecycle ("Wie wir ab jetzt arbeiten")

This is the standard operational procedure for all engineering and optimization tasks in RadianceMine:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    END-TO-END OPERATIONAL LIFECYCLE FOR OPTIMIZATIONS                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│ 1. GOAL REGISTRATION                                                                   │
│    User or Agent runs: ./scripts/dispatch_goal.sh "<Description>"                      │
│    GitHub Issue created with label: [research:new-lever]                               │
│                                                                                        │
│ 2. RESEARCH & GROUNDED PACKAGING (Claude / AGY)                                        │
│    - Consult OpenWiki (.claims/) for macro architecture.                               │
│    - Consult pi-lens / LSP for micro call sites & AST patterns.                        │
│    - Write clean patch in: candidates/lever<N>_<slug>/lever.patch                      │
│    - Write architectural README.md with mathematical roofline & gfx1201 mapping.       │
│    - Run static safety audit: python3 scripts/eval_patch_safety.py <patch>             │
│    - Update GitHub Issue label: [status:ready-to-test]                                 │
│                                                                                        │
│ 3. AUTONOMOUS ISOLATED WORKTREE TESTING (Orca Runner)                                  │
│    - Orca Runner picks up issue -> labels [status:in-progress]                         │
│    - Creates clean worktree: scripts/create_worktree.sh <slug>                         │
│    - Applies patch: git apply lever.patch                                              │
│    - Builds binary: ninja -C build_hip (ROCm C++/HIP gfx1201)                          │
│    - Hot-swaps dual GPUs: scripts/engine_manager.sh restart --build-dir <worktree>     │
│    - Runs 4-Tier Master Gate: scripts/gate_check.sh --build-dir <worktree>             │
│                                                                                        │
│ 4. GATE VERDICT:                                                                       │
│                                                                                        │
│    [VICTORY: RC == 0]                                                                  │
│    a) Golden Archival: scripts/archive_winner.sh (creates SHA256 tarball & rollback)   │
│    b) Commit in worktree branch: worktree/<slug>                                       │
│    c) Open GitHub PR: gh pr create --head worktree/<slug> --base main                 │
│    d) Update Issue: [status:gate-passed], comment with benchmark metrics               │
│    e) Restore baseline engine on GPUs: scripts/engine_manager.sh restore-golden        │
│    f) Human merges clean PR into main.                                                 │
│                                                                                        │
│    [REGRESSION: RC != 0]                                                               │
│    a) Instant Rollback: scripts/engine_manager.sh restore-golden (protects GPUs)        │
│    b) Structured Telemetry: scripts/collect_telemetry.py                               │
│    c) Root-Cause AI Classification: python3 scripts/typesafe_triage.py                 │
│    d) Write REGRESSION_REPORT.md in worktree                                           │
│    e) Post Diagnostic Dump to GitHub Issue comment                                     │
│    f) Label Issue: [status:needs-review, regression:detected]                          │
│    g) Re-route to Claude for Root-Cause Analysis and patch fix                         │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Hardware Ground Truth & Calibration Baseline

All math, models, and code must be calibrated against physical reality:

```
┌─────────────────────────────────┬─────────────────────────────────────────────────────────────┐
│ Hardware Component              │ Physical Ground Truth Specification                         │
├─────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ GPUs                            │ Dual AMD Radeon AI PRO R9700 (gfx1201, RDNA4)               │
│ Compute Units                   │ 64 Dual CUs, native Wave32 scheduling (32 threads/wave)     │
│ LDS (Local Data Share)          │ 64 KiB per CU, 32 banks (4 bytes/bank). XOR swizzle required│
│ VGPR Occupancy Budget           │ <= 84-96 VGPRs/thread (4 waves/SIMD). Above 128 collapses   │
│ VRAM & Bandwidth                │ 32 GB GDDR6 per card (256-bit bus, 576 GB/s)                │
│ Interconnect                    │ PCIe 4.0 x16 slot-to-slot (Host DMA: 28.29 GB/s, P2P: 16.95)│
│ CRITICAL INVARIANT              │ Strictly PCIe 4.0! Never assume PCIe 5.0 (63 GB/s)!        │
│ Memory Fences                   │ Store-drain / store_sys_rel; avoid unconditional sys-fences │
└─────────────────────────────────┴─────────────────────────────────────────────────────────────┘
```

### Golden Baseline Targets (Opt 146 / Commit `1a4455d`):
- **Single-Stream Decode**: $210.3 - 262.7\,\text{tok/s}$ (Code $\ge 230$, Reasoning $\ge 240$, Math $\ge 210$)
- **Concurrency C8**: $448.2\,\text{tok/s}$ (Latency P99 $\le 15.0\,\text{ms}$)
- **Cold 64k Prefill**: $9,331.8\,\text{tok/s}$ (TTFT $\le 100.0\,\text{ms}$)
- **Greedy Parity**: Tolerance strictly 0 (bit-exact greedy completions across all domains).

---

## Verification & Self-Test Verification

Every component of this workflow has been verified on the physical host:
1. `bash scripts/verify_ground_truth.sh`: 6/6 Invariants Clean Pass.
2. `python3 scripts/locate_code.py "P2P Store Drain"`: Subsystem resolved in 62 ms with 100% confidence.
3. `pi-lens-mcp`: Tested over JSON-RPC 2.0 stdio with live symbol search and AST-grep queries.
4. Upstream Watcher: `radiance-upstream-watcher.service` (systemd), writing `candidates/upstream/REVIEW.md`.
