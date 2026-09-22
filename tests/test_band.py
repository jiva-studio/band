import json
import shutil
import tempfile
import unittest
from pathlib import Path
from band.validator import validate_done_manifest, validate_intent_file
from band.circuit_breaker import CircuitBreaker
from band.adapters.make_tool import MakeClaimTool
from band.adapters.http_tool import HttpClaimTool
from band.adapters.hygiene_tool import HygieneClaimTool
from band.yaml_loader import load_yaml

class TestDoneHarness(unittest.TestCase):
    def test_validator_valid_manifest(self):
        valid = {
            "slug": "test-task",
            "target": "modules/libs/domain",
            "claims": [
                {"id": "c1", "kind": "make", "target": "check-package", "params": {"PKG": "@domain/auth"}},
                {"id": "c2", "kind": "mutation", "target": "@domain/auth", "mode": "diff"},
                {"id": "c3", "kind": "http", "url": "http://127.0.0.1:3000/health", "expect_status": 200},
                {"id": "c4", "kind": "critic", "runner": "auto", "checks": ["Intent check"]}
            ]
        }
        is_valid, errors = validate_done_manifest(valid)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_validator_invalid_manifest(self):
        invalid = {
            "slug": "",
            "claims": [
                {"id": "c1", "kind": "unknown-tool"}
            ]
        }
        is_valid, errors = validate_done_manifest(invalid)
        self.assertFalse(is_valid)
        self.assertTrue(len(errors) >= 2)

    def test_circuit_breaker_max_retries(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            cb = CircuitBreaker(tmp_dir, max_retries=2)
            res1 = cb.check_and_update([{"id": "c1", "message": "err1"}])
            self.assertFalse(res1["is_tripped"])
            self.assertEqual(res1["attempt"], 1)

            res2 = cb.check_and_update([{"id": "c1", "message": "err2"}])
            self.assertFalse(res2["is_tripped"])
            self.assertEqual(res2["attempt"], 2)

            res3 = cb.check_and_update([{"id": "c1", "message": "err3"}])
            self.assertTrue(res3["is_tripped"])
            self.assertTrue("maximum automated retry budget" in res3["reason"])
        finally:
            shutil.rmtree(tmp_dir)

    def test_circuit_breaker_stagnation(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            cb = CircuitBreaker(tmp_dir, max_retries=5)
            cb.check_and_update([{"id": "c1", "message": "exact same error"}])
            res2 = cb.check_and_update([{"id": "c1", "message": "exact same error"}])
            self.assertTrue(res2["is_tripped"])
            self.assertTrue("Stagnation detected" in res2["reason"])
        finally:
            shutil.rmtree(tmp_dir)

    def test_circuit_breaker_claim_id_key(self):
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            cb = CircuitBreaker(tmp_dir, max_retries=3)
            res = cb.check_and_update([{"claim_id": "c1", "kind": "make", "message": "error msg"}])
            self.assertFalse(res["is_tripped"])
            self.assertEqual(res["attempt"], 1)
        finally:
            shutil.rmtree(tmp_dir)

    def test_make_tool_validation(self):
        tool = MakeClaimTool()
        self.assertEqual(len(tool.validate({"target": "test"})), 0)
        self.assertGreater(len(tool.validate({})), 0)

    def test_http_tool_validation(self):
        tool = HttpClaimTool()
        self.assertEqual(len(tool.validate({"url": "http://localhost"})), 0)
        self.assertGreater(len(tool.validate({})), 0)

    def test_hygiene_tool_validation(self):
        tool = HygieneClaimTool()
        self.assertEqual(len(tool.validate({"no_stubs": True})), 0)

    def test_yaml_loader(self):
        yaml_content = """
slug: foo
claims:
  - id: c1
    kind: make
    target: test
"""
        res = load_yaml(yaml_content)
        self.assertEqual(res["slug"], "foo")
        self.assertEqual(len(res["claims"]), 1)

    def test_validator_invalid_pipeline(self):
        invalid = {
            "slug": "test-task",
            "pipeline": "non-existent-pipeline-xyz-12345",
            "claims": [
                {"id": "c1", "kind": "make", "target": "check-package"}
            ]
        }
        is_valid, errors = validate_done_manifest(invalid)
        self.assertFalse(is_valid)
        self.assertTrue(any("Unknown pipeline profile" in e for e in errors))

    def test_hook_payload_formatting(self):
        from band.reporters.hook_payload import format_hook_response
        results = [
            {"claim_id": "c1", "kind": "make", "passed": False, "message": "fail reason"}
        ]
        resp_json = format_hook_response(
            passed=False,
            circuit_tripped=False,
            circuit_reason="",
            results=results,
            attempt=1
        )
        data = json.loads(resp_json)
        self.assertEqual(data["decision"], "continue")
        self.assertTrue("Claim c1 (make)" in data["reason"])
        self.assertTrue("fail reason" in data["reason"])


class TestIntentValidator(unittest.TestCase):
    """Unit tests for the intent.md validator."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="intent_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_valid_intent_markdown(self):
        valid_file = Path(self.tmp_dir) / "intent.md"
        valid_file.write_text(
            "# Intent: User Authentication\n\n"
            "## 1. Problem & JTBD\nUsers need secure access.\n\n"
            "## 2. Scope & Non-Goals\nOut of scope: biometric login.\n\n"
            "## 3. Adversarial Failure Modes\nNetwork drop handled cleanly.\n\n"
            "## 4. Invariants\nTenant isolation strictly preserved.\n"
        )
        is_valid, errors = validate_intent_file(valid_file)
        self.assertTrue(is_valid, f"Expected valid intent, got errors: {errors}")

    def test_intent_technical_pollution_fails(self):
        polluted_file = Path(self.tmp_dir) / "intent.md"
        polluted_file.write_text(
            "# Intent: User Auth\n\n"
            "## 1. Problem & JTBD\nUsers need login.\n\n"
            "## 2. Scope & Non-Goals\nEdit UserAuth.vue and auth.ts DTO.\n\n"
            "## 3. Adversarial Failure Modes\nNone\n\n"
            "## 4. Invariants\nGET /api/v1/auth\n"
        )
        is_valid, errors = validate_intent_file(polluted_file)
        self.assertFalse(is_valid)
        self.assertTrue(any("Technical pollution" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
