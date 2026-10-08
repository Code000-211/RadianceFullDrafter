# RadianceMine Agent Operating Directives (AGENTS.md)

> **Audience**: Autonomous Coding Agents, Pair-Programming Assistants, Subagents, CI/CD Daemons.  
> **Authority**: Derived directly from [`ENGINEERING_CONSTITUTION.md`](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md).  
> **Status**: MANDATORY & STRICTLY ENFORCED.

---

## 1. Core Operating Principles

As an agent operating inside `RadianceMine`, your primary mission is to advance the performance and capabilities of the Radiance engine on AMD RDNA4 (gfx1201) hardware **without inducing regressions**.

The repository baseline is **Opt 146** (`1a4455d26871100a6a97e1dd3b5c83d4431764b6`). Any step that degrades decode, C8 concurrency or 64k prefill versus `baselines/baseline_opt146.json` beyond the gate slack, or breaks greedy bit-exact parity, is an automatic failure. All thresholds live in `baselines/gate_thresholds.json`.

---

## 2. Hard Invariants (Prohibitions)

### ⛔ Prohibited Action 1: Editing `main` or Trunk Directly
- You MUST NEVER make edits, write scratch files, or execute builds directly in the root repository or on the `main` branch.
- `main` is strictly read-only and reserved for certified winning releases.
- Always create a dedicated Git worktree via `scripts/create_worktree.sh <name>`.

### ⛔ Prohibited Action 2: Destructive Deletions
- You MUST NEVER delete code, failed kernels, scripts, or test runs using `rm` or `git rm`.
- If an experiment fails or code is superseded, move it to `attic/<date>_<name>/` accompanied by a markdown post-mortem detailing the root cause of failure.

### ⛔ Prohibited Action 3: Toxic Runtime Flags & Environment Pollution
Forensic analysis proved that previous 60% performance crashes were caused by contaminated shell variables. You are strictly forbidden from introducing:
1. `RADIANCE_HEAT_RESIDENCY > 0`: Locking down MoE expert residency prevents dynamic adaptation across prompt domains (Chat $\to$ Code $\to$ Math) and forces active experts into PCIe Zero-Copy.
2. `NUM_SPECULATIVE_TOKENS > 3` (Static): Forcing static depth 5 without adaptive LCB fallback wastes GPU cycles on rejected speculative rounds.
3. `GPU_KEEP_ALIVE=1` or `gpu_sentinel`: Background polling daemons launch periodic GPU pulse kernels that inject PCIe contention and command-queue stalls during benchmarks.

### ⛔ Prohibited Action 4: Merging Without Passing the Master Gate
No code may be promoted to candidate status or merged into `main` without a clean pass of `scripts/gate_check.sh`. The gate is fail-closed: a tier that cannot run (no server, no candidate benchmark JSON) fails it, and `DRY_RUN=1` never passes. All thresholds and seals come from `baselines/gate_thresholds.json`:
- **Tier 0**: Epistemic Ground-Truth & Anti-Hallucination Gate (`scripts/check_epistemic_invariants.py --strict`)
  * Strict binary symbol grounding (`nm -D` & `.so` check)
  * Zero tolerance for silent test skips (`if (!sel(...)) return;`) or placebo assertions
  * SHA-256 cryptographic baseline seal integrity
  * Memory clock verification (no DPM 0 96 MHz throttle)
  * Transparent logging (zero masked `stderr` or unverified exit codes)
- **Tier 1**: Parity & Speed Floor (`scripts/parity_check.py --suite full`)
  * Greedy bit-exact tokens (0 divergence)
  * Code, reasoning and math decode floors (`tier1` in `gate_thresholds.json`)
- **Tier 2**: BetterBench Composite Gate (`scripts/check_composite_gate.py`)
  * Requires the candidate's benchmark results (`--bench-json`)
  * Composite score, C1 decode, C8 concurrency and 64k prefill must not degrade versus the baseline beyond `tier2.slack_pct` (baseline composite as computed by the script: 673.7)
  * C1/C8 ITL P99 and TTFT P50 must meet `tier2.latency_targets_ms` or not degrade versus the baseline
- **Tier 3**: RDNA4 ISA & Hardware Invariants (`scripts/verify_rdna4_invariants.sh`)
  * VGPRs $\le 84$ (optimal) / $\le 96$ (strict ceiling)
  * Zero LDS 32-bank conflicts
  * 128-bit aligned coalesced global loads
  * Zero CPU-GPU spinlock barriers in decode fast-path

### ⛔ Prohibited Action 5: Blind Exploration & Multi-File Dumps Without OpenWiki & LSP Grounding
- You MUST NEVER run blind directory sweeps, random grep patterns across all files, or dump large multi-thousand-line source files into conversation memory.
- You MUST query OpenWiki (`python3 scripts/locate_code.py "<task>"`) before inspecting code to obtain verified line numbers and ground-truth architectural claims.
- When tracing function call sites, usages, or cross-file relationships, you MUST use compiler-accurate language server tools (`pi-lens` / `clangd` via `pilens_lsp_navigation`, `pilens_symbol_search`, `pilens_read_symbol`) rather than eyeballing raw files.

---

## 3. Hardware Architecture Ground Truth (RDNA4 / gfx1201)

All architectural proposals, kernel modifications, and performance optimizations must be strictly calibrated against the physical dual AMD Radeon AI PRO R9700 hardware:
- **Compute Units**: 64 Dual CUs, native Wave32 scheduling (32 threads per wave).
- **LDS (Local Data Share)**: 64 KiB per CU across 32 banks (4 bytes/bank). Must use XOR swizzling to prevent bank conflicts.
- **Register Budget**: Max occupancy (4 waves/SIMD) requires $\le 84-96$ VGPRs per thread. Above 128 VGPRs occupancy collapses to 1-2 waves.
- **VRAM & Memory Bus**: 32 GB GDDR6 per card, 256-bit bus, 576 GB/s memory bandwidth.
- **Dual-GPU Interconnect**: PCIe 4.0 x16 slot-to-slot interconnect.
  * Measured Host-to-Device DMA: $28.29\,\text{GB/s}$.
  * Measured Device-to-Device P2P: $16.95\,\text{GB/s}$ bidirectional.
  * **FATAL ERROR TO AVOID**: Never assume PCIe 5.0 (63 GB/s)! Any math based on PCIe 5.0 will cause buffer starvation and prefetch stalls.
- **Memory Fence Ordering**: Avoid unconditional `__threadfence_system()` in per-thread execution loops. Use workgroup-leader store drains (`__threadfence_system()` once per workgroup) or RDNA4 store-release flags (`store_sys_rel`).

---

## 4. Mandatory Agent Workflow

Every engineering task must follow this 7-step lifecycle:

```
Step 0: Ground in OpenWiki & LSP (Zero-Blind-Exploration & Relationship Tracing)
   ├─► Macro Architecture: python3 scripts/locate_code.py "<task_or_query>"
   │   (Identifies exact subsystem, verified claims, and physical code spans)
   └─► Micro Relationships & Call Sites: pi-lens LSP / clangd
       (Uses pilens_lsp_navigation for references/incomingCalls, pilens_symbol_search,
        pilens_ast_grep_search, and pilens_read_symbol without full file dumping)

Step 1: Spawn Worktree
   └─► bash scripts/create_worktree.sh <lever_or_feature_name>
       (Switches workspace to worktrees/<name>)

Step 2: Apply Changes / Candidate Lever
   └─► Apply candidate patch: git apply ../../candidates/<lever>/lever.patch
       OR implement targeted changes in isolated worktree.

Step 3: Local Compilation & Unit Verification
   └─► cmake --build build_hip --target arch_test -j$(nproc)
   └─► ./build_hip/tests/arch_test <test_filter>

Step 4: Run the Master Quality Gate (Tier 0 - Tier 3)
   └─► bash scripts/gate_check.sh
       (Verifies Tier 0 Epistemic, Tier 1 Parity, Tier 2 Composite, Tier 3 Hardware Invariants)

Step 5: Process Results
   ├─► IF PASS:
   │     1. bash scripts/archive_winner.sh --name <name> --build-dir build_hip
   │     2. Submit merge request / notify orchestrator for fast-forward merge.
   │
   └─► IF FAIL:
         1. Document failure telemetry in worktree log.
         2. Move failing artifact to attic/ if valuable for diagnostics.
         3. Cleanly rollback via bash scripts/rollback_to_winner.sh --latest.
```

### 4.1 Candidate Lever Packaging Standard
When packaging a new optimization lever from literature or upstream, agents must structure it strictly in `candidates/`:
```
candidates/lever<N>_<name>/
├── README.md        # Comprehensive technical specification & mathematical roofline
├── lever.patch      # Clean git patch diff against golden baseline (Opt 146)
└── src/             # (Optional) Standalone modified kernel or header sources
```
The `README.md` must include:
1. **Metadata**: Status (`Verified Candidate`), Target Baseline (Opt 146), Source Paper/Repo (exact URLs + commit SHAs), Target Files.
2. **Expected Impact**: Quantified projection in $\text{tok/s}$ (Single-Stream Decode, Concurrency C8, or Cold 64k Prefill) and latency reduction ($\mu\text{s}$).
3. **Architectural & Mathematical Principles**: Equations, roofline analysis, and memory traffic calculations.
4. **AMD RDNA4 (gfx1201) Hardware Mapping**: LDS usage, VGPR occupancy, Wave32 scheduling, PCIe bus safety.
5. **Exact Implementation**: C++/HIP code diff or kernel blueprints.
6. **Master Gate Verification Protocol**: Concrete command to execute (`scripts/gate_check.sh`) and pass criteria.

### 4.2 Literature & Reference Grounding
- **alphaXiv**: Use alphaXiv tools (`discover_papers`, `get_paper_content`, `resolve_researchers`, `get_paper_notes`) to inspect methodology, equations, and ablation studies.
- **GitHub**: Search and inspect reference implementations (vLLM, SGLang, FlashAttention-3, DeepSeek, AsmEvo, CUTLASS, Composable Kernel).
- **Issue Dispatch**: Submit GitHub Issues labeled `research:new-lever` for automated triage. Upstream PRs are not dispatched automatically; they land in `candidates/upstream/REVIEW.md` for human review.

### 4.3 Multi-Agent Roles & Collaboration Protocol
- **Claude / Research Agents**: Academic & open-source mining, architectural modeling, candidate packaging, issue generation.
- **Antigravity / Execution Agents**: Git worktree management, HIP/C++ compilation, physical execution of Tier 0–3 Master Gates on the GPUs, PR creation and merging.
- **Communication Protocol**: GitHub Issues (`gh issue create`, `gh issue comment`) serve as the asynchronous coordination bridge between agents.

### 4.4 Code Intelligence & Relationship Tracing Protocol (OpenWiki + pi-lens/LSP)
To eliminate token waste and guarantee 100% compiler-accurate relationship tracing across the codebase, all code exploration must follow this 2-tier protocol:

| Exploration Dimension | Primary Tool | How To Use / Example | What It Solves |
|---|---|---|---|
| **Macro Architecture & Subsystem Invariants** | **OpenWiki + Jev System One** | `python3 scripts/locate_code.py "<query>"` or `openwiki_search` / `openwiki_read` | Identifies which subsystem owns a problem, the data flow, and which invariants must not be violated. |
| **Call Sites / References ("Where is this called?")** | **`pilens_lsp_navigation` (LSP)** | `pilens_lsp_navigation({ operation: "references", file: "core/engine.cpp", line: 120, character: 15 })` | Compiler-precise finding of every caller across all files (AST-level, handles overloads & templates). |
| **Call Hierarchy / Dependency Tree ("Who calls whom?")** | **`pilens_lsp_navigation` (Call Tree)** | `pilens_lsp_navigation({ operation: "incomingCalls", ... })` | Traces execution paths and callers upstream without manual searching. |
| **Fast Identifier Lookup** | **`pilens_symbol_search`** | `pilens_symbol_search({ query: "RadDraftState" })` | Ranked identifier lookup over warm word index. |
| **Symbol Extraction (Zero-Bloat Reading)** | **`pilens_read_symbol` / `pilens_read_enclosing`** | `pilens_read_symbol({ file: "libr4d/r4d_ar.hip", symbol: "r4d_ar_step_write" })` | Retrieves only the verbatim function body; prevents dumping 2,000 lines into context. |
| **Structural AST Patterns** | **`pilens_ast_grep_search`** | `pilens_ast_grep_search({ lang: "cpp", pattern: "RAD_ISSUE_N($$$)" })` | Searches syntax trees rather than plain text regex. |
| **Fallback (Standalone / Non-MCP)** | **Native `clangd` + `compile_commands.json`** | `/home/orca/.local/bin/clangd` or `ctx_execute` | Uses `compile_commands.json` symlink in workspace root for compiler flags. |

---

## 5. Context & Token Management (`ctx-enforce`)

1. **Think in Code**: Never dump large raw logs, disassembly dumps, or multi-megabyte JSON files directly into chat context.
2. **Compute in Sandbox**: Use `ctx_execute` (JavaScript/Python) to filter, aggregate, parse, and extract only the relevant summary metrics before outputting.
3. **File Inspections**: Restrict `view_file` to small snippets ($\le 200$ lines). For large kernel source files or dumps, use `ctx_execute_file`.
4. **Knowledge Recall**: Always check `ctx_search` or local documentation before initiating external searches.

---

## 6. Code Quality Gate (`auto-lint`)

- Every file created or edited must satisfy the Zero-Error Standard.
- Immediately inspect and resolve any compiler warnings, syntax errors, or linter diagnostics before signaling task completion.

---

## 7. The Seven Epistemic Invariants (Anti-Hallucination Operational Law)

Derived from Rule 5 of [`ENGINEERING_CONSTITUTION.md`](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md), every agent operating in `RadianceMine` is legally and technically bound by these seven operational laws:

1. **Zero Markdown Hearsay**:
   - Never cite an architectural lever, optimization, or kernel capability based on an audit report or markdown file.
   - Ground every statement in physical C++/HIP code and verified binary ELF symbols (`nm -D`).
2. **Strict Binary Grounding**:
   - Before claiming a kernel or operator is complete, verify that its symbol is exported in `build_hip/radiance_home/kernels/*.so`.
   - Never declare graph nodes (`RAD_OP`) for non-existent symbols.
3. **Anti-Silent-Skip & Full Test Assertion Policy**:
   - Tests must never mask errors with silent early returns (`if (!sel(...)) return;`).
   - Every test must execute physical assertions against engine functions, not local arithmetic tautologies.
4. **Absolute Immutability of Test Tolerances & Speed Floors**:
   - Never change `baselines/gate_thresholds.json`, the baselines or their SHA-256 seals on your own. The pre-commit hook blocks such commits unless `RADIANCE_GATE_CHANGE=1` is set, which only the human owner decides.
   - `scripts/gate_check.sh` must not pass `--token-tolerance` or `--min-*-tps` overrides.
5. **Hardware State & Clock Transparency**:
   - Always verify that GPU memory clocks are not throttled at 96 MHz (DPM 0) before running benchmarks.
   - Run warmup passes to elevate clocks to DPM 5 (1258 MHz).
6. **Mandatory Template & Endpoint Contract**:
   - Always query chat/reasoning models (`qwen4exp`) via `/v1/chat/completions` with structured message payloads (`messages: [{"role": "user", ...}]`).
   - Raw `/v1/completions` bypasses the Jinja template and reasoning parser, inducing artificial discrepancies.
7. **Transparent Context-Mode Logging**:
   - Never pipe critical test or benchmark execution to `/dev/null` without status checks.
   - Preserve `stderr` and check return codes for all subprocesses.

---

## 8. Empirical Skepticism & Fact-Checking Authority (Anti-Sycophancy)

1. **The User's Word Is Not Infallible Law**:
   - Treat user instructions, assumptions, and hypotheses as technical propositions that must be validated against hardware reality and empirical data.
   - You are explicitly authorized and required to research the internet (web search, alphaXiv, GitHub, ROCm/AMD docs) to verify facts.
2. **Duty to Challenge Non-Physical Claims**:
   - If the user or another agent suggests an optimization or parameter that violates physical hardware constraints (e.g. PCIe 4.0 vs 5.0 bandwidth, RDNA4 Wave32 architecture, LDS bank layouts, or arithmetic intensity), **you MUST NOT agree blindly or act as a sycophant**.
   - Respectfully state the conflict, cite documentation/benchmarks, and present the physically sound path forward.

---

## 9. Autonomous GitHub Control Plane & Orca Runner Lifecycle

1. **Goal Registration (`scripts/dispatch_goal.sh`)**:
   - Any agent or engineer can register a new objective via `./scripts/dispatch_goal.sh "<goal>" [candidate_slug]`.
   - New research tasks receive label `research:new-lever`.
   - Packaged candidates ready for GPU verification receive label `status:ready-to-test`.
2. **The Orca Autonomous Daemon Runner (`scripts/orca_agent_runner.sh`)**:
   - The daemon continuously monitors GitHub Issues for `status:ready-to-test`.
   - Transitions issue to `status:in-progress`.
   - Provisions clean isolated worktree (`scripts/create_worktree.sh`), applies patch, compiles via ROCm Ninja, hot-swaps dual GPUs via `scripts/engine_manager.sh`, and executes `scripts/gate_check.sh`.
3. **Pull Request Promotion on Gate Victory**:
   - Only when an arm passes all 4 tiers of `scripts/gate_check.sh` and beats the baseline:
     * Archive the golden build (`scripts/archive_winner.sh`).
     * Commit changes in worktree branch.
     * Open an automated Pull Request (`gh pr create`), labeled `status:gate-passed`.
     * Restore golden baseline engine on GPUs.
4. **Automatic Review Routing on Gate Failure**:
   - When an optimization fails any tier of `scripts/gate_check.sh`:
     * Immediately hot-swap GPUs back to golden baseline (`scripts/engine_manager.sh restore-golden`).
     * Collect telemetry and classify root cause with TypeSafe AI Jev (`scripts/typesafe_triage.py classify-regression`).
     * Post diagnostic failure report (`REGRESSION_REPORT.md`) as a comment to the associated GitHub Issue.
     * Label the issue `status:needs-review` and `regression:detected`.
     * Route it back to the Research Agent (Claude) for Root-Cause Analysis and patch correction.

<!-- OPENWIKI:START -->

## OpenWiki

This repository has a generated `openwiki/` evidence index. It is optional just-in-time context, not required startup reading.

- Do not enumerate, preload, or search wikis at task start. Use retrieval when the user asks for it, when unfamiliar architecture or dependency behavior materially affects the task, or when source inspection leaves an important uncertainty. Stop once the question is grounded.
- When those conditions apply and OpenWiki retrieval tools are available, use `openwiki_search` for just-in-time context and `openwiki_read` for the relevant complete sections. If search returns `workspace_required`, ask which listed workspace to use and retry with its ID.
- Use `openwiki_list_workspaces` or `openwiki_list_wikis` when workspace membership itself needs to be discovered.
- If the retrieval tools are unavailable, read `openwiki/quickstart.md` and follow its links to the relevant pages.
- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->
