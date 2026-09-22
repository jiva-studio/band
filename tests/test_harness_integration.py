"""Integration and self-tests for the Band Agent Harness and FSM State Machine."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestBandHarnessIntegration(unittest.TestCase):
    """Integration test suite exercising the Band harness end-to-end."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="band_test_")
        self.agents_dir = Path(self.test_dir) / ".agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)

        repo_root = Path(__file__).parent.parent
        # Copy core modules to .agents/
        shutil.copytree(repo_root / "band", self.agents_dir / "band")
        shutil.copytree(repo_root / "pipelines", self.agents_dir / "pipelines")
        shutil.copytree(repo_root / "skills", self.agents_dir / "skills")
        shutil.copy(repo_root / "hooks.json", self.agents_dir / "hooks.json")

        # Initialize a temporary git repo to test git operations
        subprocess.run(["git", "init", "-b", "main"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@band.ai"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Band Test"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=self.test_dir, check=True, capture_output=True)

        # Create a sample task spec
        self.task_dir = self.agents_dir / "tasks" / "test-feature"
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.spec_file = self.task_dir / "done.yaml"
        self.spec_file.write_text(
            "slug: test-feature\n"
            "pipeline: fast\n"
            "claims:\n"
            "  - id: l1-hygiene\n"
            "    kind: hygiene\n"
            "    no_stubs: true\n"
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run_band(self, args, env=None):
        cmd = ["python3", "-m", "band"] + args
        current_env = os.environ.copy()
        current_env["PYTHONPATH"] = str(self.agents_dir)
        if env:
            current_env.update(env)
        return subprocess.run(
            cmd,
            cwd=self.test_dir,
            env=current_env,
            capture_output=True,
            text=True,
        )

    def test_pipeline_lifecycle_and_state(self):
        """Verify pipeline initialization, state inspection, and advancement."""
        # 1. Start pipeline
        res = self._run_band(["--start-pipeline", str(self.spec_file)])
        self.assertEqual(res.returncode, 0, f"Failed to start pipeline: {res.stderr}")
        self.assertIn("INITIALIZED", res.stdout)

        # 2. Check state via --status
        res = self._run_band(["--status", str(self.spec_file)])
        self.assertEqual(res.returncode, 0, f"Status failed: {res.stderr}")
        self.assertIn("Task: test-feature", res.stdout)
        self.assertIn("Pipeline: fast", res.stdout)
        self.assertIn("Current Stage: implementation", res.stdout)

    def test_stop_hook_blocking_behavior(self):
        """Verify that the Stop hook blocks until the active stage satisfies its claims."""
        # Start pipeline
        self._run_band(["--start-pipeline", str(self.spec_file)])

        # Query hook without passing claims
        res = self._run_band(["--hook"])
        self.assertEqual(res.returncode, 0)
        hook_payload = json.loads(res.stdout)
        self.assertEqual(hook_payload["decision"], "continue")
        self.assertIn("reason", hook_payload)

    def test_spec_claims_verification(self):
        """Verify direct claims verification against a done.yaml spec."""
        res = self._run_band(["--spec", str(self.spec_file)])
        self.assertEqual(res.returncode, 0, f"Claims verification failed: {res.stderr}")
        self.assertIn("VERIFIED COMPLETED", res.stdout)


if __name__ == "__main__":
    unittest.main()
