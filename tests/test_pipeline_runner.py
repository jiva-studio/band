import tempfile
import shutil
import unittest
from pathlib import Path
from band.pipeline_runner import PipelineRunner
from band.pipeline_loader import load_pipeline_config

class TestPipelineRunner(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.spec_file = self.tmp_dir / "band.yaml"
        self.spec_file.write_text("""
slug: test-pipeline-task
pipeline: standard
target: "modules/libs/test"
claims:
  - id: l1-check
    kind: critic
    checks:
      - "test check"
""", encoding="utf-8")
        self.runner = PipelineRunner(self.spec_file)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_init_pipeline(self):
        state = self.runner.init_pipeline()
        self.assertEqual(state["slug"], "test-pipeline-task")
        self.assertEqual(state["pipeline"], "standard")
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(state["current_stage_idx"], 0)
        self.assertEqual(state["current_stage_id"], "red-phase")

        # Verify state.json was written
        state2 = self.runner.read_state()
        self.assertEqual(state2["slug"], "test-pipeline-task")

    def test_evaluate_and_advance_blocks_if_no_tests(self):
        self.runner.init_pipeline()
        res = self.runner.evaluate_and_advance(is_hook=True)
        self.assertEqual(res.get("decision"), "continue")
        self.assertTrue("red-phase" in res.get("reason", ""))

if __name__ == "__main__":
    unittest.main()

    def test_stage_allow_file_boundary(self):
        stage = {"id": "red-phase", "allow": ["tests/**", "**/*.spec.ts"]}
        # Only test file touched
        violations = self.runner._check_stage_file_boundaries(stage, ["tests/user.spec.ts"], [])
        self.assertEqual(len(violations), 0)

        # Implementation file touched outside allow list
        violations = self.runner._check_stage_file_boundaries(stage, ["src/user.ts"], [])
        self.assertEqual(len(violations), 1)
        self.assertTrue("Disallowed modification" in violations[0])

    def test_stage_deny_file_boundary(self):
        stage = {"id": "green-phase", "deny": ["tests/**", "**/*.spec.ts"]}
        # Implementation file touched -> passes
        violations = self.runner._check_stage_file_boundaries(stage, ["src/user.ts"], [])
        self.assertEqual(len(violations), 0)

        # Test file touched -> blocked
        violations = self.runner._check_stage_file_boundaries(stage, ["tests/user.spec.ts"], [])
        self.assertEqual(len(violations), 1)
        self.assertTrue("Denied modification" in violations[0])

    def test_stage_allow_and_deny_combined(self):
        stage = {"id": "custom", "allow": ["src/**"], "deny": ["src/secret/**"]}
        # src/user.ts -> passes
        self.assertEqual(len(self.runner._check_stage_file_boundaries(stage, ["src/user.ts"], [])), 0)
        # src/secret/keys.ts -> denied
        self.assertEqual(len(self.runner._check_stage_file_boundaries(stage, ["src/secret/keys.ts"], [])), 1)
        # docs/readme.md -> disallowed (not in allow)
        self.assertEqual(len(self.runner._check_stage_file_boundaries(stage, ["docs/readme.md"], [])), 1)
