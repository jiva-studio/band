import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from band.worktree import create_worktree, merge_worktree, remove_worktree, copy_worktree_includes
from band.pipeline_runner import PipelineRunner


class TestBandWorktree(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="band_wt_test_"))
        subprocess.run(["git", "init", "-b", "main"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@band.ai"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Band Test"], cwd=self.test_dir, check=True, capture_output=True)

        # Create a dummy file and commit
        (self.test_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        (self.test_dir / ".worktreeinclude").write_text(".env.local\nconfig/secrets.json\n", encoding="utf-8")
        (self.test_dir / ".env.local").write_text("SECRET=123\n", encoding="utf-8")
        (self.test_dir / "config").mkdir(parents=True, exist_ok=True)
        (self.test_dir / "config" / "secrets.json").write_text('{"key": "val"}', encoding="utf-8")

        # Create intent file in main
        intent_dir = self.test_dir / ".agents" / "tasks" / "user-auth"
        intent_dir.mkdir(parents=True, exist_ok=True)
        (intent_dir / "intent.md").write_text("# Intent: User Auth\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=self.test_dir, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_worktree_and_includes(self):
        ok, wt_path, msg = create_worktree("auth-api", intent_slug="user-auth", repo_root=self.test_dir)
        self.assertTrue(ok)
        self.assertTrue(wt_path.exists())

        # Check that intent was copied
        task_intent = wt_path / ".agents" / "tasks" / "auth-api" / "intent.md"
        self.assertTrue(task_intent.exists())
        self.assertIn("User Auth", task_intent.read_text(encoding="utf-8"))

        # Check that .worktreeinclude files were copied
        self.assertTrue((wt_path / ".env.local").exists())
        self.assertEqual((wt_path / ".env.local").read_text(encoding="utf-8"), "SECRET=123\n")
        self.assertTrue((wt_path / "config" / "secrets.json").exists())

    def test_worktree_pause_and_resume_lifecycle(self):
        ok, wt_path, _ = create_worktree("auth-fe", intent_slug="user-auth", repo_root=self.test_dir)
        self.assertTrue(ok)

        spec_file = wt_path / ".agents" / "tasks" / "auth-fe" / "done.yaml"
        spec_file.write_text(
            "slug: auth-fe\npipeline: standard\nclaims:\n  - id: l1\n    tool: make\n    target: check\n"
        )

        runner = PipelineRunner(spec_file)
        runner.init_pipeline("standard")

        # Test pause
        res = runner.pause_pipeline()
        self.assertEqual(res["status"], "paused")

        eval_res = runner.evaluate_and_advance(is_hook=True)
        self.assertEqual(eval_res["decision"], "allow")
        self.assertIn("paused", eval_res["message"])

        # Test resume
        res = runner.resume_pipeline()
        self.assertEqual(res["status"], "in_progress")

    def test_cleanup_and_merge(self):
        ok, wt_path, _ = create_worktree("feature-x", intent_slug="user-auth", repo_root=self.test_dir)
        self.assertTrue(ok)

        # Make a commit in worktree
        (wt_path / "feature.txt").write_text("new feature", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "feat: done"], cwd=wt_path, check=True)

        # Merge
        ok, msg = merge_worktree("feature-x", target_branch="main", repo_root=self.test_dir)
        self.assertTrue(ok, msg)
        self.assertTrue((self.test_dir / "feature.txt").exists())

        # Cleanup
        ok, msg = remove_worktree("feature-x", delete_branch=True, repo_root=self.test_dir)
        self.assertTrue(ok)
        self.assertFalse(wt_path.exists())


if __name__ == "__main__":
    unittest.main()
