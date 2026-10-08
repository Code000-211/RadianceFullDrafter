#!/usr/bin/env python3
"""lever_queue.py — local, sequential test queue for candidate levers (replaces the GitHub-issue runner).

    lever_queue.py add <slug> [--ref <branch>] [--abba]   queue candidates/<slug>/lever.patch
    lever_queue.py add <slug> --ref <branch> --mode merge test the branch itself (upstream sync)
    lever_queue.py list                                  show pending / done / failed jobs
    lever_queue.py run [--daemon] [--github] [--auto-profile]
                                                         process pending jobs one at a time
    lever_queue.py profile                               decode profile of origin/main now

--auto-profile: whenever the queue is idle and origin/main has no profile yet, the runner takes a
decode profile of the baseline (scripts/profile_decode.py) into reports/profile_<sha>_<ts>/ and
points reports/profile_latest at it. Planner and audit read it to judge fusions and other levers.

With --github the runner also pulls issues labelled status:ready-to-test and reports
results back to them (see gh_bridge.py). That is how Orca automations drive the queue.

Everything is based on origin/main (fetched before every job), because merges happen on
GitHub. The baseline is worktrees/_baseline, a detached checkout of origin/main rebuilt
before every job, so the A/B never compares against files someone is editing in the
primary checkout.

Per job, nothing else is reused:
  1. fresh worktree worktrees/<slug>_<ts> on a new branch lever/<slug>-<ts> from origin/main
  2. lever.patch (from origin/<ref>, default origin/main) applied and committed, so the gate
     runs on a fixed candidate SHA
  3. clean cmake + ninja build inside the worktree (no binaries copied from main)
  4. scripts/gate_check.sh against main's build_hip, with the lever's engine flags from
     candidates/<slug>/gate.json ({"engine_args": [...], "engine_env": {...}}) if present
  5. reports/<slug>_<ts>/RESULT.md + run.log; on PASS the candidate SHA is tagged
     winner/<slug>-<ts> and its build is copied to releases/<slug>-<ts>/ with a sha256 manifest

Mode "merge" (upstream syncs, docs/UPSTREAM.md) replaces steps 1-2: the candidate is
origin/<ref> itself, which must contain origin/main, so the merge commit and with it the upstream
history survive into the PR. gate.json is still read from candidates/<slug>/ on that branch.

Jobs run under a file lock, so two runners never share the GPUs. Every step's output goes
to run.log; a failing step ends the job as FAILED with the step named in RESULT.md.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import gh_bridge

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = REPO_ROOT / "queue"
REPORTS_DIR = REPO_ROOT / "reports"
RELEASES_DIR = REPO_ROOT / "releases"
LOCK_FILE = QUEUE_DIR / "runner.lock"
PROFILE_LATEST = REPORTS_DIR / "profile_latest"
PROFILE_TRIED = QUEUE_DIR / "profile_tried"  # baseline SHA of the last profile attempt, pass or fail
BASELINE_WT = REPO_ROOT / "worktrees" / "_baseline"
ROCM = os.environ.get("ROCM_PATH", "/opt/rocm")
# The systemd unit starts with a bare environment; cmake's HIP detection needs these.
BUILD_ENV = {
    **os.environ,
    "ROCM_PATH": ROCM,
    "HIP_PATH": os.environ.get("HIP_PATH", ROCM),
    "PATH": f"{ROCM}/bin:{ROCM}/llvm/bin:{os.environ.get('PATH', '/usr/bin:/bin')}",
}
CMAKE_ARGS = ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DRAD_WITH_HIP=ON", "-DRAD_GPU_TARGETS=gfx1201", "-DRAD_BUILD_TESTS=ON"]


class StepFailed(RuntimeError):
    def __init__(self, step: str, rc: int):
        super().__init__(f"step '{step}' failed with exit code {rc}")
        self.step = step
        self.rc = rc


def queue_path(state: str) -> Path:
    path = QUEUE_DIR / state
    path.mkdir(parents=True, exist_ok=True)
    return path


def enqueue(job: dict[str, Any]) -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    job = {"queued_at": ts, "ref": "main", "mode": "patch", "issue": None, "abba": False, **job}
    path = queue_path("pending") / f"{ts}_{job['slug']}.json"
    path.write_text(json.dumps(job, indent=2))
    return path


def cmd_add(args: argparse.Namespace) -> int:
    path = enqueue({"slug": args.slug, "ref": args.ref, "mode": args.mode, "abba": args.abba})
    print(f"queued {path.relative_to(REPO_ROOT)}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    for state in ("pending", "running", "done", "failed"):
        jobs = sorted(queue_path(state).glob("*.json"))
        print(f"{state} ({len(jobs)})")
        for j in jobs:
            data = json.loads(j.read_text())
            extra = f"  {data.get('verdict', '')}  {data.get('report', '')}" if state in ("done", "failed") else ""
            print(f"  {j.stem}{extra}")
    return 0


def run_step(step: str, cmd: list[str], log_f, cwd: Path) -> None:
    log_f.write(f"\n=== {time.strftime('%H:%M:%S')} {step}: {' '.join(cmd)}\n")
    log_f.flush()
    proc = subprocess.run(cmd, cwd=str(cwd), stdout=log_f, stderr=subprocess.STDOUT, env=BUILD_ENV, check=False)
    log_f.write(f"=== {step} exit {proc.returncode}\n")
    log_f.flush()
    if proc.returncode != 0:
        raise StepFailed(step, proc.returncode)


def git_out(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


def read_candidate_file(ref: str, slug: str, name: str) -> str | None:
    proc = subprocess.run(["git", "show", f"origin/{ref}:candidates/{slug}/{name}"], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def ensure_baseline(log_f) -> tuple[Path, str]:
    """Detached checkout of origin/main in worktrees/_baseline, built incrementally."""
    sha = git_out("rev-parse", "origin/main")
    if not BASELINE_WT.exists():
        run_step("baseline-worktree", ["git", "worktree", "add", "--detach", str(BASELINE_WT), sha], log_f, REPO_ROOT)
    else:
        if git_out("status", "--porcelain", "--untracked-files=no", cwd=BASELINE_WT):
            raise StepFailed("baseline-clean", 1)
        run_step("baseline-checkout", ["git", "checkout", "--detach", sha], log_f, BASELINE_WT)
    if not (BASELINE_WT / "build_hip" / "build.ninja").is_file():
        run_step("baseline-configure", ["cmake", "-B", "build_hip", "-S", ".", *CMAKE_ARGS], log_f, BASELINE_WT)
    run_step("baseline-build", ["ninja", "-C", "build_hip"], log_f, BASELINE_WT)
    return BASELINE_WT / "build_hip", sha


def archive_winner(tag: str, worktree: Path, candidate_sha: str, report_dir: Path) -> Path:
    dest = RELEASES_DIR / tag
    dest.mkdir(parents=True)
    build = worktree / "build_hip"
    shutil.copy2(build / "bin" / "radiance", dest / "radiance")
    shutil.copytree(build / "radiance_home", dest / "radiance_home", symlinks=True)
    files = {}
    for f in sorted(p for p in dest.rglob("*") if p.is_file()):
        files[str(f.relative_to(dest))] = hashlib.sha256(f.read_bytes()).hexdigest()
    manifest = {"tag": tag, "commit": candidate_sha, "gate_report": str(report_dir), "files": files}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return dest


def process(job_path: Path) -> dict[str, Any]:
    job = json.loads(job_path.read_text())
    slug = job["slug"]
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = f"{slug}_{ts}"
    report_dir = REPORTS_DIR / name
    report_dir.mkdir(parents=True)
    worktree = REPO_ROOT / "worktrees" / name
    branch = f"lever/{slug}-{ts}"
    ref = job.get("ref") or "main"
    mode = job.get("mode") or "patch"
    result: dict[str, Any] = {"slug": slug, "ref": ref, "mode": mode, "issue": job.get("issue"), "branch": branch,
                              "worktree": str(worktree), "report": str(report_dir)}
    gate_cfg: dict[str, Any] = {}

    with (report_dir / "run.log").open("w") as log_f:
        try:
            refspecs = ["+refs/heads/main:refs/remotes/origin/main"]
            if ref != "main":
                refspecs.append(f"+refs/heads/{ref}:refs/remotes/origin/{ref}")
            run_step("fetch", ["git", "fetch", "origin", *refspecs], log_f, REPO_ROOT)
            gate_json = read_candidate_file(ref, slug, "gate.json")
            gate_cfg = json.loads(gate_json) if gate_json else {}
            if mode == "merge":
                if ref == "main":
                    raise StepFailed("merge-needs-ref", 1)
                baseline_build, result["base_sha"] = ensure_baseline(log_f)
                ref_sha = git_out("rev-parse", f"origin/{ref}")
                # The A/B must compare main against main plus upstream, not against an older main.
                run_step("contains-main", ["git", "merge-base", "--is-ancestor", result["base_sha"], ref_sha], log_f, REPO_ROOT)
                run_step("worktree", ["git", "worktree", "add", "-b", branch, str(worktree), ref_sha], log_f, REPO_ROOT)
            else:
                patch = read_candidate_file(ref, slug, "lever.patch")
                if patch is None:
                    raise StepFailed("find-patch", 1)
                (report_dir / "lever.patch").write_text(patch)
                baseline_build, result["base_sha"] = ensure_baseline(log_f)
                run_step("worktree", ["git", "worktree", "add", "-b", branch, str(worktree), result["base_sha"]], log_f, REPO_ROOT)
                run_step("apply", ["git", "apply", "--index", str(report_dir / "lever.patch")], log_f, worktree)
                run_step("commit", ["git", "commit", "--no-verify", "-m", f"lever: apply {slug}"], log_f, worktree)
            result["candidate_sha"] = git_out("rev-parse", "HEAD", cwd=worktree)
            run_step("configure", ["cmake", "-B", "build_hip", "-S", ".", *CMAKE_ARGS], log_f, worktree)
            run_step("build", ["ninja", "-C", "build_hip"], log_f, worktree)
            gate_cmd = ["bash", str(REPO_ROOT / "scripts" / "gate_check.sh"), "--build-dir", str(worktree / "build_hip"),
                        "--candidate-root", str(worktree), "--baseline-build-dir", str(baseline_build),
                        "--out", str(report_dir / "gate")]
            if job.get("abba"):
                gate_cmd.append("--abba")
            for a in gate_cfg.get("engine_args", []):
                gate_cmd += ["--candidate-arg", a]
            for k, v in gate_cfg.get("engine_env", {}).items():
                gate_cmd += ["--candidate-env", f"{k}={v}"]
            run_step("gate", gate_cmd, log_f, REPO_ROOT)
            tag = f"winner/{slug}-{ts}"
            run_step("tag", ["git", "tag", tag, result["candidate_sha"]], log_f, REPO_ROOT)
            result["release"] = str(archive_winner(tag.replace("/", "_"), worktree, result["candidate_sha"], report_dir))
            result["verdict"] = "PASS"
        except StepFailed as e:
            result["verdict"] = f"FAILED at {e.step} (exit {e.rc})"
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            result["verdict"] = f"ERROR: {e}"

    ab_report = report_dir / "gate" / "ab" / "report.md"
    lines = [
        f"# {slug}: {result['verdict']}",
        "",
        f"- Base (origin/main): `{result.get('base_sha', '?')}`, "
        + (f"merge branch `origin/{ref}` itself" if mode == "merge" else f"patch from `origin/{ref}`"),
        f"- Candidate: `{result.get('candidate_sha', '?')}` on branch `{branch}`",
        f"- Worktree: `{worktree}`",
        f"- Engine flags: {gate_cfg or 'none'}",
        f"- Full log: `{report_dir / 'run.log'}`",
        "",
        ab_report.read_text() if ab_report.is_file() else "_No A/B report (the job stopped before or inside the gate)._",
    ]
    (report_dir / "RESULT.md").write_text("\n".join(lines) + "\n")
    return result


def report_pending_results() -> None:
    """Posts results to GitHub that are not reported yet (retried every loop)."""
    for state in ("done", "failed"):
        for path in sorted(queue_path(state).glob("*.json")):
            data = json.loads(path.read_text())
            if not data.get("issue") or data.get("reported"):
                continue
            try:
                gh_bridge.report(data, REPO_ROOT)
                data["reported"] = True
            except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
                data["report_error"] = str(e)
                print(f"⚠️  could not report {path.stem} to issue #{data['issue']}: {e}", flush=True)
            path.write_text(json.dumps(data, indent=2))


def profile_baseline() -> Path:
    """Decode profile of origin/main's baseline build; the caller holds the runner lock (GPUs)."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    staging = REPORTS_DIR / f"profile_pending_{ts}"
    staging.mkdir(parents=True)
    with (staging / "run.log").open("w") as log_f:
        run_step("fetch", ["git", "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"], log_f, REPO_ROOT)
        # Recorded before anything can fail, so a broken baseline is not rebuilt every idle minute.
        PROFILE_TRIED.write_text(git_out("rev-parse", "origin/main") + "\n")
        baseline_build, sha = ensure_baseline(log_f)
        out = REPORTS_DIR / f"profile_{sha[:10]}_{ts}"
        staging.rename(out)
        run_step("profile", [sys.executable, str(REPO_ROOT / "scripts" / "profile_decode.py"),
                             "--build-dir", str(baseline_build), "--out", str(out)], log_f, REPO_ROOT)
    link = REPORTS_DIR / f".profile_latest_{ts}"
    link.symlink_to(out.name)
    link.replace(PROFILE_LATEST)
    return out


def profile_due() -> bool:
    proc = subprocess.run(["git", "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main"],
                          cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"⚠️  fetch for the profile check failed: {proc.stderr.strip()}", flush=True)
        return False
    tried = PROFILE_TRIED.read_text().strip() if PROFILE_TRIED.is_file() else ""
    return tried != git_out("rev-parse", "origin/main")


def run_profile_logged() -> None:
    print(f"[{time.strftime('%H:%M:%S')}] profiling origin/main", flush=True)
    try:
        out = profile_baseline()
        print(f"[{time.strftime('%H:%M:%S')}] profile -> {out}/PROFILE.md", flush=True)
    except (StepFailed, OSError, subprocess.CalledProcessError) as e:
        # Not retried for the same baseline (PROFILE_TRIED); the next main gets a new attempt.
        print(f"⚠️  profile failed: {e} (see reports/profile_*/run.log)", flush=True)


def take_lock():
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_FILE.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another queue runner is active", file=sys.stderr)
        return None
    return lock


def cmd_profile(_: argparse.Namespace) -> int:
    lock = take_lock()
    if lock is None:
        return 1
    try:
        out = profile_baseline()
    except (StepFailed, OSError, subprocess.CalledProcessError) as e:
        print(f"profile failed: {e}", file=sys.stderr)
        return 2
    print(f"{out}/PROFILE.md")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    lock = take_lock()
    if lock is None:
        return 1
    if args.github:
        gh_bridge.ensure_labels()
    while True:
        if args.github:
            try:
                for job in gh_bridge.pull_ready():
                    print(f"[{time.strftime('%H:%M:%S')}] issue #{job['issue']} -> queued {enqueue(job).stem}", flush=True)
            except RuntimeError as e:
                print(f"⚠️  GitHub pull failed: {e}", flush=True)
            report_pending_results()
        pending = sorted(queue_path("pending").glob("*.json"))
        if not pending and args.auto_profile and profile_due():
            run_profile_logged()
            continue
        if not pending:
            if not args.daemon:
                return 0
            time.sleep(60)
            continue
        job_path = pending[0]
        running = queue_path("running") / job_path.name
        job_path.rename(running)
        print(f"[{time.strftime('%H:%M:%S')}] running {running.stem}", flush=True)
        result = process(running)
        data = {**json.loads(running.read_text()), **result}
        target = queue_path("done" if result["verdict"] == "PASS" else "failed") / running.name
        target.write_text(json.dumps(data, indent=2))
        running.unlink()
        print(f"[{time.strftime('%H:%M:%S')}] {running.stem}: {result['verdict']} -> {result['report']}/RESULT.md", flush=True)
        if args.github:
            report_pending_results()


def main() -> int:
    parser = argparse.ArgumentParser(description="Local sequential test queue for candidate levers")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add")
    p_add.add_argument("slug")
    p_add.add_argument("--ref", default="main", help="branch on origin holding candidates/<slug>/ (default: main)")
    p_add.add_argument("--abba", action="store_true", help="A,B,B,A gate instead of A,B")
    p_add.add_argument("--mode", choices=["patch", "merge"], default="patch",
                       help="merge: test origin/<ref> itself (upstream sync, must contain origin/main)")
    sub.add_parser("list")
    p_run = sub.add_parser("run")
    p_run.add_argument("--daemon", action="store_true", help="keep polling for new jobs")
    p_run.add_argument("--github", action="store_true", help="pull status:ready-to-test issues and report results to them")
    p_run.add_argument("--auto-profile", action="store_true", help="profile each new origin/main while idle")
    sub.add_parser("profile")
    args = parser.parse_args()
    return {"add": cmd_add, "list": cmd_list, "run": cmd_run, "profile": cmd_profile}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
