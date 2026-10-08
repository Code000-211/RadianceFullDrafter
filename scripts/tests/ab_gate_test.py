"""Tests for Tier 4 of scripts/ab_gate.py: the diagnose runs, the corpus export and the verdict.

No engine and no GPU: start_engine.sh is replaced by a fake that writes a diagnose report, and
BetterBench by a fake package.

Run: python3 -m unittest scripts/tests/ab_gate_test.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("ab_gate", SCRIPTS_DIR / "ab_gate.py")
ag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ag)

DCFG = {**ag.DIAGNOSE_DEFAULTS, "port": 8123, "timeout_s": 30}


def run(rc=0, verdict="valid", parity=None, problems=None):
    """A run_diagnose result as judge_diagnose sees it."""
    report = {"verdict": verdict, "problems": problems or []}
    if parity is not None:
        report["parity"] = parity
    return {"rc": rc, "report": report, "log": "engine.log", "report_path": "diagnose.json", "wall_s": 1.0}


IDENTICAL = {"compared": 10, "identical": 10, "verdict": "identical", "acceptance_verdict": "no drop",
             "differing": [], "acceptance_dropped": []}
DIFFERS = {**IDENTICAL, "identical": 7, "verdict": "DIFFERS",
           "differing": [{"point": "concurrency 8", "run": 1, "request": 3, "first_different_token": 41}]}
DROPPED = {**IDENTICAL, "acceptance_verdict": "DROPPED",
           "acceptance_dropped": [{"point": "categories code", "what": "position 2", "now": 0.41,
                                   "baseline": 0.55, "z": -5.2}]}


class JudgeTest(unittest.TestCase):
    def test_identical_passes(self):
        j = ag.judge_diagnose(run(), run(parity=IDENTICAL), False)
        self.assertEqual(j["kind"], "pass")
        self.assertNotIn("declared", j)

    def test_differing_tokens_fail_a_bitexact_lever(self):
        j = ag.judge_diagnose(run(), run(rc=4, parity=DIFFERS), False)
        self.assertEqual(j["kind"], "fail")
        self.assertIn("7 of 10", j["why"])

    def test_differing_tokens_go_to_leon_when_declared(self):
        j = ag.judge_diagnose(run(), run(rc=4, parity=DIFFERS), True)
        self.assertEqual(j["kind"], "pass")
        self.assertTrue(j["declared"])
        self.assertIn("Leon", j["why"])

    def test_an_acceptance_drop_fails_even_when_declared(self):
        for declared in (False, True):
            j = ag.judge_diagnose(run(), run(rc=4, parity=DROPPED), declared)
            self.assertEqual(j["kind"], "fail", declared)
            self.assertIn("acceptance", j["why"])

    def test_a_baseline_run_that_is_not_a_measurement_is_a_setup_error(self):
        j = ag.judge_diagnose(run(verdict="NOT A MEASUREMENT", problems=["cache hit"]), run(parity=IDENTICAL), False)
        self.assertEqual(j["kind"], "setup")
        j = ag.judge_diagnose({"rc": None, "report": None, "log": "x"}, run(parity=IDENTICAL), False)
        self.assertEqual(j["kind"], "setup")

    def test_a_candidate_run_that_breaks_is_the_candidates_failure(self):
        self.assertEqual(ag.judge_diagnose(run(), {"rc": None, "report": None, "log": "x"}, False)["kind"], "fail")
        self.assertEqual(ag.judge_diagnose(run(), run(rc=4, verdict="NOT A MEASUREMENT"), False)["kind"], "fail")

    def test_no_comparison_is_a_setup_error(self):
        j = ag.judge_diagnose(run(), run(rc=4, parity={"verdict": "not compared: different workloads"}), False)
        self.assertEqual(j["kind"], "setup")
        self.assertEqual(ag.judge_diagnose(run(), run(), False)["kind"], "setup")


class CorpusExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name in [m for m in sys.modules if m == "betterbench" or m.startswith("betterbench.")]:
            del sys.modules[name]

    def tearDown(self):
        for name in [m for m in sys.modules if m == "betterbench" or m.startswith("betterbench.")]:
            del sys.modules[name]
        while str(self.dir / "bb") in sys.path:
            sys.path.remove(str(self.dir / "bb"))
        self.tmp.cleanup()

    def fake_bb(self, body: str) -> str:
        pkg = self.dir / "bb" / "betterbench"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "corpus.py").write_text(textwrap.dedent(body))
        return str(self.dir / "bb")

    def test_dict_entries_with_messages(self):
        bb = self.fake_bb("""
            def load_corpus(a, b):
                return [{"id": "c1", "category": "code", "messages": [{"role": "user", "content": "write"}]},
                        {"id": "p1", "category": "prose", "messages": [{"role": "user", "content": "tell"}], "max_tokens": 300}]
        """)
        path, note = ag.export_bb_corpus(bb, self.dir / "c.jsonl")
        self.assertIsNotNone(path, note)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([r["category"] for r in rows], ["code", "prose"])
        self.assertNotIn("max_tokens", rows[0])
        self.assertEqual(rows[1]["max_tokens"], 300)
        self.assertIn("2 prompts in 2 categories", note)

    def test_objects_with_a_prompt(self):
        bb = self.fake_bb("""
            class P:
                def __init__(self, c, p):
                    self.category, self.prompt = c, p
            def load_corpus(a, b):
                return {"x": P("json", "list three")}
        """)
        path, _ = ag.export_bb_corpus(bb, self.dir / "c.jsonl")
        self.assertIsNotNone(path)
        row = json.loads(path.read_text())
        self.assertEqual(row["messages"], [{"role": "user", "content": "list three"}])

    def test_an_unknown_shape_falls_back_with_the_reason(self):
        bb = self.fake_bb("""
            def load_corpus(a, b):
                return [{"name": "no category"}]
        """)
        path, note = ag.export_bb_corpus(bb, self.dir / "c.jsonl")
        self.assertIsNone(path)
        self.assertIn("without category", note)
        for name in [m for m in sys.modules if m == "betterbench" or m.startswith("betterbench.")]:
            del sys.modules[name]
        sys.path.remove(bb)
        path, note = ag.export_bb_corpus(str(self.dir / "nowhere"), self.dir / "d.jsonl")
        self.assertIsNone(path)
        self.assertIn("not loadable", note)


class RunDiagnoseTest(unittest.TestCase):
    """run_diagnose against a fake start_engine.sh that records how it was called."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = ag.SCRIPT_DIR
        ag.SCRIPT_DIR = self.dir
        (self.dir / "start_engine.sh").write_text(textwrap.dedent("""\
            #!/usr/bin/env bash
            printf '%s\\n' "$@" > "$(dirname "$0")/args.txt"
            echo "FG=${RADIANCE_ENGINE_FOREGROUND:-} X=${X:-}" > "$(dirname "$0")/env.txt"
            out=""
            while [ $# -gt 0 ]; do
                if [ "$1" = "--diagnose" ]; then out="$2"; fi
                shift
            done
            echo '{"verdict": "valid"}' > "$out/diagnose.json"
            exit ${FAKE_RC:-0}
        """))

    def tearDown(self):
        ag.SCRIPT_DIR = self.saved
        self.tmp.cleanup()

    def test_arguments_environment_and_report(self):
        corpus = self.dir / "c.jsonl"
        corpus.write_text("{}\n")
        r = ag.run_diagnose(self.dir / "build", self.dir / "out", DCFG, corpus, self.dir / "base.json",
                            ["--flag"], {"X": "1"})
        self.assertEqual(r["rc"], 0)
        self.assertEqual(r["report"], {"verdict": "valid"})
        args = (self.dir / "args.txt").read_text().split("\n")
        self.assertIn("--diagnose", args)
        self.assertEqual(args[args.index("--diagnose-prefill") + 1], DCFG["prefill"])
        self.assertEqual(args[args.index("--diagnose-corpus") + 1], str(corpus))
        self.assertEqual(args[args.index("--diagnose-baseline") + 1], str(self.dir / "base.json"))
        self.assertEqual(args[args.index("--port") + 1], "8123")
        self.assertEqual(args[-2], "--flag")   # the candidate's own flags come last
        self.assertEqual((self.dir / "env.txt").read_text().strip(), "FG=1 X=1")

    def test_no_corpus_no_baseline(self):
        r = ag.run_diagnose(self.dir / "build", self.dir / "out", DCFG, None, None, [], {})
        args = (self.dir / "args.txt").read_text().split("\n")
        self.assertNotIn("--diagnose-corpus", args)
        self.assertNotIn("--diagnose-baseline", args)
        self.assertEqual(r["rc"], 0)


class ReportTest(unittest.TestCase):
    def test_tier4_section(self):
        summary = {
            "verdict": "FAIL (diagnose: ...)", "baseline_build": "/a", "candidate_build": "/b", "mode": "ab",
            "blocks": [], "comparison": {"rows": []},
            "diagnose": {
                "judgement": {"kind": "fail", "why": "draft acceptance dropped"},
                "corpus_note": "BetterBench corpus, 2 prompts",
                "baseline": {"rc": 0, "wall_s": 10.0, "report_path": "/a/diagnose.json"},
                "candidate": {"rc": 4, "wall_s": 11.0, "report_path": "/b/diagnose.json",
                              "report": {"parity": {**DIFFERS, **{k: DROPPED[k] for k in ("acceptance_verdict", "acceptance_dropped")}}}},
            },
        }
        md = ag.render_report(summary)
        self.assertIn("## Tier 4", md)
        self.assertIn("**FAIL**", md)
        self.assertIn("differs: concurrency 8 run 1 request 3 from token 41", md)
        self.assertIn("acceptance dropped: categories code position 2 0.41 vs 0.55 (z -5.2)", md)


if __name__ == "__main__":
    unittest.main()
