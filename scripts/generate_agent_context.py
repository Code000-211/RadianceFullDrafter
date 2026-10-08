#!/usr/bin/env python3
"""
generate_agent_context.py — Minimal Scoped Context Generator for RadianceMine

Generates strictly scoped, hallucination-proof prompts for agents:
- Strips all conversation bloat, unverified historical hearsay, and dead code notes.
- Injects ONLY:
  1. The exact objective / hypothesis.
  2. The strict RDNA4 (gfx1201) hardware truth card (<10 lines).
  3. The specific baseline metric to beat (Opt 146).
  4. The exact output contract (candidates/ or worktree/).
"""

import argparse

HARDWARE_TRUTH_CARD = """
=== AMD RDNA4 (gfx1201) Hardware Ground Truth ===
- GPUs: Dual AMD Radeon AI PRO R9700 (64 Dual CUs, Wave32 native scheduling).
- LDS: 64 KiB per CU across 32 banks (4 bytes/bank, XOR swizzling required to avoid bank conflicts).
- VGPR Occupancy: <= 84-96 VGPRs/thread for 4 waves/SIMD max occupancy. (Never exceed 128 VGPRs).
- Memory: 32 GB GDDR6 (256-bit bus, 576 GB/s) per card.
- Dual-GPU Interconnect: PCIe 4.0 x16 slot-to-slot interconnect (DMA: 28.29 GB/s, P2P: 16.95 GB/s bidirectional).
  * CRITICAL: Strictly PCIe 4.0! Never assume PCIe 5.0 (63 GB/s).
- Memory Fences: Avoid per-thread __threadfence_system(); use workgroup-leader drains or store_sys_rel.
"""

BASELINE_OPT146 = """
=== Golden Baseline Target (Opt 146 / Commit 1a4455d) ===
- Single-Stream Decode: 210.3 - 262.7 tok/s (Code >= 230, Reasoning >= 240, Math >= 210)
- Concurrency C8: 448.2 tok/s (P99 <= 15 ms)
- Cold 64k Prefill: 9,331.8 tok/s (TTFT <= 100 ms)
- Master Gate: Parity tolerance strictly 0 (greedy exactness).
"""

OPENWIKI_GROUNDING_MANDATE = """
=== Mandatory Ground-Truth First & Two-Tier Code Intelligence ===
- You are STRICTLY PROHIBITED from blind directory searches, random multi-file greps, or dumping full source files into context memory.
- Tier 1 (Macro Architecture & Subsystems): Ground in OpenWiki first:
    python3 scripts/locate_code.py "<task_or_query>"
  or query OpenWiki via `openwiki_search` / `openwiki_read`. Citing verified claims (repo://path#L...) is required.
- Tier 2 (Micro Relationships & Call Sites): Trace cross-file dependencies and call sites using LSP / pi-lens:
    * Find references & callers: `pilens_lsp_navigation` (operation: "references" / "incomingCalls") or `clangd`.
    * Semantic AST search: `pilens_ast_grep_search`.
    * Inspect symbols: `pilens_read_symbol` or bounded view (<= 200 lines). NEVER dump full multi-thousand-line source files.
"""

def generate_research_prompt(goal: str, suggestion: str = "", lever_slug: str = "") -> str:
    prompt = f"""# Mandate: Research & Optimization Blueprint

## Objective
{goal}
"""
    if suggestion:
        prompt += f"""
## User Suggestion / Hypothesis to Test
"{suggestion}"
*NOTE: Verify this hypothesis against official docs, alphaXiv, and GitHub. If it violates hardware reality, challenge it with data and propose the correct solution.*
"""
    prompt += HARDWARE_TRUTH_CARD
    prompt += BASELINE_OPT146
    prompt += OPENWIKI_GROUNDING_MANDATE
    prompt += f"""
## Strict Output Contract (Zero Trunk Modification)
1. Ground in OpenWiki first (`python3 scripts/locate_code.py "<query>"`).
2. Research papers on alphaXiv and kernels on GitHub (vLLM, SGLang, FlashAttention-3, DeepSeek, AsmEvo, CUTLASS).
3. Package your candidate lever strictly inside:
   `candidates/{lever_slug or 'lever<N>_<slug>'}/`
   - `README.md`: Equations, roofline analysis, RDNA4 Wave32 mapping, expected gain, OpenWiki references.
   - `lever.patch`: Clean git patch against baseline (Opt 146).
   - `src/`: (Optional) Standalone modified kernel/header files.
4. Submit a GitHub Issue labeled `research:new-lever`:
   `gh issue create --title "Candidate Lever: <Name>" --label "research:new-lever" --body "..."`
"""
    return prompt.strip()

def generate_implementation_prompt(lever_slug: str, worktree_path: str, issue_num: str = "") -> str:
    prompt = f"""# Mandate: Implementation & Hardware Gate Verification

## Candidate Lever to Test
`candidates/{lever_slug}/`

## Worktree Environment
Path: `{worktree_path}`
Base: `main` (Opt 146 golden baseline)

{HARDWARE_TRUTH_CARD}
{BASELINE_OPT146}
{OPENWIKI_GROUNDING_MANDATE}

## Execution Steps
0. Ground in OpenWiki: `python3 scripts/locate_code.py "Implementing {lever_slug}"`.
1. Navigate to worktree `{worktree_path}`.
2. Apply patch: `git apply ../../candidates/{lever_slug}/lever.patch`.
3. Compile: `ninja -C build_hip arch_test`.
4. Execute Master Gate on Dual R9700 GPUs:
   `scripts/gate_check.sh --build-dir build_hip`
5. Report Outcome:
   - If Pass: Auto-creates Pull Request against `main`.
   - If Regression: Captured into `REGRESSION_REPORT.md` and routed to GitHub Issue #{issue_num or '<num>'}.
"""
    return prompt.strip()

def main():
    parser = argparse.ArgumentParser(description="Generate minimal scoped context for agents.")
    parser.add_argument("--role", choices=["research", "implementation"], required=True)
    parser.add_argument("--goal", default="Optimize performance lever")
    parser.add_argument("--suggestion", default="")
    parser.add_argument("--lever", default="")
    parser.add_argument("--worktree", default="")
    parser.add_argument("--issue", default="")
    parser.add_argument("--out", default="")

    args = parser.parse_args()

    if args.role == "research":
        content = generate_research_prompt(args.goal, args.suggestion, args.lever)
    else:
        content = generate_implementation_prompt(args.lever, args.worktree, args.issue)

    if args.out:
        with open(args.out, "w") as f:
            f.write(content)
        print(f"Context written to {args.out}")
    else:
        print(content)

if __name__ == "__main__":
    main()
