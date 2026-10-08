#!/usr/bin/env python3
"""
watch_upstream.py — Automated Upstream Codeberg Monitor & Triage Pipeline

Monitors the upstream Radiance repository (https://codeberg.org/StillDeadcode/radiance):
  1. Polls Codeberg REST API & RSS feed for new Pull Requests and Commits.
  2. Evaluates relevance using TypeSafe AI (Jev System One) in <100ms.
  3. Downloads .patch files and runs deterministic safety checks (eval_patch_safety.py).
  4. Automatically queues candidate optimizations into candidates/upstream/ with full audit logs.
  5. Tracks seen state in telemetry/upstream_seen.json to eliminate redundant processing.

Zero-Token Rule:
  Trivial docs, markdown-only, or CI-only changes are classified deterministically without burning Jev tokens.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Optional import of typesafe_triage
try:
    import typesafe_triage
except ImportError:
    script_dir = Path(__file__).resolve().parent
    sys.path.append(str(script_dir))
    import typesafe_triage

BASE_DIR = Path(__file__).resolve().parent.parent
TELEMETRY_DIR = BASE_DIR / "telemetry"
UPSTREAM_CANDIDATES_DIR = BASE_DIR / "candidates" / "upstream"
SEEN_FILE = TELEMETRY_DIR / "upstream_seen.json"
QUEUE_FILE = UPSTREAM_CANDIDATES_DIR / "QUEUE.md"

CODEBERG_BASE = "https://codeberg.org"
REPO_OWNER = "StillDeadcode"
REPO_NAME = "radiance"
API_BASE = f"{CODEBERG_BASE}/api/v1/repos/{REPO_OWNER}/{REPO_NAME}"
RSS_URL = f"{CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME}.rss"
USER_AGENT = "RadianceMine-Watcher/1.0"


def http_get_json(url: str, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"HTTP GET failed for {url}: {e}") from e


def http_get_text(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"HTTP GET failed for {url}: {e}") from e


def load_seen_state() -> dict[str, Any]:
    if SEEN_FILE.is_file():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"prs": {}, "commits": {}, "last_checked": 0}
    return {"prs": {}, "commits": {}, "last_checked": 0}


def save_seen_state(state: dict[str, Any]) -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", s)[:40]


def is_docs_or_ci_only(patch_content: str) -> bool:
    """Deterministic check: does this patch only touch docs, markdown, or CI files?"""
    files = re.findall(r"diff --git a/(.*?) b/", patch_content)
    if not files:
        return False
    docs_extensions = {".md", ".txt", ".rst", ".png", ".jpg", ".svg"}
    docs_dirs = ("docs/", "doc/", ".github/", ".forgejo/", "licenses/")

    for f in files:
        path = Path(f)
        is_doc = path.suffix.lower() in docs_extensions or any(
            f.startswith(d) for d in docs_dirs
        )
        if not is_doc:
            return False
    return True


def evaluate_with_jev(title: str, author: str, body: str) -> dict[str, Any]:
    """Queries Jev System One for structured triage."""
    payload = f"Title: {title}\nAuthor: {author}\n\nDescription:\n{body[:1500]}"
    questions = {
        "subsystem": {
            "type": "choice",
            "instructions": "Which engine subsystem does this optimization proposal affect?",
            "criteria": {
                "gemm": "Matrix multiplication, W4A8 GEMM, and linear projection kernels",
                "gdn": "Gated Delta Network, recurrent SSM, linear attention",
                "qsa": "Qwen Sparse Attention, micro-block scoring, paged KV cache",
                "moe": "Mixture of Experts router, top-k scatter, expert GEMMs",
                "interconnect": "Dual-GPU P2P All-Reduce, PCIe DMA, memory fence synchronization",
                "drafter": "Speculative decoding, MTP drafter, acceptance controller",
                "serving": "OpenAI-compatible HTTP server, endpoints (/v1/models, /props, hfget)",
                "tooling": "Benchmarking, clock monitoring, hardware inspection scripts",
                "general": "General engine core, memory management, config, or documentation",
            },
        },
        "violates_rdna4_limits": {
            "type": "noul",
            "instructions": "Does this proposal contradict AMD RDNA4 gfx1201 hardware constraints (e.g. CUDA PTX, Wave64, >64KB LDS)?",
        },
        "feasibility": {
            "type": "score",
            "instructions": "Feasibility and architectural viability on dual AMD Radeon AI PRO R9700",
            "criteria": [
                "Unfeasible / contradicts hardware laws / CUDA-only",
                "High risk or complex external dependency",
                "Moderate feasibility / experimental",
                "Feasible / standard ROCm HIP implementation",
                "Immediate high-value quick win",
            ],
        },
        "performance_roi": {
            "type": "score",
            "instructions": "Expected performance ROI on AMD dual R9700",
            "criteria": [
                "Zero or negative performance impact (docs, tool, placebo)",
                "Marginal gain (<2%) or monitoring/stability utility",
                "Solid architectural gain (2-5%)",
                "High-impact gain (5-15%)",
                "Breakthrough gain (>15%)",
            ],
        },
    }
    return typesafe_triage.query_jev(payload, questions)


def run_deterministic_safety_audit(patch_path: Path) -> tuple[bool, list[str]]:
    """Runs scripts/eval_patch_safety.py on the downloaded patch."""
    checker = BASE_DIR / "scripts" / "eval_patch_safety.py"
    if not checker.is_file():
        return True, ["eval_patch_safety.py not found; skipped"]

    proc = subprocess.run(
        [sys.executable, str(checker), str(patch_path)],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        check=False,
    )

    violations = []
    if proc.returncode != 0:
        for line in proc.stdout.splitlines():
            if line.strip().startswith("•") or "violation" in line.lower() or "rejected" in line.lower():
                violations.append(line.strip())
        if not violations:
            violations = [proc.stdout.strip()]

    return proc.returncode == 0, violations


def package_candidate(
    pr_id: int,
    title: str,
    author: str,
    url: str,
    patch_content: str,
    jev_result: dict[str, Any] | None,
    safety_passed: bool,
    safety_violations: list[str],
    status: str,
) -> Path:
    """Packages candidate into candidates/upstream/pr_{id}_{slug}/."""
    UPSTREAM_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    folder_name = f"pr_{pr_id}_{slugify(title)}"
    candidate_dir = UPSTREAM_CANDIDATES_DIR / folder_name
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save patch
    patch_file = candidate_dir / "pr.patch"
    patch_file.write_text(patch_content, encoding="utf-8", errors="replace")

    # 2. Extract modified files from patch
    modified_files = re.findall(r"diff --git a/(.*?) b/", patch_content)

    # 3. Save METADATA.json
    meta = {
        "pr_id": pr_id,
        "title": title,
        "author": author,
        "url": url,
        "status": status,
        "modified_files": modified_files,
        "safety_audit": {
            "passed": safety_passed,
            "violations": safety_violations,
        },
        "jev_evaluation": jev_result or {},
    }
    (candidate_dir / "METADATA.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # 4. Generate README.md
    subsystem = (jev_result or {}).get("subsystem", {}).get("choice", "N/A")
    feasibility = (jev_result or {}).get("feasibility", {}).get("score", 0.0)
    violates_rdna4 = (jev_result or {}).get("violates_rdna4_limits", {}).get("noul", 0.0)
    roi = (jev_result or {}).get("performance_roi", {}).get("score", 0.0)

    readme_content = f"""# Upstream PR #{pr_id}: {title}

**Author**: @{author}  
**Upstream URL**: {url}  
**Status**: `{status}`  
**Candidate Directory**: `candidates/upstream/{folder_name}`  

---

## 1. TypeSafe AI (Jev System One) Evaluation
- **Target Subsystem**: `{subsystem}`
- **RDNA4 Hardware Violation Risk**: `{violates_rdna4:.2f}` (lower is safer)
- **Feasibility Score**: `{feasibility:.2f} / 4.00`
- **Expected Performance ROI**: `{roi:.2f} / 4.00`

---

## 2. Deterministic Safety Audit
- **Safety Gate Result**: `{"PASS" if safety_passed else "FAIL (REJECTED)"}`
{chr(10).join(f"- {v}" for v in safety_violations) if safety_violations else "- Zero dangerous anti-patterns detected."}

---

## 3. Modified Files ({len(modified_files)})
{chr(10).join(f"- `{f}`" for f in modified_files)}

---

## 4. Verification & Testing Instructions
To test this patch cleanly in an isolated worktree:
```bash
# 1. Create isolated worktree from golden baseline
bash scripts/create_worktree.sh test_upstream_pr_{pr_id}

# 2. Enter worktree and apply patch
cd worktrees/test_upstream_pr_{pr_id}
git apply ../../candidates/upstream/{folder_name}/pr.patch

# 3. Build HIP kernels
ninja -C build_hip

# 4. Run Epistemic and ISA Gate Checks
bash scripts/verify_ground_truth.sh
bash scripts/verify_rdna4_invariants.sh build_hip

# 5. Run Parity & Benchmark Gate (when authorized)
bash scripts/gate_check.sh
```
"""
    (candidate_dir / "README.md").write_text(readme_content, encoding="utf-8")
    return candidate_dir


def update_master_queue_doc(seen_state: dict[str, Any]) -> None:
    """Updates candidates/upstream/QUEUE.md with the live queue overview."""
    UPSTREAM_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    prs = seen_state.get("prs", {})

    lines = [
        "# Upstream Codeberg Evaluation Queue",
        "",
        f"**Repository**: [{REPO_OWNER}/{REPO_NAME}]({CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME})  ",
        f"**Last Checked**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seen_state.get('last_checked', time.time())))}  ",
        f"**Total Screened PRs**: {len(prs)}  ",
        "",
        "---",
        "",
        "| PR # | Title | Author | Subsystem | Feasibility | ROI | Safety | Status | Link |",
        "|------|-------|--------|-----------|-------------|-----|--------|--------|------|",
    ]

    # Sort PRs by PR number descending
    sorted_prs = sorted(prs.values(), key=lambda x: x.get("pr_id", 0), reverse=True)

    for item in sorted_prs:
        pr_id = item.get("pr_id")
        title = item.get("title", "")[:35]
        author = item.get("author", "")
        jev = item.get("jev", {})
        sub = jev.get("subsystem", {}).get("choice", "-")
        feas = f"{jev.get('feasibility', {}).get('score', 0.0):.1f}" if jev else "-"
        roi = f"{jev.get('performance_roi', {}).get('score', 0.0):.1f}" if jev else "-"
        safety = "✅ PASS" if item.get("safety", {}).get("passed", True) else "❌ FAIL"
        status = item.get("status", "QUEUED")
        url = item.get("url", f"{CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_id}")
        slug = slugify(item.get("title", ""))
        rel_dir = f"pr_{pr_id}_{slug}/README.md"

        link = f"[Inspect]({rel_dir})" if (UPSTREAM_CANDIDATES_DIR / f"pr_{pr_id}_{slug}").exists() else f"[PR #{pr_id}]({url})"

        lines.append(
            f"| #{pr_id} | {title} | @{author} | `{sub}` | {feas} | {roi} | {safety} | `{status}` | {link} |"
        )

    lines.extend([
        "",
        "---",
        "### Status Legend:",
        "- `READY_TO_TEST`: Passed Jev triage + deterministic patch safety; packaged in candidate folder.",
        "- `DOCS_OR_TOOLING`: Monitoring tool, benchmark utility, or documentation improvement.",
        "- `SERVING_ENDPOINT`: HTTP server endpoints or client compatibility.",
        "- `REJECTED_UNFEASIBLE`: High RDNA4 violation or unfeasible architecture (e.g. CUDA PTX).",
        "- `REJECTED_SAFETY_VIOLATION`: Detected dangerous anti-pattern (e.g. per-thread threadfence, test tampering).",
    ])

    QUEUE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_and_triage_pull_requests(
    use_typesafe: bool = True, force: bool = False
) -> list[dict[str, Any]]:
    """Polls open PRs, screens them, and updates queue."""
    seen = load_seen_state()
    prs_data = http_get_json(f"{API_BASE}/pulls?state=all")
    results = []

    print(f"🔍 Fetched {len(prs_data)} total PRs from {API_BASE}/pulls...")

    for pr in prs_data:
        pr_id = pr["number"]
        pr_key = str(pr_id)
        title = pr["title"]
        author = pr["user"]["username"]
        body = pr.get("body") or ""
        pr_url = f"{CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_id}"
        updated_at = pr.get("updated_at", "")

        # Check if already screened and not updated
        if (
            not force
            and pr_key in seen.get("prs", {})
            and seen["prs"][pr_key].get("updated_at") == updated_at
        ):
            continue

        print(f"\n⚡ Triage PR #{pr_id}: '{title}' (@{author})")

        # 1. Download patch
        patch_url = f"{CODEBERG_BASE}/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_id}.patch"
        try:
            patch_content = http_get_text(patch_url)
        except (urllib.error.URLError, OSError, RuntimeError) as e:
            print(f"⚠️ Failed to download patch for PR #{pr_id}: {e}")
            continue

        # 2. Check if docs-only (Deterministic 0-token rule)
        is_doc = is_docs_or_ci_only(patch_content)
        jev_result = None

        if is_doc:
            status = "DOCS_OR_CI"
            print("  📄 PR touches only docs / CI / text files (Deterministic 0-token rule).")
        elif use_typesafe:
            try:
                print("  🧠 Querying TypeSafe AI (Jev System One)...")
                jev_result = evaluate_with_jev(title, author, body)
                sub = jev_result.get("subsystem", {}).get("choice", "general")
                feas = jev_result.get("feasibility", {}).get("score", 0.0)
                viol = jev_result.get("violates_rdna4_limits", {}).get("noul", 0.0)
                roi = jev_result.get("performance_roi", {}).get("score", 0.0)
                print(f"  • Subsystem: {sub} | Feasibility: {feas:.2f} | RDNA4 Viol: {viol:.2f} | ROI: {roi:.2f}")

                if viol >= 0.50 or feas < 1.5:
                    status = "REJECTED_UNFEASIBLE"
                elif sub == "tooling":
                    status = "DOCS_OR_TOOLING"
                elif sub == "serving":
                    status = "SERVING_ENDPOINT"
                elif roi >= 1.5 or sub in ("gemm", "gdn", "qsa", "moe", "interconnect", "drafter"):
                    status = "READY_TO_TEST"
                else:
                    status = "QUEUED_LOW_PRIORITY"
            except (RuntimeError, ValueError) as e:
                print(f"  ⚠️ Jev query failed: {e}")
                status = "QUEUED_MANUAL_REVIEW"
        else:
            status = "QUEUED_NO_TYPESAFE"

        # 3. Temporary patch file for deterministic safety audit
        temp_patch = TELEMETRY_DIR / f"temp_pr_{pr_id}.patch"
        temp_patch.write_text(patch_content, encoding="utf-8")
        safety_passed, violations = run_deterministic_safety_audit(temp_patch)
        temp_patch.unlink(missing_ok=True)

        if not safety_passed:
            status = "REJECTED_SAFETY_VIOLATION"
            print(f"  ❌ Patch rejected by deterministic safety audit: {violations}")
        else:
            print("  🛡️ Patch safety audit: PASSED")

        # 4. Package candidate directory
        c_dir = package_candidate(
            pr_id=pr_id,
            title=title,
            author=author,
            url=pr_url,
            patch_content=patch_content,
            jev_result=jev_result,
            safety_passed=safety_passed,
            safety_violations=violations,
            status=status,
        )
        print(f"  📦 Packaged candidate into {c_dir.relative_to(BASE_DIR)}")

        # 5. Record state
        seen.setdefault("prs", {})[pr_key] = {
            "pr_id": pr_id,
            "title": title,
            "author": author,
            "url": pr_url,
            "updated_at": updated_at,
            "status": status,
            "jev": jev_result,
            "safety": {
                "passed": safety_passed,
                "violations": violations,
            },
        }
        results.append(seen["prs"][pr_key])

    seen["last_checked"] = int(time.time())
    save_seen_state(seen)
    update_master_queue_doc(seen)
    print(f"\n✅ Upstream PR triage complete. Master queue updated at {QUEUE_FILE.relative_to(BASE_DIR)}")
    return results


def check_recent_commits() -> None:
    """Checks recent commits on main for upstream version bumps or core kernel edits."""
    commits = http_get_json(f"{API_BASE}/commits?limit=5")
    print("\n🔍 Latest upstream commits on main:")
    for c in commits:
        sha = c["sha"][:8]
        date = c["commit"]["committer"]["date"][:10]
        msg = c["commit"]["message"].splitlines()[0]
        print(f"  • [{sha}] {date} — {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated Upstream Codeberg Watcher & Triage")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds (default: 300)")
    parser.add_argument("--force", action="store_true", help="Force re-evaluation of seen PRs")
    parser.add_argument("--no-typesafe", action="store_true", help="Disable Jev System One queries")
    parser.add_argument("--pr", type=int, help="Triage a specific PR number")

    args = parser.parse_args()

    use_typesafe = not args.no_typesafe

    if args.pr:
        print(f"Targeting single PR #{args.pr}...")
        check_and_triage_pull_requests(use_typesafe=use_typesafe, force=True)
        return 0

    if args.daemon:
        print(f"🚀 Starting watch_upstream daemon (polling every {args.interval}s)...")
        while True:
            try:
                check_and_triage_pull_requests(use_typesafe=use_typesafe, force=args.force)
                check_recent_commits()
            except (urllib.error.URLError, OSError, RuntimeError) as e:
                print(f"⚠️ Error during polling cycle: {e}")
            print(f"Sleeping {args.interval}s...")
            time.sleep(args.interval)
        return 0

    # Default: single run
    check_and_triage_pull_requests(use_typesafe=use_typesafe, force=args.force)
    check_recent_commits()
    return 0


if __name__ == "__main__":
    sys.exit(main())
