# RadianceMine Engineering Constitution

> **Status**: BINDING & INVIOLABLE  
> **Target Baseline**: Radiance Opt 146 (`1a4455d26871100a6a97e1dd3b5c83d4431764b6`)  
> **Hardware Environment**: Dual AMD Radeon AI PRO R9700 (gfx1201, RDNA4, 64 CUs, Wave32, 576 GB/s GDDR6, PCIe Gen5 $\times 16$ `--tp-wire wht6`)  
> **Target Model**: Qwen3.8-Flash-Next / Qwen4Exp (FP8 trunk linears, IQ4R/W4 MoE 512 experts, top-$k=10$, GDN linear attention, MTP Spec 3–5)  

---

## Preamble

The Radiance project achieved an unprecedented milestone at **Opt 146** (calibrated speculative ladder, RidgeFill projector, CED predictive prefetching, 210.3 tok/s median decode, 9,331 tok/s 64k prefill, 448 tok/s C8 concurrency). Subsequent efforts suffered severe performance regressions—plummeting to 75.6 tok/s—not due to hardware faults, but due to unprincipled engineering: stacking unverified multi-agent experiments, polluting runtime environments with toxic flags (`RADIANCE_HEAT_RESIDENCY`, uncalibrated static draft depths, unsynchronized background polling daemons), and modifying trunk directly without regression gates.

This Constitution establishes an ironclad, mathematically grounded operating system for **RadianceMine**. Every contributor, human or autonomous agent, is bound by these four immutable laws.

---

## Rule 1: The Zero-Regression Invariant (Push/Merge Gate)

**No code is EVER merged into `main` unless it passes the Master Push/Merge Gate on physical dual-R9700 GPUs.**

Under no circumstances may speculative branches bypass any tier. A failure on a single check constitutes an unconditional rejection of the candidate.

```
       Candidate Branch / Worktree
                   │
                   ▼
┌──────────────────────────────────────┐
│  Tier 0: Epistemic Ground-Truth Gate │──[FAIL]──► Immediate Abort (No GPU Access)
│  (Physical Symbols, Anti-Skip, Seals)│
└──────────────────────────────────────┘
                   │ [PASS]
                   ▼
┌──────────────────────────────────────┐
│  Tier 1: Parity Check Gate           │──[FAIL]──► Immediate Rejection / Quarantine
│  (Exact Greedy & TPS Floor)          │
└──────────────────────────────────────┘
                   │ [PASS]
                   ▼
┌──────────────────────────────────────┐
│  Tier 2: BetterBench Composite Gate  │──[FAIL]──► Immediate Rejection / Quarantine
│  (Throughput, Prefill, Latency P99)  │
└──────────────────────────────────────┘
                   │ [PASS]
                   ▼
┌──────────────────────────────────────┐
│  Tier 3: RDNA4 ISA & Hardware Gate   │──[FAIL]──► Immediate Rejection / Quarantine
│  (VGPRs, LDS Banks, Coalescing, MMIO)│
└──────────────────────────────────────┘
                   │ [PASS]
                   ▼
       Admitted to Main Trunk
```

### Tier 0: Epistemic Ground-Truth & Anti-Hallucination Gate
- **Invocation**: `scripts/check_epistemic_invariants.py --strict` (orchestrated via `scripts/gate_check.sh --tier 0` or pre-commit hook)
- **Binary Grounding**: Every operator declared in headers must exist as an exported ELF symbol in the compiled shared library (`nm -D`).
- **Test Integrity**: Zero tolerance for early-exit test fall-throughs (`if (!sel(...)) return;`) or placebo assertion suites.
- **Cryptographic Seals**: SHA-256 baseline verification for `golden_parity_reference.json` and `baseline_opt146.json`.
- **Pre-Flight Hardware Clock Check**: Prevents benchmarking when GDN memory clocks are asleep at 96 MHz (DPM 0).
- **Execution Transparency**: Bars silent error suppression (`> /dev/null 2>&1` without status checks).

### Tier 1: Parity Check Gate
- **Invocation**: `scripts/parity_check.py --suite full` (orchestrated via `scripts/gate_check.sh --tier 1`)
- **Greedy Token Exactness**: Temperature $T=0.0$ greedy generation across all standardized prompts must produce **bit-exact token sequence matches** (0 discrepancy against certified golden references in `baselines/golden_parity_reference.json`).
- **Throughput Floors**:
  - **Code TPS**: $\ge \mathbf{230.0\,\text{tok/s}}$ (Prompt: `code_is_prime`)
  - **Reasoning TPS**: $\ge \mathbf{240.0\,\text{tok/s}}$ (Prompt: `reasoning_probability`)
  - **Math TPS**: $\ge \mathbf{210.0\,\text{tok/s}}$ (Prompt: `math_linear_eq`)
- **Failure Conditions**: Any token mismatch, premature end-of-turn token, hallucinated output pattern, or decode speed below any threshold immediately aborts the gate.

### Tier 2: BetterBench Composite Score Gate
- **Invocation**: `scripts/check_composite_gate.py <results.json> baselines/baseline_opt146.json`
- **Composite Score Invariant**: The weighted multi-workload composite score must match or exceed the baseline:
  $$\text{Composite Score} \ge \text{Baseline Score} \quad (\text{Baseline Opt 146} = 631.3, \text{Record} = 685.2)$$
- **Throughput Non-Degradation Floors**:
  - **C1 Single-Stream Combined Decode**: $\ge \mathbf{210.3\,\text{tok/s}}$ (zero net regression across weighted domains).
  - **C8 Concurrency Aggregate**: $\ge \mathbf{448.2\,\text{tok/s}}$ (strict stability within $\le 2\%$).
  - **Cold 64k Context Prefill**: $\ge \mathbf{9,331.8\,\text{tok/s}}$ (zero prefill throughput regression).
- **Strict Latency Guardrails**:
  - **C1 Decode Step P99**: $\le \mathbf{4.5\,\text{ms}}$
  - **C8 Step P99**: $\le \mathbf{15.0\,\text{ms}}$
  - **Time-to-First-Token (TTFT)**: $\le \mathbf{100.0\,\text{ms}}$ (hot single-stream prompt)

### Tier 3: RDNA4 ISA & Hardware Invariants
- **Invocation**: `scripts/verify_rdna4_invariants.sh` (or `scripts/check_isa_compliance.py`)
- **Zero LDS Bank Conflicts**:
  - RDNA4 Compute Units feature 32 physical LDS memory banks per dual-compute unit.
  - All shared memory indexing across Wave32 warps must maintain conflict-free bank strides:
    $$\text{Bank Index} = (\text{LDS Byte Address} \gg 2) \pmod{32}$$
  - Two threads within a Wave32 must never access distinct Dwords within the same bank simultaneously.
- **VGPR Occupancy Clamping**:
  - Architectural VGPR allocation granularity on gfx1201 is 24 registers.
  - Hot decode and draft kernels must strictly satisfy:
    $$\text{VGPR Count} \le \mathbf{84} \quad (\text{Optimal: 18 waves/SIMD}) \quad \text{Strict Ceiling} \le \mathbf{96} \quad (\text{16 waves/SIMD})$$
  - Exceeding 96 VGPRs triggers the severe RDNA4 occupancy cliff ($16 \to 12$ waves), collapsing memory hiding capacity.
- **Coalesced Memory Access**:
  - All global VRAM memory transactions across Wave32 must be 128-bit aligned vector operations (`global_load_b128` / `global_store_b128`).
  - Strided 32-bit single-lane non-coalesced accesses on the decode fast path are strictly prohibited.
- **Zero Redundant CPU Barriers**:
  - Zero synchronous CPU-GPU spinlocks (`hipDeviceSynchronize()`, blocking mutex locks) inside the single-step inference iteration.
  - Host-to-device HSA queue doorbell writes must be batched to minimize MMIO PCIe interconnect stalls.

---

## Rule 2: Mandatory Full Standalone Build Archival for Winning Arms

Whenever an experimental arm satisfies all three tiers of the push gate and establishes a certified performance gain over the current baseline:

1. **Complete Build Freezing**:
   The entire deployment payload must be captured without relying on ambient system state:
   - Compiled binary executable (`radiance` / `server`)
   - Complete `radiance_home` directory (including compiled `kernels.rkb`, vendor shared objects, and architecture definitions)
   - Configuration files (`config.json`, launch parameters)
   - Git commit SHA and explicit diff from base
   - Sanitized runtime environment variables (`env.sh`)
   - Full BetterBench `results.json` and parity verification logs
2. **Packaging & Cryptographic Integrity**:
   - The payload is packaged into `releases/golden_builds/<label>_<timestamp>.zip`.
   - A SHA256 checksum is computed and stored alongside as `<label>_<timestamp>.zip.sha256`.
   - The release is registered in `releases/golden_builds/catalog.json`.
3. **5-Second One-Click Rollback Script**:
   - Every archive generates a self-contained restoration script `restore.sh`.
   - Invoking `scripts/rollback_to_winner.sh <label>` must verify SHA256 integrity and restore the exact working binary, environment, and libraries in **under 5 seconds**.

---

## Rule 3: Strict Worktree Isolation

1. **Trunk Immutability**:
   `main` is **PERMANENTLY FROZEN** to the latest certified golden baseline. No direct commits or interactive edits may ever occur on `main`.
2. **Dedicated Git Worktrees**:
   All engineering, experimentation, kernel modifications, and performance profiling MUST occur in isolated Git worktrees spawned via:
   ```bash
   scripts/create_worktree.sh <feature_name>
   ```
   This creates `worktrees/<feature_name>` on branch `worktree/<feature_name>`.
3. **Clean Workspace Guarantees**:
   Worktrees maintain dedicated build directories and temporary log buffers. Trunk remains pristine at all times.
4. **Merge Protocol**:
   Only after `scripts/gate_check.sh` reports a clean 3-Tier PASS in the worktree may the branch be fast-forward merged into `main` by the release orchestrator.

---

## Rule 4: Zero Destructive Deletions

1. **Preservation of Intellectual Capital**:
   No code, patch, benchmark log, or architectural experiment is ever deleted with `rm` or `git rm` without archival.
2. **The Attic (`attic/`)**:
   - Deprecated implementations, superseded kernels, and negative experimental results must be moved to `attic/<date>_<description>/`.
   - Every entry in `attic/` must include a post-mortem document explaining:
     * The original hypothesis
     * The empirical failure mode (e.g. LDS conflict, PCIe saturation, cache eviction)
     * Why the code was retired
3. **Candidate Isolation (`candidates/`)**:
   - Candidate levers are maintained in clean, self-contained directories with unified patches (`lever.patch`), reference sources (`src/`), and mathematical documentation (`README.md`).

---

## Rule 5: The Seven Epistemic Invariants (Anti-Hallucination Law)

Following the forensic findings of `HOW_HALLUCINATIONS_CORRUPTED_THE_WORKTREE_AND_CONTEXT_MODE_POSTMORTEM.md`, all engineers and autonomous agents are strictly bound by the Seven Epistemic Invariants. Violations are automatically caught by Tier 0 (`scripts/check_epistemic_invariants.py`) and result in immediate rejection.

### 1. Zero Markdown Hearsay
- An agent shall NEVER cite an architectural feature, kernel, or optimization lever based solely on a markdown file (`.md`), transcript, or comment.
- Every claim must link directly to physical C++/HIP code and verified binary ELF symbols (`nm -D`).
- Speculative research notes must remain isolated in `candidates/` and never declared in production headers until a physical kernel exists.

### 2. Strict Binary Symbol Grounding
- No operator declaration (`RAD_OP`, `rad_arch_declare`, `op_*`) may exist in `arch/common/` or `libr4d/` without a backing compiled symbol in `build_hip/radiance_home/kernels/*.so`.
- Declaring ungrounded operators (e.g. phantom pooling kernels like `kv_csa3_kvarn_pool`) is classified as worktree corruption.

### 3. Anti-Silent-Skip & Full Test Assertion Policy
- Test suites must never simulate coverage through silent fall-throughs (`if (!sel(...)) return;`) or tests with zero physical assertions.
- Placebo tests asserting local mathematical constants rather than engine behavior are strictly prohibited.
- Self-tests must report failures whenever a claimed symbol or kernel fails to resolve.

### 4. Absolute Immutability of Test Tolerances & Speed Floors
- Test tolerances and performance floors are permanently locked.
- `--token-tolerance` in `scripts/parity_check.py` and `scripts/gate_check.sh` is strictly 0 (greedy exactness).
- Speed thresholds (`--min-code-tps >= 230.0`, `--min-reasoning-tps >= 240.0`, `--min-math-tps >= 210.0`) cannot be lowered under any circumstances.
- Golden reference vectors (`baselines/golden_parity_reference.json` and `baselines/baseline_opt146.json`) are sealed with immutable SHA-256 checksums verified by Tier 0.

### 5. Hardware State & Clock Transparency
- Benchmark runs and speed evaluations must verify that GPUs are NOT throttled at DPM 0 (96 MHz memory clock).
- Autonomous test harnesses must inspect `/sys/class/drm/card*/device/pp_dpm_mclk` or `rocm-smi` and ensure 1258 MHz MCLK before recording performance numbers.
- Automated warmup passes must prime the GPU before measuring decode or prefill throughput.

### 6. Mandatory Template & Endpoint Contract
- Chat and reasoning models (`Qwen3.8-Flash-Next` / `qwen4exp`) MUST always be queried via `/v1/chat/completions` with structured messages (`messages: [{"role": "user", ...}]`).
- Raw prompt posting to `/v1/completions` bypasses Jinja chat templating and thinking parsers, causing artificial divergence.
- Test suites must respect the model serving contract.

### 7. Transparent Context-Mode Logging
- Scripts executing in `context-mode` or automated subagent environments must never silently swallow `stderr` or ignore non-zero process exit codes (`> /dev/null 2>&1` without verification is barred).
- Lossy filter scripts matching only positive strings (`PASS`) while hiding fatal exceptions or ROCm VM page faults are strictly forbidden.

---

## Rule 6: Empirical Skepticism & Mandatory Fact-Checking (Anti-Sycophancy Law)

1. **User & Peer Input is a Hypothesis, Not Dogma**:
   - The user and peer agents are collaborative partners, NOT infallible oracles.
   - When the user proposes an idea, hypothesis, or parameter (e.g., PCIe bandwidth, kernel fusion strategy, speculative depth, or ISA instructions), all agents MUST treat it as a testable hypothesis rather than an unchallengeable absolute command.
2. **Authority & Duty to Research the Internet**:
   - All agents (Claude, AGY, subagents) are explicitly authorized and required to search the internet, academic literature (alphaXiv/arXiv), open-source repositories (GitHub), and official vendor manuals (AMD RDNA4 ISA, ROCm docs) to independently verify claims.
3. **Duty to Respectfully Challenge False Assumptions**:
   - If an agent discovers that an instruction, user premise, or peer proposal contradicts physical hardware reality (e.g. assuming PCIe 5.0 on a PCIe 4.0 slot, or claiming Wave64 on RDNA4), the agent **MUST NOT blindly comply or act sycophantically**.
   - The agent MUST challenge the assumption, cite the official documentation or empirical measurements, explain the risks, and propose the technically sound alternative.
4. **Automated Regression Review Lifecycle**:
   - Whenever an optimization lever or candidate fails `scripts/gate_check.sh` (or causes a performance drop in single-stream decode, concurrency, or prefill):
     * The lever is NEVER silently discarded or pushed with relaxed thresholds.
     * The automated system MUST post the exact failure diagnostic and benchmark diff to the corresponding GitHub Issue.
     * The issue MUST be labeled `status:needs-review` and `regression:detected` and routed back to the Research Agent (Claude) for forensic root-cause analysis and architectural revision.

---

## Enforcement & Penalties

Any automated agent or developer violating this Constitution will have their branch quarantined immediately:
- Commits made directly to `main` without worktrees will be hard-reset without confirmation.
- Submissions failing any tier of the push gate will be moved directly to `attic/failed_candidates/`.
- Runtime flag tampering (e.g. setting `RADIANCE_HEAT_RESIDENCY > 0`, disabling adaptive speculative fallbacks, or launching background pollers) is classified as malicious and strictly barred by automated pre-flight checks.
