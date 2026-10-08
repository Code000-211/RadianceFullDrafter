#!/usr/bin/env python3
"""lever_review.py — checks for candidate levers before they are sent to the GPU gate.

    lever_review.py claims <slug> [--ref <branch>]   does the README's evidence hold up?
    lever_review.py similar "<idea>"                 was this idea already tried or documented?

claims
  Deterministic:  the patch applies to origin/main; every pre-image blob named in its
                  `index <a>..<b>` lines exists in git (a made-up hash means the patch was
                  not produced by git diff); gate.json, if present, is valid JSON.
  Jev (one call): for each README line that states a number, a measurement or a verification,
                  the probability that the patch and the files in the candidate directory
                  support it; plus whether the README assumes PCIe 5.0 and whether the patch
                  implements what the README's summary describes.
  Exit 1 when a deterministic check fails or a measurement claim has support < 0.3.

similar
  Candidate sections are the markdown sections of the lever catalog, the postmortems and every
  candidates/*/README.md, prefiltered by word overlap with the idea; Jev rates each section in
  one call. Prints the best matches with file:line.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import typesafe_triage

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAIM_RE = re.compile(r"(\d[\d.,]*\s*(%|tok/s|t/s|GB/s|µs|us|ms|MiB|GiB|x\b|×))|verified|parity|measured|bit-exact|gen ?5|pcie ?5", re.I)
HISTORY_DOCS = [
    "docs/history/EXHAUSTIVE_OPTIMIZATION_LEVERS_ARM1_TO_OPT191_CATALOG.md",
    "docs/history/FULL_OPT1_TO_OPT190_POSTMORTEM_AND_ROOT_CAUSE_ANALYSIS.md",
    "docs/history/ced_projection_and_prefetch_optimization_audit.md",
]


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=check)


def read_candidate(slug: str, ref: str, name: str) -> str | None:
    if ref == "worktree":
        path = Path.cwd() / "candidates" / slug / name
        return path.read_text(encoding="utf-8") if path.is_file() else None
    proc = git("show", f"origin/{ref}:candidates/{slug}/{name}")
    return proc.stdout if proc.returncode == 0 else None


def list_candidate_files(slug: str, ref: str) -> list[str]:
    if ref == "worktree":
        base = Path.cwd() / "candidates" / slug
        return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
    proc = git("ls-tree", "-r", "--name-only", f"origin/{ref}", f"candidates/{slug}/")
    return [line.split(f"candidates/{slug}/", 1)[1] for line in proc.stdout.splitlines()]


def cmd_claims(args: argparse.Namespace) -> int:
    if args.ref != "worktree":
        git("fetch", "origin", "+refs/heads/main:refs/remotes/origin/main", f"+refs/heads/{args.ref}:refs/remotes/origin/{args.ref}")
    readme = read_candidate(args.slug, args.ref, "README.md")
    patch = read_candidate(args.slug, args.ref, "lever.patch")
    if readme is None or patch is None:
        print(f"❌ candidates/{args.slug}/README.md and lever.patch must both exist on {args.ref}")
        return 1
    failed = False

    # Deterministic checks: apply against origin/main through a throwaway index
    git("fetch", "origin", "+refs/heads/main:refs/remotes/origin/main")
    tmp_patch = REPO_ROOT / "telemetry" / f"lever_review_{args.slug}.patch"
    tmp_index = REPO_ROOT / "telemetry" / f"lever_review_{args.slug}.index"
    tmp_patch.write_text(patch, encoding="utf-8")
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_index)}
    subprocess.run(["git", "read-tree", "origin/main"], cwd=str(REPO_ROOT), env=env, check=True)
    applies = subprocess.run(["git", "apply", "--cached", "--check", str(tmp_patch)], cwd=str(REPO_ROOT),
                             env=env, capture_output=True, text=True)
    tmp_patch.unlink()
    tmp_index.unlink(missing_ok=True)
    print(f"{'✓' if applies.returncode == 0 else '❌'} patch applies to origin/main"
          + ("" if applies.returncode == 0 else f": {applies.stderr.strip()[:300]}"))
    failed |= applies.returncode != 0
    for m in re.finditer(r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})", patch, re.M):
        pre = m.group(1)
        if set(pre) == {"0"}:
            continue
        exists = git("cat-file", "-e", f"{pre}^{{blob}}").returncode == 0
        if not exists:
            print(f"❌ pre-image blob {pre} does not exist in git: the patch was not produced by git diff")
            failed = True
    gate_json = read_candidate(args.slug, args.ref, "gate.json")
    if gate_json is not None:
        try:
            cfg = json.loads(gate_json)
            print(f"✓ gate.json: engine_args={cfg.get('engine_args', [])} engine_env={cfg.get('engine_env', {})}")
        except json.JSONDecodeError as e:
            print(f"❌ gate.json is not valid JSON: {e}")
            failed = True

    # Jev: claim support
    claims = [line.strip() for line in readme.splitlines() if CLAIM_RE.search(line) and len(line.strip()) > 15][:40]
    state = json.dumps({
        "setup": "2x AMD Radeon AI PRO R9700 (RDNA4 gfx1201), PCIe 4.0 (measured ~27 GB/s per direction), TP2",
        "candidate_files": list_candidate_files(args.slug, args.ref),
        "readme": readme[:12000],
        "patch": patch[:20000],
        "claims": claims,
    })
    questions = {
        f"claim_{i}": {
            "type": "noul",
            "instructions": (
                f"Is the claim `claims[{i}]` supported by evidence present in `patch` or in "
                "`candidate_files` (e.g. a results file), rather than only asserted in the README? "
                "Code that could plausibly produce an effect is not evidence that a measured number was achieved."
            ),
        }
        for i in range(len(claims))
    }
    questions["assumes_pcie5"] = {"type": "noul", "instructions": "Does `readme` base any calculation on PCIe 5.0 bandwidth?"}
    questions["patch_matches_summary"] = {
        "type": "noul",
        "instructions": "Does `patch` implement the change that the summary at the top of `readme` describes?",
    }
    answers = typesafe_triage.query_jev(state, questions)

    print("\nClaim support (Jev):")
    for i, claim in enumerate(claims):
        p = float(answers[f"claim_{i}"]["noul"])
        measured = bool(re.search(r"tok/s|t/s|GB/s|%|µs|ms|verified|parity|measured|bit-exact", claim, re.I))
        mark = "❌" if measured and p < 0.3 else ("⚠️ " if p < 0.5 else "✓")
        failed |= measured and p < 0.3
        print(f"  {mark} {p:.2f}  {claim[:150]}")
    pcie5 = float(answers["assumes_pcie5"]["noul"])
    match = float(answers["patch_matches_summary"]["noul"])
    print(f"\n{'❌' if pcie5 >= 0.5 else '✓'} assumes PCIe 5.0: {pcie5:.2f}")
    print(f"{'❌' if match < 0.5 else '✓'} patch matches README summary: {match:.2f}")
    failed |= pcie5 >= 0.5 or match < 0.5
    print("\nRESULT:", "FAIL — fix the README or the patch before sending this lever to the gate" if failed else "OK")
    return 1 if failed else 0


def sections_of(path: Path) -> list[tuple[str, int, str]]:
    out, start, buf = [], 1, []
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if line.startswith("#") and buf:
            out.append((str(path.relative_to(REPO_ROOT)), start, "\n".join(buf)))
            start, buf = n, []
        buf.append(line)
    if buf:
        out.append((str(path.relative_to(REPO_ROOT)), start, "\n".join(buf)))
    return out


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]{4,}", text.lower())}


def cmd_similar(args: argparse.Namespace) -> int:
    docs = [REPO_ROOT / d for d in HISTORY_DOCS if (REPO_ROOT / d).is_file()]
    docs += sorted((REPO_ROOT / "candidates").glob("*/README.md"))
    sections = [s for d in docs for s in sections_of(d)]
    q = words(args.idea)
    ranked = sorted(sections, key=lambda s: -len(q & words(s[2])))[:30]
    state = json.dumps({"idea": args.idea, "sections": [s[2][:1500] for s in ranked]})
    questions = {
        f"s{i}": {
            "type": "noul",
            "instructions": f"Does `sections[{i}]` describe the same optimization idea as `idea`, or a very close variant of it (already tried, measured or rejected)?",
        }
        for i in range(len(ranked))
    }
    answers = typesafe_triage.query_jev(state, questions)
    scored = sorted(((float(answers[f"s{i}"]["noul"]), ranked[i]) for i in range(len(ranked))), key=lambda x: -x[0])
    print(f"Closest documented ideas for: {args.idea}\n")
    for p, (path, line, text) in scored[: args.top]:
        title = text.splitlines()[0][:100]
        print(f"  {p:.2f}  {path}:{line}  {title}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-gate checks for candidate levers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("claims")
    pc.add_argument("slug")
    pc.add_argument("--ref", default="worktree", help="'worktree' (current directory, default) or a branch on origin")
    ps = sub.add_parser("similar")
    ps.add_argument("idea")
    ps.add_argument("--top", type=int, default=8)
    args = parser.parse_args()
    try:
        return cmd_claims(args) if args.cmd == "claims" else cmd_similar(args)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
