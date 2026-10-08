"""Tests for scripts/orca_agent.py: selection, tiers, handoff, limits, slots, one simulated run.

Run: python3 -m unittest scripts/tests/orca_agent_test.py
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

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
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
        self.assertEqual(self.kind("plan", "upstream:sync"), "new")
        self.assertIsNone(self.kind("plan", "upstream:sync", "plan:ready"))
        self.assertEqual(self.kind("code", "upstream:sync", "plan:ready", "tier:heavy"), "implement")

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
    DISTINCT = {"light": "a", "medium": "b", "heavy": "c", "fallback": "d"}
    SHARED = {"light": "gemini", "medium": "gemini", "heavy": "glm", "fallback": "opus"}

    def test_escalation_with_distinct_backends(self) -> None:
        t = lambda labels, steps=0, max_tier="fallback": oa.pick_tier(self.DISTINCT, labels, steps, max_tier)[0]
        self.assertEqual(t(set()), "medium")
        self.assertEqual(t({"tier:light"}), "light")
        self.assertEqual(t({"tier:light"}, 1), "medium")
        self.assertEqual(t({"tier:heavy"}, 1), "fallback")
        self.assertEqual(t({"tier:medium"}, 5, "heavy"), "heavy")
        self.assertEqual(t({"tier:light", "tier:heavy"}), "heavy")
        self.assertEqual(t({"tier:fallback"}), "medium")  # planner cannot pick Opus

    def test_each_step_changes_the_model(self) -> None:
        t = lambda labels, steps=0, max_tier="fallback": oa.pick_tier(self.SHARED, labels, steps, max_tier)[0]
        self.assertEqual(t({"tier:light"}), "light")
        self.assertEqual(t({"tier:light"}, 1), "heavy")      # not medium: same Gemini model
        self.assertEqual(t({"tier:light"}, 2), "fallback")
        self.assertEqual(t({"tier:medium"}, 1), "heavy")
        self.assertEqual(t({"tier:heavy"}, 1, "heavy"), "heavy")

    def test_failures_count_gate_reviews_and_missing_handoffs(self) -> None:
        rows = [{"role": "review", "outcome": "changes-requested"}, {"role": "code", "outcome": None},
                {"role": "code", "outcome": None, "rate_limited": True}, {"role": "code", "outcome": "submitted"}]
        self.assertEqual(oa.code_failures([GATE_FAIL, GATE_PASS, "text"], rows), 3)

    def test_opus_only_for_planning_and_as_last_code_step(self) -> None:
        cfg = oa.load_config()
        first = lambda role, labels, f: oa.backend_options(cfg, role, labels, f)[0]
        self.assertEqual(first("plan", {"tier:light"}, 0), ("opus", None))
        self.assertEqual(cfg["roles"]["answer"]["backend"], "opus")
        self.assertEqual(first("code", {"tier:light"}, 0), ("gemini", "light"))
        self.assertEqual(first("code", {"tier:medium"}, 0), ("gemini", "medium"))
        self.assertEqual(first("code", {"tier:light"}, 1), ("glm", "heavy"))
        self.assertEqual(first("code", {"tier:heavy"}, 0), ("glm", "heavy"))
        self.assertEqual(first("code", {"tier:heavy"}, 1), ("opus", "fallback"))
        self.assertEqual(first("review", {"tier:light"}, 0), ("glm", "heavy"))    # never the coder's model
        self.assertEqual(first("review", {"tier:heavy"}, 3), ("glm", "heavy"))
        for role in ("research", "audit", "upstream"):
            self.assertNotEqual(first(role, set(), 0)[0], "opus")

    def test_unavailable_backend_moves_up_but_not_to_opus(self) -> None:
        cfg = oa.load_config()
        self.assertEqual(oa.backend_options(cfg, "code", {"tier:light"}, 0), [("gemini", "light"), ("glm", "heavy")])
        cfg["limits"]["availability_fallback"] = True
        self.assertEqual(oa.backend_options(cfg, "code", {"tier:heavy"}, 0)[-1], ("opus", "fallback"))
        with mock.patch.object(oa, "backend_problem", side_effect=lambda c, n: None if n == "glm" else "gesperrt"):
            picked = oa.choose_backend(cfg, [("gemini", "light"), ("glm", "heavy")], lambda m: None)
        self.assertEqual(picked, ("glm", "heavy"))


class TestBrief(unittest.TestCase):
    VIEW = {"title": "t", "body": "Idee: X fusionieren", "comments": [
        oa.PLAN_MARKER + " alter Plan", "Plauderei", oa.RESULT_MARKER + "\n### Gate nicht bestanden: alt",
        oa.PLAN_MARKER + " neuer Plan", oa.HANDOFF_MARKER + " Übergabe 1\ncandidate: x\nref: agent/a",
        oa.REVIEW_MARKER + " Befund A", oa.QA_MARKER + " Frage/Antwort", "unwichtig"]}

    def test_code_changes_gets_only_what_it_needs(self) -> None:
        brief = oa.build_brief("code", "changes", self.VIEW)
        for needed in ("Idee: X", "neuer Plan", "Befund A", "Frage/Antwort", "Übergabe 1", "ref: agent/a"):
            self.assertIn(needed, brief)
        for noise in ("alter Plan", "Plauderei", "unwichtig", "Gate nicht bestanden"):
            self.assertNotIn(noise, brief)

    def test_gate_fix_gets_gate_report(self) -> None:
        self.assertIn("Gate nicht bestanden", oa.build_brief("code", "gate-fix", self.VIEW))

    def test_revision_gets_everything_since_the_plan(self) -> None:
        brief = oa.build_brief("plan", "revise", self.VIEW)
        self.assertIn("neuer Plan", brief)
        self.assertIn("Befund A", brief)
        self.assertIn("unwichtig", brief)
        self.assertNotIn("alter Plan", brief)


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
        cfg = copy.deepcopy(self.cfg)
        cfg["backends"]["gemini"]["model"] = None
        self.assertIn("kein Modellname", oa.backend_problem(cfg, "gemini"))
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
            text = oa.build_prompt(self.cfg, item, [], Path("/wt"), "b", "# Übergabe\nX")
            self.assertIn(f"Rolle: **{role}**", text)
            self.assertIn("# Rolle:", text)
            self.assertTrue(text.endswith("# Übergabe\nX"))
            self.assertEqual("orca_agent.py ask" in text, role in oa.ASK_ROLES)
        self.assertTrue((oa.PROMPTS / "answer.md").is_file())


class TestRun(StateTestCase):
    """One review run end to end with GitHub and the agent CLI replaced."""

    def run_review(self, labels_after: set[str]) -> tuple[int, list[tuple], list[dict]]:
        labels = {"plan:ready", "tier:light", "needs-code-review"}
        calls: list[tuple] = []
        patches = [
            mock.patch.object(oa, "git", side_effect=lambda *a, **k: "/wt" if a[0] == "rev-parse" else "lever-x"),
            mock.patch.object(oa, "open_issues", return_value=[issue(12, *labels)]),
            mock.patch.object(oa, "gh_comments", return_value=[]),
            mock.patch.object(oa, "issue_view", side_effect=[
                {"labels": labels, "state": "OPEN", "comments": [], "body": "b", "title": "t"},
                {"labels": labels_after, "state": "OPEN", "comments": [], "body": "b", "title": "t"}]),
            mock.patch.object(oa, "gh", side_effect=lambda *a: calls.append(a) or ""),
            mock.patch.object(oa, "launch", return_value=(0, False, "")),
            mock.patch.object(oa.shutil, "which", return_value="/usr/bin/claude"),
            mock.patch.object(oa, "cooling_until", return_value=0.0),
            mock.patch.object(oa.subprocess, "run", side_effect=lambda cmd, **k: calls.append(("setup", *cmd)) or
                              mock.Mock(returncode=0)),
        ]
        cfg = copy.deepcopy(self.cfg)
        key = Path(self.tmp.name) / "zai"
        key.write_text("k")
        cfg["backends"]["glm"]["key_file"] = str(key)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        rc = oa.cmd_run(cfg, "review", 12)
        return rc, calls, oa.ledger(12)

    def test_approval_is_recorded(self) -> None:
        rc, calls, rows = self.run_review({"plan:ready", "tier:light", "status:ready-to-test"})
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("setup", "bash", "/wt/scripts/orca_setup.sh")])
        self.assertEqual((rows[-1]["outcome"], rows[-1]["backend"], rows[-1]["tier"]), ("approved", "glm", "heavy"))

    def test_missing_handoff_is_reported(self) -> None:
        rc, calls, rows = self.run_review({"plan:ready", "tier:light", "needs-code-review"})
        self.assertEqual(rc, 1)
        self.assertIsNone(rows[-1]["outcome"])
        self.assertTrue(any(c[:2] == ("issue", "comment") and "ohne gültige Label-Übergabe" in c[-1] for c in calls))


class TestAsk(StateTestCase):
    def test_question_is_answered_by_a_fresh_planner_session(self) -> None:
        env = {"RADIANCE_AGENT_ROLE": "code", "RADIANCE_AGENT_ISSUE": "12", "RADIANCE_AGENT_RUN": "r1"}
        posted: list[tuple] = []
        view = {"title": "t", "body": "", "labels": set(), "state": "OPEN",
                "comments": [oa.PLAN_MARKER + " Plan: Schritt 2 ändert foo()"]}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(oa.subprocess, "Popen") as popen, \
                mock.patch.object(oa, "wait_answer", return_value=0):
            self.assertEqual(oa.cmd_ask(self.cfg, "Gilt Schritt 2 auch für bar()?", 1), 0)
        qid = popen.call_args[0][0][-1]
        prompts = []
        with mock.patch.object(oa, "issue_view", return_value=view), \
                mock.patch.object(oa, "backend_problem", return_value=None), \
                mock.patch.object(oa, "comment", side_effect=lambda n, b: posted.append((n, b))), \
                mock.patch.object(oa, "launch", side_effect=lambda b, p, *a, **k: prompts.append((b, p, k)) or (0, False, "Nur foo().")):
            self.assertEqual(oa.cmd_answer_worker(self.cfg, qid), 0)
        backend, prompt, kwargs = prompts[0]
        self.assertEqual(backend["model"], "opus")
        self.assertTrue(kwargs["read_only"])
        self.assertIn("Schritt 2 ändert foo()", prompt)
        self.assertIn("Gilt Schritt 2 auch für bar()?", prompt)
        self.assertEqual(posted[0][0], 12)
        self.assertIn(oa.QA_MARKER, posted[0][1])
        q = json.loads(oa.question_path(qid).read_text())
        self.assertEqual((q["status"], q["answer"]), ("answered", "Nur foo()."))
        self.assertEqual(oa.wait_answer(qid, 0), 0)

    def test_question_limit_and_roles(self) -> None:
        with mock.patch.dict(os.environ, {"RADIANCE_AGENT_ROLE": "plan", "RADIANCE_AGENT_ISSUE": "1"}):
            self.assertEqual(oa.cmd_ask(self.cfg, "?", 0), 2)
        env = {"RADIANCE_AGENT_ROLE": "review", "RADIANCE_AGENT_ISSUE": "3", "RADIANCE_AGENT_RUN": "r2"}
        with mock.patch.dict(os.environ, env), mock.patch.object(oa.subprocess, "Popen"), \
                mock.patch.object(oa, "wait_answer", return_value=0), mock.patch.object(oa.time, "strftime", side_effect=["a", "b", "c", "d"] + ["x"] * 10):
            for _ in range(self.cfg["limits"]["max_questions"]):
                self.assertEqual(oa.cmd_ask(self.cfg, "?", 0), 0)
            self.assertEqual(oa.cmd_ask(self.cfg, "?", 0), 1)


class TestTick(StateTestCase):
    def test_reservation_prevents_double_start(self) -> None:
        cfg = copy.deepcopy(self.cfg)
        cfg["orca"]["launcher"] = "detached"
        cfg["backends"]["gemini"]["model"] = "flash-x"
        started = []
        orig = oa.find_work
        with mock.patch.object(oa, "git", return_value=""), \
                mock.patch.object(oa, "open_issues", return_value=[issue(4, "plan:ready", "tier:light")]), \
                mock.patch.object(oa, "gh_comments", return_value=[]), \
                mock.patch.object(oa.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(oa.subprocess, "Popen", side_effect=lambda *a, **k: started.append(a[0])), \
                mock.patch.object(oa, "find_work", side_effect=lambda c, r, **k: orig(c, r, **k) if r == "code" else None):
            self.assertEqual(oa.cmd_tick(cfg), 0)
            self.assertEqual(oa.cmd_tick(cfg), 0)
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][-2:], ["--issue", "4"])
        self.assertTrue(oa.reserved("code", 4))
        self.assertEqual(len(oa.worktree_records()), 1)


class TestOrcaWorktrees(StateTestCase):
    def test_orca_creates_the_worktree_and_removes_it_by_id(self) -> None:
        wt = Path(self.tmp.name) / "workspaces" / "agent-code-4"
        wt.mkdir(parents=True)
        wid = f"2a02::{wt}"
        calls: list[tuple] = []

        def orca(cfg, *args):
            calls.append(args)
            if args[:2] == ("worktree", "create"):  # nesting as reported by orca-ide 1.4.192, wrapped once more
                return json.dumps({"ok": True, "result": {"worktree": {"id": wid, "path": str(wt), "branch": "x"}}})
            return json.dumps({"ok": True})

        cfg = copy.deepcopy(self.cfg)
        with mock.patch.object(oa, "orca", side_effect=orca), \
                mock.patch.object(oa, "git", side_effect=lambda *a, **k: "OoguroRyuuya/agent-code-4" if a[:2] == ("rev-parse", "--abbrev-ref") else ""), \
                mock.patch.object(oa.subprocess, "run", return_value=mock.Mock(returncode=1)):
            path = oa.start_agent(cfg, {"role": "code", "issue": 4})
            self.assertEqual(path, wt)
            self.assertIn(("terminal", "create", "--worktree", f"id:{wid}", "--title", "code #4", "--command",
                           f"python3 {oa.PRIMARY / 'scripts' / 'orca_agent.py'} run code --issue 4"), calls)
            rec = next(iter(oa.worktree_records().values()))
            self.assertEqual((rec["orca_id"], rec["branch"]), (wid, "OoguroRyuuya/agent-code-4"))
            oa.remove_worktree(cfg, rec, "agent-code-4")
            self.assertIn(("worktree", "rm", "--worktree", f"id:{wid}", "--force"), calls)

    def test_missing_id_is_an_error(self) -> None:
        with mock.patch.object(oa, "orca", return_value=json.dumps({"ok": True, "result": {}})):
            with self.assertRaises(RuntimeError):
                oa.create_worktree(self.cfg, "x")


if __name__ == "__main__":
    unittest.main()
