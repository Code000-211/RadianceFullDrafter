#!/usr/bin/env python3
"""
locate_code.py — Sub-150ms Fast Repository Router using Jev System One & OpenWiki

Combines TypeSafe AI (Jev System One) sub-100ms structured classification with OpenWiki's
verified Claims and architectural documentation to immediately tell any model or developer:
  1. Which subsystem owns the topic.
  2. Which OpenWiki documentation page explains the architecture.
  3. The exact physical source files and line ranges (repo://...#L...).
  4. The verified architectural ground truth claims.

Usage:
  python3 scripts/locate_code.py "How does P2P All-Reduce store drain work on dual R9700?"
  python3 scripts/locate_code.py --json "LDS bank conflict swizzling in W4A8 GEMM"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Import Jev triage engine
try:
    import typesafe_triage
except ImportError:
    script_dir = Path(__file__).resolve().parent
    sys.path.append(str(script_dir))
    import typesafe_triage

BASE_DIR = Path(__file__).resolve().parent.parent
OPENWIKI_DIR = BASE_DIR / "openwiki"
CLAIMS_DIR = OPENWIKI_DIR / ".claims"


def load_claims_for_page(page_rel_path: str) -> list[dict[str, Any]]:
    """Loads verified claims from openwiki/.claims/<page_stem>.json."""
    stem = page_rel_path
    if stem.startswith("/openwiki/"):
        stem = stem[len("/openwiki/") :]
    elif stem.startswith("openwiki/"):
        stem = stem[len("openwiki/") :]

    stem = stem.removesuffix(".md")

    claims_file = CLAIMS_DIR / f"{stem}.json"
    if not claims_file.is_file():
        return []

    try:
        data = json.loads(claims_file.read_text(encoding="utf-8"))
        return data.get("claims", [])
    except (json.JSONDecodeError, OSError):
        return []


def query_jev_router(query: str) -> dict[str, Any]:
    """Queries Jev System One to route the query to the exact OpenWiki page and source file."""
    questions = {
        "subsystem": {
            "type": "choice",
            "instructions": "Which engine subsystem contains the code for this query?",
            "criteria": {
                "p2p_interconnect": "Dual-GPU P2P All-Reduce, PCIe DMA, memory fence synchronization (libr4d/r4d_ar_*.hip)",
                "gemm_and_kernels": "W4A8 GEMM, Wave32 scheduling, LDS bank conflicts, VGPR occupancy (libr4d/r4d_gemm_*.hip)",
                "speculative_mtp": "MTP speculative decoding, draft head, FR-Spec vocab reduction (core/sched/, arch/common/)",
                "gdn_linear_attn": "Gated Delta Network, recurrent SSM update, conv window (arch/common/rad_block_gdn_*.h)",
                "moe_routing": "Mixture of Experts router, top-k scatter, expert GEMMs (libr4d/r4d_moe.hip)",
                "engine_runtime": "Engine step loop, CPU wait barriers, AQL queue dispatch (core/engine.cpp, core/device/)",
                "governance_gates": "Master quality gate, epistemic invariants, parity checks (scripts/)",
                "upstream_watcher": "Codeberg watcher, Jev usefulness triage, human review list (scripts/watch_upstream.py)",
            },
        },
        "relevant_wiki_page": {
            "type": "choice",
            "instructions": "Which OpenWiki documentation page covers this topic?",
            "criteria": {
                "openwiki/architecture/p2p_interconnect.md": "All-Reduce, WHT6 wire, P2P fences, and store drain protocol",
                "openwiki/architecture/gemm_and_kernels.md": "Matrix multiplication, Wave32, LDS layout, and VGPR limits",
                "openwiki/architecture/speculative_mtp.md": "Speculative drafting, draft head, and depth controllers",
                "openwiki/architecture/engine_runtime.md": "Engine step execution, AQL queues, and memory budgeting",
                "openwiki/governance/quality_gates.md": "Epistemic checks, Parity checks, and ISA verification",
                "openwiki/pipeline/upstream_watcher.md": "Upstream watcher, Jev usefulness triage, and review list",
                "openwiki/quickstart.md": "Prerequisites, build commands, worktree operations, and gate check",
            },
        },
        "primary_source_file": {
            "type": "choice",
            "instructions": "Which primary source file contains the core implementation?",
            "criteria": {
                "libr4d/r4d_ar_entry.hip": "P2P All-Reduce entry point, barrier synchronization, and rank communication",
                "libr4d/r4d_gemm_w4a8_prefill.hip": "Prefill W4A8 GEMM kernel with dual-issue VOPD and swizzling",
                "core/engine.cpp": "Main decode loop and host-device synchronization",
                "core/engine_draft.cpp": "Speculative draft issue and verification pipeline",
                "core/sched/scheduler.cpp": "Scheduler step advancing and speculative depth arbitration",
                "scripts/gate_check.sh": "4-Tier Master Quality Gate runner",
                "scripts/check_epistemic_invariants.py": "Tier 0 Epistemic ground truth checker",
                "scripts/watch_upstream.py": "Upstream Codeberg monitor writing candidates/upstream/REVIEW.md",
            },
        },
    }
    return typesafe_triage.query_jev(query, questions)


def locate(query: str) -> dict[str, Any]:
    """Resolves code locations and verified claims for a given query."""
    jev_routing = query_jev_router(query)

    subsystem = jev_routing.get("subsystem", {}).get("choice", "unknown")
    sub_conf = jev_routing.get("subsystem", {}).get("confidence", 0.0)

    wiki_page = jev_routing.get("relevant_wiki_page", {}).get("choice", "openwiki/quickstart.md")
    wiki_conf = jev_routing.get("relevant_wiki_page", {}).get("confidence", 0.0)

    source_file = jev_routing.get("primary_source_file", {}).get("choice", "")
    src_conf = jev_routing.get("primary_source_file", {}).get("confidence", 0.0)

    # Load verified claims
    claims = load_claims_for_page(wiki_page)

    # Extract all cited resources
    resources: list[str] = []
    for c in claims:
        for ev in c.get("evidence", []):
            res = ev.get("resource", "")
            if res and res not in resources:
                resources.append(res)

    # Read page summary
    page_file = BASE_DIR / wiki_page
    page_content = page_file.read_text(encoding="utf-8") if page_file.is_file() else ""

    return {
        "query": query,
        "subsystem": subsystem,
        "subsystem_confidence": sub_conf,
        "wiki_page": wiki_page,
        "wiki_page_confidence": wiki_conf,
        "primary_source_file": source_file,
        "primary_source_file_confidence": src_conf,
        "cited_resources": resources,
        "claims": claims,
        "page_preview": page_content[:1000] if page_content else "",
    }


def format_cli_output(result: dict[str, Any]) -> str:
    lines = [
        "================================================================================",
        " 🧭 Jev System One + OpenWiki Fast Code Locator",
        "================================================================================",
        f" • Query:                {result['query']}",
        f" • Subsystem:            {result['subsystem']} (Confidence: {result['subsystem_confidence'] * 100:.0f}%)",
        f" • Documentation Page:   {result['wiki_page']} (Confidence: {result['wiki_page_confidence'] * 100:.0f}%)",
        f" • Primary Source File:  {result['primary_source_file']} (Confidence: {result['primary_source_file_confidence'] * 100:.0f}%)",
        "================================================================================",
        "",
        "📍 Verified Code Spans & Claims:",
    ]

    for i, c in enumerate(result.get("claims", []), 1):
        statement = c.get("statement", "")
        ev_resources = [ev.get("resource", "") for ev in c.get("evidence", [])]
        res_str = ", ".join(ev_resources)
        lines.append(f"  [{i}] {res_str}")
        lines.append(f"      → \"{statement}\"")

    lines.extend([
        "",
        "💡 Ready-to-inject LLM Context:",
        "```markdown",
        f"Target Subsystem: {result['subsystem']}",
        f"Architecture Reference: {result['wiki_page']}",
        f"Primary Code Locations: {', '.join(result.get('cited_resources', [result['primary_source_file']]))}",
        "```",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sub-150ms Fast Code Locator using Jev System One & OpenWiki")
    parser.add_argument("query", help="Question, error message, or feature request")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    result = locate(args.query)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_cli_output(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
