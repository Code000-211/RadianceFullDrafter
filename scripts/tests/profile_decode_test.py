"""Tests for the trace analysis in scripts/profile_decode.py on a synthetic rocprofv3 CSV.

Run: python3 -m unittest scripts/tests/profile_decode_test.py
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
spec = importlib.util.spec_from_file_location("profile_decode", SCRIPTS_DIR / "profile_decode.py")
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
        md = pd.render({"commit": "abc", "build_dir": "b", "date": "d", "levels": [
            {"streams": 1, "untraced": {"decode_tps": 50.0}, "untraced_ms_per_step": 0.12, "overhead_us": 1.0,
             "analysis": a, "warnings": ["gaps.sh rc=1"]}]})
        self.assertIn("| `small_op` | `gemm_w4a8<true,1u>` |", md)
        self.assertIn("**Warnung:** gaps.sh rc=1", md)


if __name__ == "__main__":
    unittest.main()
