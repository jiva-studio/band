import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from band.setup import detect_project_stack, setup_project
from band.doctor import run_doctor, format_doctor_report


class TestBandSetupAndDoctor(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="band_setup_test_"))
        subprocess.run(["git", "init", "-b", "main"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@band.ai"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Band Test"], cwd=self.test_dir, check=True, capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_detect_node_ts_stack(self):
        (self.test_dir / "package.json").write_text(json.dumps({
            "name": "test-app",
            "devDependencies": {"vitest": "^1.0.0"}
        }), encoding="utf-8")
        (self.test_dir / "tsconfig.json").write_text("{}", encoding="utf-8")
        (self.test_dir / ".env.local").write_text("SECRET=1", encoding="utf-8")

        stack = detect_project_stack(self.test_dir)
        self.assertEqual(stack["language"], "typescript")
        self.assertIn("package.json", stack["config_files"])
        self.assertIn(".env.local", stack["env_files"])

    def test_setup_project_and_doctor_report(self):
        (self.test_dir / "Makefile").write_text("check-package:\n\t@echo ok\nmutate-diff:\n\t@echo ok\nsetup:\n\t@echo ok\n", encoding="utf-8")
        (self.test_dir / "package.json").write_text(json.dumps({"name": "test-app"}), encoding="utf-8")
        (self.test_dir / "tsconfig.json").write_text("{}", encoding="utf-8")

        res = setup_project(self.test_dir)
        self.assertTrue(len(res["actions_taken"]) > 0)
        self.assertTrue((self.test_dir / ".worktreeinclude").exists())
        self.assertTrue((self.test_dir / ".agents" / "hooks.json").exists())

        # Run doctor on setup repo
        diag = run_doctor(self.test_dir)
        self.assertTrue(diag["ready"])
        report = format_doctor_report(diag)
        self.assertIn("100% READY", report)
        self.assertIn("Typescript", report)

    def test_detect_python_stack(self):
        (self.test_dir / "pyproject.toml").write_text("[project]\nname = 'py-app'\n", encoding="utf-8")

        stack = detect_project_stack(self.test_dir)
        self.assertEqual(stack["language"], "python")
        self.assertIn("pyproject.toml", stack["config_files"])


if __name__ == "__main__":
    unittest.main()
