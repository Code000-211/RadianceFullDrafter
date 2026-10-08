"""Tests for scripts/goal.py, the 1% lows in scripts/bench_metrics.py and the goal gate in orca_agent.

Run: python3 -m unittest scripts/tests/goal_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
import bench_metrics  # noqa: E402
import goal  # noqa: E402
import orca_agent  # noqa: E402


def bench(itl_ms: list[float], decode: float = 100.0, prefill: float = 8000.0, conc: float = 500.0) -> dict:
    return bench_metrics.calculate_metrics({
        "config": {}, "single_stream": {"code": [{"ok": True, "decode_tps": decode, "itl_ms": itl_ms, "ttft_ms": 50.0}]},
        "prefill": [{"pp_tps": [prefill], "target_depth": 64000}],
        "concurrency": [{"level": 8, "aggregate_tps": conc, "itl_ms": [12.0] * 100}]})


class TestOnePercentLows(unittest.TestCase):
    def test_slow_tail_lowers_the_score(self) -> None:
        smooth, tail = bench([10.0] * 1000), bench([10.0] * 990 + [30.0] * 10)
        self.assertEqual(smooth["tail_ratio"], 1.0)
        self.assertAlmostEqual(tail["itl_low1_ms"], 30.0)
        self.assertAlmostEqual(tail["tail_ratio"], 1 / 3, places=3)
        self.assertLess(tail["total_score"], smooth["total_score"])
        self.assertEqual(set(tail["subscores"]), {"decode", "prefill", "concurrency", "tail"})


class TestGoal(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.targets = self.dir / "targets.json"
        self.status = self.dir / "goal_status.json"

    def set_target(self, **t) -> None:
        self.targets.write_text(json.dumps(t))

    def rec(self, sha: str, m: dict) -> dict:
        return goal.record(sha, m, f"reports/p_{sha}", self.status, self.targets)

    def test_no_target_is_no_goal(self) -> None:
        self.set_target(total_score=None, at_least={"decode_med_tps": None})
        st = self.rec("a", bench([10.0] * 100))
        self.assertFalse(st["target_set"])
        self.assertFalse(st["reached"])

    def test_reached_only_twice_in_a_row(self) -> None:
        m = bench([10.0] * 100)
        self.set_target(total_score=m["total_score"] - 1)
        st = self.rec("a", m)
        self.assertTrue(st["needs_confirmation"])
        self.assertFalse(st["reached"])
        st = self.rec("a", m)
        self.assertTrue(st["reached"])
        self.assertFalse(st["needs_confirmation"])
        st = self.rec("b", bench([10.0] * 100, decode=10.0))  # regression on a later main
        self.assertFalse(st["reached"])

    def test_raising_the_target_resumes(self) -> None:
        m = bench([10.0] * 100)
        self.set_target(total_score=m["total_score"] - 1)
        self.rec("a", m)
        self.rec("a", m)
        self.assertTrue(goal.current(self.status, self.targets)["reached"])
        self.set_target(total_score=m["total_score"] + 100)
        self.assertFalse(goal.current(self.status, self.targets)["reached"])

    def test_floors_ceilings_and_room(self) -> None:
        self.set_target(at_least={"decode_med_tps": 150}, at_most={"c8_itl_p99_ms": 15})
        st = self.rec("a", bench([10.0] * 100, decode=100.0))
        checks = {c["metric"]: c["met"] for c in st["latest"]["evaluation"]["checks"]}
        self.assertEqual(checks, {"decode_med_tps": False, "c8_itl_p99_ms": True})
        room = st["latest"]["evaluation"]["room"]
        self.assertEqual(room[0]["part"], "decode")  # 333/1000 at weight 0.35 leaves the most points
        md = goal.render(st)
        self.assertIn("**Ziel: nicht erreicht.**", md)
        self.assertIn("| `decode_med_tps` | >= 150 | 100.0 | nein |", md)


class TestGoalGatesNewIdeas(unittest.TestCase):
    def test_research_stops_when_reached_and_runs_often_while_open(self) -> None:
        cfg = orca_agent.load_config()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(orca_agent, "STATE", Path(d)), \
                mock.patch.object(orca_agent, "open_issues", return_value=[]), \
                mock.patch.object(orca_agent, "backend_problem", return_value=None):
            stamp = Path(d) / "last-research"
            stamp.touch()  # ran just now
            with mock.patch.object(orca_agent, "goal_now", return_value={"target_set": True, "reached": True}):
                self.assertIsNone(orca_agent.find_work(cfg, "research", verbose=False))
            with mock.patch.object(orca_agent, "goal_now", return_value={"target_set": True, "reached": False}):
                self.assertIsNone(orca_agent.find_work(cfg, "research", verbose=False))  # 2 h spacing
                old = stamp.stat().st_mtime - 3 * 3600
                import os
                os.utime(stamp, (old, old))
                self.assertIsNotNone(orca_agent.find_work(cfg, "research", verbose=False))
            with mock.patch.object(orca_agent, "goal_now", return_value={"target_set": False, "reached": False}):
                self.assertIsNone(orca_agent.find_work(cfg, "research", verbose=False))  # 24 h without a target


if __name__ == "__main__":
    unittest.main()
