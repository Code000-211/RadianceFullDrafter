"""Unit and integration test suite for parity_check.py pre-benchmark gate."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Load parity_check module dynamically from scripts/
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
PARITY_SCRIPT = SCRIPTS_DIR / "parity_check.py"

spec = importlib.util.spec_from_file_location("parity_check", PARITY_SCRIPT)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load {PARITY_SCRIPT}")
parity_check = importlib.util.module_from_spec(spec)
sys.modules["parity_check"] = parity_check
spec.loader.exec_module(parity_check)

TestCase = parity_check.TestCase
evaluate_test = parity_check.evaluate_test
load_test_cases = parity_check.load_test_cases
check_server_health = parity_check.check_server_health
run_single_prompt = parity_check.run_single_prompt
normalize_endpoint = parity_check.normalize_endpoint


class TestEndpointNormalization(unittest.TestCase):
    def test_various_endpoint_formats(self) -> None:
        self.assertEqual(normalize_endpoint("http://localhost:8000"), "http://localhost:8000/v1")
        self.assertEqual(normalize_endpoint("http://localhost:8000/"), "http://localhost:8000/v1")
        self.assertEqual(normalize_endpoint("http://localhost:8000/v1"), "http://localhost:8000/v1")
        self.assertEqual(normalize_endpoint("http://localhost:8000/v1/"), "http://localhost:8000/v1")
        self.assertEqual(
            normalize_endpoint("http://localhost:8000/v1/chat/completions"),
            "http://localhost:8000/v1",
        )
        self.assertEqual(
            normalize_endpoint("http://localhost:8000/v1/models"),
            "http://localhost:8000/v1",
        )


class TestParityEvaluator(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_case = TestCase(
            id="test_case_1",
            category="math",
            prompt="2+2",
            max_tokens=16,
            temperature=0.0,
            golden_tokens=2,
            golden_sha256="4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
            expected_finish_reason="stop",
            golden_text="4",
            required_patterns=["4"],
            forbidden_patterns=["error", "<|im_start|>"],
        )

    def test_exact_match_passes(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="4",
            tokens=2,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=0,
        )
        self.assertTrue(res.passed)
        self.assertEqual(res.divergence_reason, [])
        self.assertEqual(res.diff, "")

    def test_divergent_content_fails_with_diff(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="5",
            tokens=2,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=0,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("SHA256 divergence" in r for r in res.divergence_reason))
        self.assertTrue(any("Missing required semantic pattern" in r for r in res.divergence_reason))
        self.assertIn("-4", res.diff)
        self.assertIn("+5", res.diff)
        # Verify lines are not concatenated into e.g. -4+5
        self.assertNotIn("-4+5", res.diff)

    def test_golden_text_without_sha256_fails_on_divergence(self) -> None:
        case = TestCase(
            id="test_no_sha",
            category="math",
            prompt="2+2",
            max_tokens=16,
            golden_tokens=0,
            golden_sha256="",
            golden_text="4",
            expected_finish_reason="stop",
        )
        res = evaluate_test(
            case,
            content="5",
            tokens=2,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=0,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("SHA256 divergence" in r for r in res.divergence_reason))

    def test_premature_finish_reason_fails(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="4",
            tokens=2,
            finish_reason="length",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=0,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("Premature/abnormal finish reason" in r for r in res.divergence_reason))

    def test_token_count_mismatch_fails_strict(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="4",
            tokens=3,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=0,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("Token count mismatch" in r for r in res.divergence_reason))

    def test_token_tolerance_relaxed_semantic_match(self) -> None:
        # Candidate has slightly different whitespace/content and 3 tokens instead of 2,
        # but required pattern "4" is present and token_tolerance=1 allows delta 1.
        res = evaluate_test(
            self.sample_case,
            content="4 ",
            tokens=3,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=1,
        )
        self.assertTrue(res.passed)

    def test_token_tolerance_exceeded_fails(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="4 ",
            tokens=5,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=1,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("Token count mismatch" in r for r in res.divergence_reason))

    def test_token_tolerance_missing_pattern_fails(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="five",
            tokens=2,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=2,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("Missing required semantic pattern" in r for r in res.divergence_reason))

    def test_forbidden_pattern_detected(self) -> None:
        res = evaluate_test(
            self.sample_case,
            content="4 <|im_start|>",
            tokens=5,
            finish_reason="stop",
            ttft_ms=10.0,
            total_ms=20.0,
            decode_tps=100.0,
            token_tolerance=5,
        )
        self.assertFalse(res.passed)
        self.assertTrue(any("Found forbidden hallucination" in r for r in res.divergence_reason))


class TestGoldenDataLoader(unittest.TestCase):
    def test_load_default_cases(self) -> None:
        cases = load_test_cases(None)
        self.assertGreaterEqual(len(cases), 4)
        ids = {c.id for c in cases}
        self.assertIn("sanity_arithmetic", ids)
        self.assertIn("code_is_prime", ids)
        self.assertIn("math_linear_eq", ids)
        self.assertIn("reasoning_probability", ids)

    def test_load_custom_json(self) -> None:
        custom_data = [
            {
                "id": "custom_1",
                "category": "unit",
                "prompt": "hello",
                "max_tokens": 10,
                "golden_tokens": 1,
                "golden_sha256": "abc",
                "expected_finish_reason": "stop",
                "golden_text": "world",
                "required_patterns": ["world"],
                "forbidden_patterns": [],
            }
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(custom_data, f)
            temp_path = Path(f.name)

        try:
            cases = load_test_cases(temp_path)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].id, "custom_1")
            self.assertEqual(cases[0].prompt, "hello")
        finally:
            temp_path.unlink()

    def test_load_missing_file_raises_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_test_cases(Path("/tmp/non_existent_golden_file_xyz123.json"))

    def test_load_custom_json_derives_sha256(self) -> None:
        custom_data = [
            {
                "id": "custom_no_sha",
                "category": "unit",
                "prompt": "hello",
                "golden_text": "world",
            }
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(custom_data, f)
            temp_path = Path(f.name)

        try:
            cases = load_test_cases(temp_path)
            self.assertEqual(len(cases), 1)
            # SHA-256 for "world"
            self.assertEqual(
                cases[0].golden_sha256,
                "486ea46224d1bb4fb680f34f7c9ad96a8f24ec88be73ea8e5a6c65260e9cb8a7",
            )
        finally:
            temp_path.unlink()


class TestLiveEngineParity(unittest.TestCase):
    def test_running_engine_sanity(self) -> None:
        endpoint = "http://localhost:8000/v1"
        if not check_server_health(endpoint, timeout=2.0):
            self.skipTest("Engine server on port 8000 is not online")

        cases = load_test_cases(None)
        sanity_case = next(c for c in cases if c.id == "sanity_arithmetic")
        content, tokens, finish_reason, ttft_ms, total_ms, decode_tps = run_single_prompt(
            endpoint, "qwen4exp", sanity_case, timeout=10.0
        )
        res = evaluate_test(
            sanity_case,
            content,
            tokens,
            finish_reason,
            ttft_ms,
            total_ms,
            decode_tps,
        )
        self.assertTrue(res.passed, f"Live engine sanity check failed: {res.divergence_reason}")
        self.assertEqual(content.strip(), "4")
        self.assertEqual(finish_reason, "stop")

    def test_running_engine_endpoint_variants(self) -> None:
        # Test without /v1
        endpoint = "http://localhost:8000"
        if not check_server_health(endpoint, timeout=2.0):
            self.skipTest("Engine server on port 8000 is not online")

        cases = load_test_cases(None)
        sanity_case = next(c for c in cases if c.id == "sanity_arithmetic")
        content, *_ = run_single_prompt(
            endpoint, "qwen4exp", sanity_case, timeout=10.0
        )
        self.assertEqual(content.strip(), "4")


if __name__ == "__main__":
    unittest.main()
