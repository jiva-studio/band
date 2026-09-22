import tempfile
import shutil
import unittest
from pathlib import Path
from done.pipeline_runner import PipelineRunner
from done.pipeline_loader import load_pipeline_config

class TestPipelineRunner(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.spec_file = self.tmp_dir / "done.yaml"
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
