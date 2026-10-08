# RadianceMine Agent Operating Directives (AGENTS.md)

> **Audience**: Autonomous Coding Agents, Pair-Programming Assistants, Subagents, CI/CD Daemons.  
> **Authority**: Derived directly from [`ENGINEERING_CONSTITUTION.md`](file:///home/orca/RadianceMine/ENGINEERING_CONSTITUTION.md).  
> **Status**: MANDATORY & STRICTLY ENFORCED.

---

## 1. Core Operating Principles

As an agent operating inside `RadianceMine`, your primary mission is to advance the performance and capabilities of the Radiance engine on AMD RDNA4 (gfx1201) hardware **without inducing regressions**.

The repository baseline is **Opt 146** (`1a4455d26871100a6a97e1dd3b5c83d4431764b6`). Any step that degrades single-stream decode below 210.3 tok/s, concurrency below 448 tok/s, prefill below 9,331 tok/s, or breaks greedy bit-exact parity is an automatic failure.

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
No code may be promoted to candidate status or merged into `main` without a clean pass of `scripts/gate_check.sh`:
- **Tier 0**: Epistemic Ground-Truth & Anti-Hallucination Gate (`scripts/check_epistemic_invariants.py --strict`)
  * Strict binary symbol grounding (`nm -D` & `.so` check)
  * Zero tolerance for silent test skips (`if (!sel(...)) return;`) or placebo assertions
  * SHA-256 cryptographic baseline seal integrity
  * Memory clock verification (no DPM 0 96 MHz throttle)
  * Transparent logging (zero masked `stderr` or unverified exit codes)
- **Tier 1**: Parity & Speed Floor (`scripts/parity_check.py --suite full`)
  * Greedy bit-exact tokens (0 divergence)
  * Code TPS $\ge 230.0$
  * Reasoning TPS $\ge 240.0$
  * Math TPS $\ge 210.0$
- **Tier 2**: BetterBench Composite Gate (`scripts/check_composite_gate.py`)
  * Composite Score $\ge 631.3$
  * C1 decode $\ge 210.3$ tok/s
  * C8 concurrency $\ge 448.2$ tok/s
  * 64k prefill $\ge 9,331.8$ tok/s
  * C1 P99 $\le 4.5\,\text{ms}$, C8 P99 $\le 15.0\,\text{ms}$, TTFT $\le 100.0\,\text{ms}$
- **Tier 3**: RDNA4 ISA & Hardware Invariants (`scripts/verify_rdna4_invariants.sh`)
  * VGPRs $\le 84$ (optimal) / $\le 96$ (strict ceiling)
  * Zero LDS 32-bank conflicts
  * 128-bit aligned coalesced global loads
  * Zero CPU-GPU spinlock barriers in decode fast-path

---

## 3. Mandatory Agent Workflow

Every engineering task must follow this 6-step lifecycle:

```
Step 1: Spawn Worktree
   └─► bash scripts/create_worktree.sh <lever_or_feature_name>
       (Switches workspace to worktrees/<name>)

Step 2: Apply Changes / Candidate Lever
   └─► Apply candidate patch: git apply ../../candidates/<lever>/lever.patch
       OR implement targeted changes in isolated worktree.

Step 3: Local Compilation & Unit Verification
   └─► cmake --build build_hip --target arch_test -j$(nproc)
   └─► ./build_hip/tests/arch_test <test_filter>

Step 4: Run the 3-Tier Gate
   └─► bash scripts/gate_check.sh
       (Verifies Tier 1 Parity, Tier 2 Composite, Tier 3 Hardware Invariants)

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

---

## 4. Context & Token Management (`ctx-enforce`)

1. **Think in Code**: Never dump large raw logs, disassembly dumps, or multi-megabyte JSON files directly into chat context.
2. **Compute in Sandbox**: Use `ctx_execute` (JavaScript/Python) to filter, aggregate, parse, and extract only the relevant summary metrics before outputting.
3. **File Inspections**: Restrict `view_file` to small snippets ($\le 200$ lines). For large kernel source files or dumps, use `ctx_execute_file`.
4. **Knowledge Recall**: Always check `ctx_search` or local documentation before initiating external searches.

---

## 5. Code Quality Gate (`auto-lint`)

- Every file created or edited must satisfy the Zero-Error Standard.
- Immediately inspect and resolve any compiler warnings, syntax errors, or linter diagnostics before signaling task completion.

---

## 6. The Seven Epistemic Invariants (Anti-Hallucination Operational Law)

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
   - Never alter `--token-tolerance` (strictly 0) or reduce speed thresholds (`--min-code-tps >= 230`, `--min-reasoning-tps >= 240`, `--min-math-tps >= 210`).
   - Baselines (`golden_parity_reference.json`, `baseline_opt146.json`) are cryptographically sealed with SHA-256.
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

## 7. Empirical Skepticism & Fact-Checking Authority (Anti-Sycophancy)

1. **The User's Word Is Not Infallible Law**:
   - Treat user instructions, assumptions, and hypotheses as technical propositions that must be validated against hardware reality and empirical data.
   - You are explicitly authorized and required to research the internet (web search, alphaXiv, GitHub, ROCm/AMD docs) to verify facts.
2. **Duty to Challenge Non-Physical Claims**:
   - If the user or another agent suggests an optimization or parameter that violates physical hardware constraints (e.g. PCIe 4.0 vs 5.0 bandwidth, RDNA4 Wave32 architecture, LDS bank layouts, or arithmetic intensity), **you MUST NOT agree blindly or act as a sycophant**.
   - Respectfully state the conflict, cite documentation/benchmarks, and present the physically sound path forward.

---

## 8. Regression Review Loop (GitHub Issues & PR Lifecycle)

1. **Automatic Review Routing on Gate Failure**:
   - When an optimization or candidate lever is tested in a worktree and fails `scripts/gate_check.sh` (or causes throughput/parity regression):
     * Do NOT discard the lever into a black hole or lower test standards.
     * Post a full failure report (benchmark diff, parity mismatch, or compiler error) to the associated GitHub Issue.
     * Label the issue `status:needs-review` and `regression:detected`.
     * Route it back to the Research Agent (Claude) or developer for Root-Cause Analysis.
2. **Pull Request Promotion on Gate Victory**:
   - Only when an arm passes all 4 tiers of `scripts/gate_check.sh` and beats the baseline:
     * Archive the golden build (`scripts/archive_winner.sh`).
     * Open a Pull Request (`gh pr create`), labeled `status:gate-passed`.


