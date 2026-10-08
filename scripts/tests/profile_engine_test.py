"""Tests for the trace analysis in scripts/profile_engine.py on a synthetic rocprofv3 CSV.

Run: python3 -m unittest scripts/tests/profile_engine_test.py
"""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
spec = importlib.util.spec_from_file_location("profile_engine", SCRIPTS_DIR / "profile_engine.py")
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)

FIELDS = ["Kind", "Agent_Id", "Queue_Id", "Kernel_Name", "Correlation_Id", "Start_Timestamp", "End_Timestamp"]


def synthetic(path: Path, steps: int = 12) -> None:
    """Two ranks. Per step: marker 4 us, small 5 us, 20 us gap, gemm 100 us, 2 us gap, back to marker."""
    rows = []
    for agent in ("Agent 1", "Agent 2"):
        t = 1_000_000
        for _ in range(steps):
            for name, dur, gap in (("void r4d_rowtopk_stage1<1>(float*)", 4_000, 2_000),
                                   ("void (anonymous namespace)::small_op(int)", 5_000, 20_000),
                                   ("void gemm_w4a8 <true, 1u>(int)", 100_000, 2_000)):
                rows.append({"Kind": "KERNEL_DISPATCH", "Agent_Id": agent, "Queue_Id": 0, "Kernel_Name": name,
                             "Correlation_Id": 0, "Start_Timestamp": t, "End_Timestamp": t + dur})
                t += dur + gap
    rows.append({"Kind": "MEMORY_COPY", "Agent_Id": "Agent 1", "Queue_Id": 0, "Kernel_Name": "",
                 "Correlation_Id": 0, "Start_Timestamp": 0, "End_Timestamp": 1})
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows(rows)


class TestAnalysis(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.csv = Path(tmp.name) / "k_kernel_trace.csv"
        synthetic(self.csv)

    def test_names_like_tsum(self) -> None:
        names = {r[3] for r in pd.read_trace(self.csv)}
        self.assertEqual(names, {"r4d_rowtopk_stage1<1>", "small_op", "gemm_w4a8<true,1u>"})

    def test_window_busy_gaps_and_joins(self) -> None:
        a = pd.analyse(pd.read_trace(self.csv), overhead_us=1.0)
        self.assertAlmostEqual(a["traced_ms_per_step"], 0.133)
        r = a["ranks"]["Agent 1"]
        self.assertEqual(r["dispatches_per_step"], 3.0)
        self.assertAlmostEqual(r["busy_ms_per_step"], 0.109)
        self.assertAlmostEqual(r["gap_ms_per_step_traced"], 0.024, places=3)
        self.assertAlmostEqual(r["gap_ms_per_step_corrected"], 0.021, places=3)  # 3 gaps, 1 us tracer each
        top = a["joins"][0]
        self.assertEqual((top["from"], top["to"]), ("small_op", "gemm_w4a8<true,1u>"))
        self.assertAlmostEqual(top["gap_us_per_step"], 19.0)
        self.assertEqual(a["small_kernels"]["count_per_step"], 2.0)  # marker 4 us and small_op 5 us
        self.assertEqual(a["kernels"][0]["kernel"], "gemm_w4a8<true,1u>")

    def test_no_decode_is_an_error(self) -> None:
        rows = [r for r in pd.read_trace(self.csv) if "rowtopk" not in r[3]]
        with self.assertRaises(RuntimeError):
            pd.analyse(rows, 0.0)

    def test_report_renders(self) -> None:
        a = pd.analyse(pd.read_trace(self.csv), overhead_us=1.0)
        rows = pd.read_trace(self.csv)
        md = pd.render({"commit": "abc", "build_dir": "b", "date": "d", "levels": [
            {"streams": 1, "untraced": {"decode_tps": 50.0}, "untraced_ms_per_step": 0.12, "overhead_us": 1.0,
             "analysis": a, "slow_steps": pd.slow_steps(rows, 1.0), "warnings": ["gaps.sh rc=1"]}],
            "prefill": {"prompt_tokens": 64000, "untraced_tps": 9000.0, "overhead_us": 1.0, "warnings": [],
                        "analysis": pd.analyse(rows, 1.0, pd.last_burst(rows))}})
        self.assertIn("| `small_op` | `gemm_w4a8<true,1u>` |", md)
        self.assertIn("**Warnung:** gaps.sh rc=1", md)
        self.assertIn("## Prefill, 64000 Prompt-Tokens", md)
        self.assertIn("Langsamste Schritte", md)


class TestOutliersAndBursts(unittest.TestCase):
    def rows(self, slow_every: int = 0) -> list:
        """One rank, 40 steps; every `slow_every`-th step has a 300 us longer gemm and a 500 us host wait."""
        rows, t = [], 0
        for i in range(40):
            slow = slow_every and i % slow_every == 0
            for name, dur, gap in (("r4d_rowtopk_stage1", 4_000, 2_000), ("small_op", 5_000, 520_000 if slow else 20_000),
                                   ("gemm", 400_000 if slow else 100_000, 2_000)):
                rows.append(("Agent 1", t, t + dur, name))
                t += dur + gap
        return rows

    def test_slow_steps_name_their_cause(self) -> None:
        so = pd.slow_steps(self.rows(slow_every=10), overhead_us=1.0)
        self.assertEqual(so["slow_count"], 3)
        causes = {(c["kernel"], c["where"]): c["extra_us"] for c in so["contributors"]}
        self.assertAlmostEqual(causes[("gemm", "Lücke davor")], 500.0, places=0)
        self.assertAlmostEqual(causes[("gemm", "Kernel-Zeit")], 300.0, places=0)
        self.assertGreater(so["slow_ms"], so["typical_ms"])

    def test_last_burst_skips_model_load(self) -> None:
        load = [("Agent 1", 0, 1_000_000, "load_weights")]
        req = [("Agent 1", 5_000_000_000 + i * 10_000, 5_000_000_000 + i * 10_000 + 8_000, "prefill_gemm") for i in range(100)]
        t0, t1, n = pd.last_burst(load + req)
        self.assertEqual((t0, n), (5_000_000_000, 1))
        a = pd.analyse(load + req, 0.0, (t0, t1, n))
        self.assertEqual([k["kernel"] for k in a["kernels"]], ["prefill_gemm"])


if __name__ == "__main__":
    unittest.main()
