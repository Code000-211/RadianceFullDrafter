"""Tests for scripts/upstream_sync.py (analysis on throwaway repos) and the merge-mode metadata.

Run: python3 -m unittest scripts/tests/upstream_sync_test.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("upstream_sync", SCRIPTS_DIR / "upstream_sync.py")
us = importlib.util.module_from_spec(spec)
spec.loader.exec_module(us)
import gh_bridge  # noqa: E402


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text)


class TestAnalyse(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        r = self.repo = Path(self.tmp.name)
        sh(r, "init", "-q", "-b", "main")
        for rel in ("libr4d/moe.hip", "core/sched.cpp", "core/server.cpp", "arch/q.cpp"):
            write(r, rel, "base\n")
        sh(r, "add", ".")
        sh(r, "commit", "-qm", "radiance 1.0.13")
        sh(r, "branch", "up")
        # ours: kernel tuned, scheduler changed at the top, one upstream commit excluded earlier
        write(r, "libr4d/moe.hip", "ours\n")
        write(r, "core/sched.cpp", "ours-top\nbase\n")
        sh(r, "commit", "-qam", "opt: moe")
        sh(r, "commit", "-q", "--allow-empty", "-m", "Revert x\n\nUpstream-Excluded: abc1234 slower MoE at T<=16")
        # upstream: kernel rewritten (conflict), scheduler appended (overlap, no conflict), new TP3 file
        sh(r, "checkout", "-q", "up")
        write(r, "libr4d/moe.hip", "upstream\n")
        sh(r, "commit", "-qam", "libr4d: faster moe")
        write(r, "core/sched.cpp", "base\nupstream-bottom\n")
        write(r, "libr4d/ar_3rank.hip", "tp3\n")
        sh(r, "add", ".")
        sh(r, "commit", "-qm", "three ranks | all-reduce")
        sh(r, "checkout", "-q", "main")

    def test_conflicts_overlap_commits_and_exclusions(self) -> None:
        with mock.patch.object(us, "REPO_ROOT", self.repo):
            a = us.analyse("main", "up")
        self.assertEqual(a["conflicts"], ["libr4d/moe.hip"])
        self.assertEqual(a["overlap"], ["core/sched.cpp"])
        self.assertEqual([c[2] for c in a["commits"]], ["libr4d: faster moe", "three ranks | all-reduce"])
        self.assertEqual(a["excluded"], ["Upstream-Excluded: abc1234 slower MoE at T<=16"])
        body = us.issue_body(a)
        self.assertIn(f"upstream: {a['upstream_sha']}", body)
        self.assertIn("**Kernel (libr4d)** (1): `libr4d/moe.hip`", body)
        self.assertIn("**Engine-Kern** (1): `core/sched.cpp`", body)
        self.assertIn("three ranks / all-reduce", body)  # table-safe
        self.assertIn("slower MoE at T<=16", body)
        # analysis must not touch the work tree or HEAD
        self.assertEqual(sh(self.repo, "status", "--porcelain"), "")
        self.assertEqual(sh(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")


class TestMergeMeta(unittest.TestCase):
    def test_mode_is_parsed_and_newest_block_wins(self) -> None:
        self.assertEqual(gh_bridge.parse_meta(["candidate: upstream-sync\nref: agent/s\nmode: merge"]),
                         ("upstream-sync", "agent/s", "merge"))
        self.assertEqual(gh_bridge.parse_meta(["candidate: l1\nref: b"]), ("l1", "b", "patch"))
        self.assertEqual(gh_bridge.parse_meta(["candidate: a\nref: b\nmode: merge", "candidate: c\nref: d"]),
                         ("c", "d", "patch"))
        self.assertIsNone(gh_bridge.parse_meta(["nichts"]))


if __name__ == "__main__":
    unittest.main()
