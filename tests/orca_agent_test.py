"""Tests for scripts/orca_agent.py: selection, tiers, handoff, limits, slots, one simulated run.

Run: python3 -m unittest tests/orca_agent_test.py
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
spec = importlib.util.spec_from_file_location("orca_agent", SCRIPTS_DIR / "orca_agent.py")
oa = importlib.util.module_from_spec(spec)
sys.modules["orca_agent"] = oa
spec.loader.exec_module(oa)

GATE_FAIL = oa.RESULT_MARKER + "\n### Gate nicht bestanden: FAIL\n"
GATE_PASS = oa.RESULT_MARKER + "\n### Gate bestanden\n"


def issue(n: int, *labels: str) -> dict:
    return {"number": n, "title": f"Hebel {n}", "labels": set(labels)}


class StateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(oa, "STATE", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.cfg = oa.load_config()


class TestSelection(unittest.TestCase):
    def kind(self, role: str, *labels: str, gated: bool = True) -> str | None:
        return oa.kind_of(role, set(labels), lambda: gated)

    def test_plan_takes_new_ideas_and_revisions_only(self) -> None:
        self.assertEqual(self.kind("plan", "research:new-lever"), "new")
        self.assertEqual(self.kind("plan", "research:new-lever", "plan:ready", "plan:needs-revision"), "revise")
        self.assertIsNone(self.kind("plan", "research:new-lever", "plan:ready"))
        self.assertIsNone(self.kind("plan", "research:new-lever", "status:needs-review"))  # legacy issue
        self.assertIsNone(self.kind("plan", "research:new-lever", "plan:rejected"))

    def test_code_priorities_and_exclusions(self) -> None:
        self.assertEqual(self.kind("code", "plan:ready", "tier:light"), "implement")
        self.assertEqual(self.kind("code", "plan:ready", "changes-requested"), "changes")
        self.assertEqual(self.kind("code", "plan:ready", "status:needs-review"), "gate-fix")
        self.assertIsNone(self.kind("code", "plan:ready", "status:needs-review", gated=False))
        self.assertIsNone(self.kind("code", "plan:ready", "needs-code-review"))
        self.assertIsNone(self.kind("code", "plan:ready", "plan:needs-revision"))
        self.assertIsNone(self.kind("code", "plan:ready", "status:queued"))
        self.assertIsNone(self.kind("code", "changes-requested", "status:blocked"))

    def test_review_needs_clean_handoff(self) -> None:
        self.assertEqual(self.kind("review", "plan:ready", "needs-code-review"), "review")
        self.assertIsNone(self.kind("review", "needs-code-review", "status:needs-review"))
        self.assertIsNone(self.kind("review", "needs-code-review", "changes-requested"))

    def test_in_flight_work_before_new_work(self) -> None:
        issues = [issue(3, "plan:ready"), issue(9, "changes-requested"), issue(5, "status:needs-review"),
                  issue(1, "plan:ready")]
        comments = {5: [GATE_FAIL]}
        order = [(i["number"], k) for i, k in oa.work_items("code", issues, lambda n: comments.get(n, []))]
        self.assertEqual(order, [(9, "changes"), (5, "gate-fix"), (1, "implement"), (3, "implement")])


class TestTiers(unittest.TestCase):
    def test_default_escalation_and_cap(self) -> None:
        self.assertEqual(oa.pick_tier(set(), 0)[0], "medium")
        self.assertEqual(oa.pick_tier({"tier:light"}, 0)[0], "light")
        self.assertEqual(oa.pick_tier({"tier:light"}, 1)[0], "medium")
        self.assertEqual(oa.pick_tier({"tier:light"}, 0, offset=1)[0], "medium")
        self.assertEqual(oa.pick_tier({"tier:medium"}, 5)[0], "heavy")
        self.assertEqual(oa.pick_tier({"tier:light", "tier:heavy"}, 0)[0], "heavy")

    def test_failures_count_gate_reviews_and_missing_handoffs(self) -> None:
        rows = [{"role": "review", "outcome": "changes-requested"}, {"role": "code", "outcome": None},
                {"role": "code", "outcome": None, "rate_limited": True}, {"role": "code", "outcome": "submitted"}]
        self.assertEqual(oa.code_failures([GATE_FAIL, GATE_PASS, "text"], rows), 3)

    def test_backend_per_role(self) -> None:
        cfg = oa.load_config()
        self.assertEqual(oa.backend_for(cfg, "plan", {"tier:light"}, 0), ("opus", None))
        self.assertEqual(oa.backend_for(cfg, "code", {"tier:light"}, 0), ("gemini-flash", "light"))
        self.assertEqual(oa.backend_for(cfg, "review", {"tier:light"}, 0), ("glm", "medium"))
        self.assertEqual(oa.backend_for(cfg, "review", {"tier:medium"}, 1), ("opus", "heavy"))


class TestOutcome(unittest.TestCase):
    def test_plan(self) -> None:
        before = {"research:new-lever"}
        self.assertEqual(oa.outcome("plan", before, before | {"plan:ready", "tier:medium"}, "OPEN"), "planned")
        self.assertIsNone(oa.outcome("plan", before, before | {"plan:ready"}, "OPEN"))  # tier missing
        self.assertEqual(oa.outcome("plan", before, before | {"plan:rejected"}, "CLOSED"), "rejected")
        self.assertIsNone(oa.outcome("plan", before, before, "OPEN"))

    def test_code(self) -> None:
        before = {"plan:ready", "status:needs-review"}
        self.assertEqual(oa.outcome("code", before, {"plan:ready", "needs-code-review"}, "OPEN"), "submitted")
        self.assertIsNone(oa.outcome("code", before, before | {"needs-code-review"}, "OPEN"))  # status label left
        self.assertEqual(oa.outcome("code", before, {"plan:ready", "plan:needs-revision"}, "OPEN"), "replan")
        self.assertEqual(oa.outcome("code", before, before | {"status:blocked"}, "OPEN"), "blocked")

    def test_review(self) -> None:
        before = {"plan:ready", "needs-code-review"}
        self.assertEqual(oa.outcome("review", before, {"plan:ready", "status:ready-to-test"}, "OPEN"), "approved")
        self.assertEqual(oa.outcome("review", before, {"plan:ready", "changes-requested"}, "OPEN"), "changes-requested")
        self.assertEqual(oa.outcome("review", before, {"plan:ready", "plan:needs-revision"}, "OPEN"), "replan")
        self.assertIsNone(oa.outcome("review", before, before | {"status:ready-to-test"}, "OPEN"))


class TestLimitsAndLocks(StateTestCase):
    def test_limits(self) -> None:
        item = {"role": "code", "kind": "changes"}
        rows = [{"role": "review", "outcome": "changes-requested"}] * 2
        self.assertIsNone(oa.limit_violation(self.cfg, item, rows))
        self.assertIn("Review-Runden", oa.limit_violation(self.cfg, item, rows * 2))
        self.assertIn("ohne gültige Übergabe", oa.limit_violation(self.cfg, item, [{"role": "code", "outcome": None}] * 2))
        plan = {"role": "plan", "kind": "revise"}
        self.assertIn("Plan", oa.limit_violation(self.cfg, plan, [{"role": "plan", "outcome": "planned"}] * 3))

    def test_slots_are_exclusive_and_freed_on_close(self) -> None:
        fds = [oa.acquire_slot(2), oa.acquire_slot(2)]
        self.assertNotIn(None, fds)
        self.assertIsNone(oa.acquire_slot(2))
        self.assertEqual(oa.free_slots(2), 0)
        os.close(fds[0])
        self.assertEqual(oa.free_slots(2), 1)

    def test_backend_problems(self) -> None:
        self.assertIn("kein Modellname", oa.backend_problem(self.cfg, "gemini-flash"))
        cfg = copy.deepcopy(self.cfg)
        cfg["backends"]["glm"]["key_file"] = str(Path(self.tmp.name) / "missing")
        with mock.patch.object(oa.shutil, "which", return_value="/usr/bin/claude"):
            self.assertIn("Schlüsseldatei", oa.backend_problem(cfg, "glm"))
            self.assertIsNone(oa.backend_problem(cfg, "opus"))
            (Path(self.tmp.name) / "cooldown-opus").write_text(str(oa.time.time() + 600))
            self.assertIn("Nutzungslimit", oa.backend_problem(cfg, "opus"))


class TestLaunchHelpers(StateTestCase):
    def test_env_never_routes_opus_elsewhere(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic", "ANTHROPIC_AUTH_TOKEN": "x"}):
            env = oa.agent_env(self.cfg["backends"]["opus"])
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        key = Path(self.tmp.name) / "zai"
        key.write_text("secret\n")
        glm = dict(self.cfg["backends"]["glm"], key_file=str(key))
        env = oa.agent_env(glm)
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "secret")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")

    def test_limit_detection_ignores_file_contents(self) -> None:
        tool_output = json.dumps({"type": "user", "message": {"content": "grep: rate limit 429"}})
        result = json.dumps({"type": "result", "is_error": True, "result": "Claude usage limit reached"})
        self.assertFalse(oa.is_limit_message("claude", tool_output))
        self.assertTrue(oa.is_limit_message("claude", result))
        self.assertTrue(oa.is_limit_message("agy", "Error: RESOURCE_EXHAUSTED quota exceeded"))

    def test_every_role_has_a_prompt(self) -> None:
        for role in oa.ROLES:
            item = {"role": role, "issue": 7 if role in ("plan", "code", "review") else None, "title": "x",
                    "kind": {"plan": "new", "code": "implement", "review": "review"}.get(role, role),
                    "backend": "opus", "tier": "medium" if role == "code" else None, "failures": 0}
            text = oa.build_prompt(self.cfg, item, [], Path("/wt"), "b")
            self.assertIn(f"Rolle: **{role}**", text)
            self.assertIn("# Rolle:", text)


class TestRun(StateTestCase):
    """One review run end to end with GitHub and the agent CLI replaced."""

    def run_review(self, labels_after: set[str]) -> tuple[int, list[tuple], list[dict]]:
        labels = {"plan:ready", "tier:light", "needs-code-review"}
        calls: list[tuple] = []
        patches = [
            mock.patch.object(oa, "git_out", side_effect=lambda *a: "/wt" if a[0] == "rev-parse" else "lever-x"),
            mock.patch.object(oa, "open_issues", return_value=[issue(12, *labels)]),
            mock.patch.object(oa, "gh_comments", return_value=[]),
            mock.patch.object(oa, "issue_view", return_value={"labels": labels_after, "state": "OPEN", "comments": []}),
            mock.patch.object(oa, "gh", side_effect=lambda *a: calls.append(a) or ""),
            mock.patch.object(oa, "launch", return_value=(0, False)),
            mock.patch.object(oa.shutil, "which", return_value="/usr/bin/claude"),
            mock.patch.object(oa, "cooling_until", return_value=0.0),
        ]
        cfg = copy.deepcopy(self.cfg)
        key = Path(self.tmp.name) / "zai"
        key.write_text("k")
        cfg["backends"]["glm"]["key_file"] = str(key)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        rc = oa.cmd_run(cfg, "review")
        return rc, calls, oa.ledger(12)

    def test_approval_is_recorded(self) -> None:
        rc, calls, rows = self.run_review({"plan:ready", "tier:light", "status:ready-to-test"})
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertEqual((rows[-1]["outcome"], rows[-1]["backend"], rows[-1]["tier"]), ("approved", "glm", "medium"))

    def test_missing_handoff_is_reported(self) -> None:
        rc, calls, rows = self.run_review({"plan:ready", "tier:light", "needs-code-review"})
        self.assertEqual(rc, 1)
        self.assertIsNone(rows[-1]["outcome"])
        self.assertTrue(any(c[:2] == ("issue", "comment") and "ohne gültige Label-Übergabe" in c[-1] for c in calls))


if __name__ == "__main__":
    unittest.main()
