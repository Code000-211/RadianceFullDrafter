---
type: governance
title: The 4-Tier Master Quality Gate & Epistemic Laws
description: Governance framework and automated 4-Tier Master Quality Gate enforcing zero-regression invariants, epistemic truth, greedy parity, and RDNA4 ISA compliance.
tags: [governance, quality-gate, parity, epistemic, zero-regression, isa]
verified:
  - by: openwiki/0.6.1
    at: 2026-10-08T09:22:05.134Z
sources:
  - id: openwiki-source-b14428d37d54a5651ece7cc9
    resource: repo://scripts/check_epistemic_invariants.py
  - id: openwiki-source-72ad8968cc39197079aa5d36
    resource: repo://scripts/gate_check.sh
  - id: openwiki-source-29605c6afd5c06f404015f83
    resource: repo://scripts/parity_check.py
generated: { by: "antigravity", at: "2026-10-08T09:22:05.134Z" }
---

# The 4-Tier Master Quality Gate & Epistemic Laws

Under Rule 1 and Rule 5 of the [Engineering Constitution](repo://ENGINEERING_CONSTITUTION.md), no code is ever merged into `main` unless it passes all four automated tiers of `scripts/gate_check.sh` on physical hardware (dual AMD Radeon AI PRO R9700).

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: an unescaped angle bracket inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
    Candidate["Candidate Patch / Branch"] --> T0["Tier 0: Epistemic Ground Truth Gate<br/>Binary symbols, SHA-256 seal, DPM clocks"]
    T0 -->|Pass| T1["Tier 1: Parity & Exactness Gate<br/>Token tolerance: 0, Code >= 230, Reasoning >= 240"]
    T1 -->|Pass| T2["Tier 2: Composite Score Gate<br/>Composite >= Baseline Opt 146, C1/C8/64k guardrails"]
    T2 -->|Pass| T3["Tier 3: RDNA4 ISA Compliance Gate<br/>24-VGPR cliffs, zero waterfall, zero scratch spills"]
    T3 -->|All Pass| Merge["Approved for Main / Golden Release"]
```

## 1. Tier 0: Epistemic Ground Truth Gate

The Epistemic Gate (`scripts/check_epistemic_invariants.py`) prevents AI hallucinations before testing:
- **Binary Symbol Physical Grounding**: Scans operator declarations in header files and verifies their exported ELF symbols in compiled `.so` binaries using `nm -D`.
- **Anti-Silent-Skip Policy**: Parses test source files to detect and reject mock patterns such as `if (!sel) return;` or empty test bodies where assertions are bypassed.
- **Cryptographic Baseline Seal**: Enforces SHA-256 checksum validation on `baselines/golden_parity_reference.json` and `baselines/baseline_opt146.json` to prevent tolerance degradation.
- **Hardware DPM Pre-Flight Verification**: Reads GPU sysfs entries (`pp_dpm_mclk`) before benchmarking to ensure memory clocks are active (1258 MHz) and not throttled to idle (96 MHz).

## 2. Tier 1: Parity & Greedy Exactness Gate

The Parity Gate (`scripts/parity_check.py --suite full`) validates numerical integrity:
- **Greedy Token Exactness**: `--token-tolerance 0` requires bit-exact greedy token parity against the certified golden baseline across coding, reasoning, and mathematics prompts.
- **Speed Floors**:
  - Code TPS: $\ge 230.0\,\text{tok/s}$
  - Reasoning TPS: $\ge 240.0\,\text{tok/s}$
  - Math TPS: $\ge 210.0\,\text{tok/s}$

## 3. Tier 2: Composite Score Gate

The Composite Score Gate (`scripts/check_composite_gate.py`) evaluates multi-metric performance against Opt 146:
- **Composite Score Formula**:
  $$\text{Composite} = 0.40 \cdot \text{Decode}_{\text{median}} + 0.35 \cdot \text{Concurrency}_{C8} + 0.25 \cdot \left(\frac{\text{Prefill}_{64k}}{10}\right)$$
- **Strict Guardrails**: No individual workload (single-stream decode, C8 concurrency, or 64k prefill) may regress below baseline thresholds, and latency P99 limits are strictly enforced.

## 4. Tier 3: RDNA4 ISA & Hardware Compliance Gate

The ISA Gate (`scripts/verify_rdna4_invariants.sh`) validates compiled binary machine code:
- Analyzes kernel disassembly across all 1,600+ compiled objects.
- Flags VGPR cliff danger windows ($VGPR \in [94, 96]$, $[118, 120]$) and scratch memory spills.
- Uses TypeSafe AI (Jev System One) for sub-100ms architectural hazard arbitration when warnings arise.
