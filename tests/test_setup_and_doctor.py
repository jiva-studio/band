import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from band.setup import (
    detect_project_stack,
    setup_project,
    merge_claude_settings,
    claude_settings_has_band_hooks,
)
from band.doctor import run_doctor, format_doctor_report, check_interpreter
from band.launcher import LAUNCHER_SCRIPT, CLAUDE_GUARD_MATCHER


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


    def test_setup_writes_launcher_and_claude_settings(self):
        res = setup_project(self.test_dir)
        launcher = self.test_dir / ".agents" / "bin" / "band"
        self.assertEqual(launcher.read_text(encoding="utf-8"), LAUNCHER_SCRIPT)
        settings = json.loads((self.test_dir / ".claude" / "settings.json").read_text(encoding="utf-8"))
        pre = settings["hooks"]["PreToolUse"]
        self.assertEqual(len(pre), 1)
        self.assertEqual(pre[0]["matcher"], CLAUDE_GUARD_MATCHER)
        self.assertEqual(pre[0]["hooks"][0]["type"], "command")
        self.assertIn("${CLAUDE_PROJECT_DIR}/.agents/bin/band", pre[0]["hooks"][0]["command"])
        stop = settings["hooks"]["Stop"]
        self.assertNotIn("matcher", stop[0])
        self.assertIn("--hook --harness claude-code", stop[0]["hooks"][0]["command"])
        legacy = json.loads((self.test_dir / ".agents" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(legacy["deterministic-done-gate"]["PreToolUse"][0]["command"], "sh .agents/bin/band --guard")
        self.assertTrue(any("settings.json" in a for a in res["actions_taken"]))

        # Idempotent: second run changes nothing
        res2 = setup_project(self.test_dir)
        self.assertEqual(res2["actions_taken"], [])

    def test_setup_merges_existing_claude_settings(self):
        claude_dir = self.test_dir / ".claude"
        claude_dir.mkdir()
        existing = {
            "permissions": {"allow": ["Bash(npm test)"]},
            "env": {"FOO": "1"},
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "./lint-bash.sh"}]},
                    # stale Band entry from an older install, mixed with a user hook
                    {"matcher": "Edit|Write", "hooks": [
                        {"type": "command", "command": "python3 -m band --guard"},
                        {"type": "command", "command": "./keep-me.sh"},
                    ]},
                ],
                "PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "./fmt.sh"}]}],
            },
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing), encoding="utf-8")

        setup_project(self.test_dir)
        merged = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(merged["permissions"], existing["permissions"])
        self.assertEqual(merged["env"], existing["env"])
        self.assertEqual(merged["hooks"]["PostToolUse"], existing["hooks"]["PostToolUse"])
        commands = [h["command"] for g in merged["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertIn("./lint-bash.sh", commands)
        self.assertIn("./keep-me.sh", commands)
        self.assertNotIn("python3 -m band --guard", commands)
        self.assertEqual(sum(1 for c in commands if ".agents/bin/band" in c), 1)
        self.assertEqual(claude_settings_has_band_hooks(merged), {"PreToolUse": True, "Stop": True})

    def test_merge_is_idempotent_and_pure(self):
        original = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "./notify.sh"}]}]}}
        once = merge_claude_settings(original)
        twice = merge_claude_settings(once)
        self.assertEqual(once, twice)
        self.assertEqual(original, {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "./notify.sh"}]}]}})
        self.assertEqual(len(once["hooks"]["Stop"]), 2)

    def test_setup_does_not_clobber_invalid_settings(self):
        claude_dir = self.test_dir / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{ not json", encoding="utf-8")
        res = setup_project(self.test_dir)
        self.assertEqual((claude_dir / "settings.json").read_text(encoding="utf-8"), "{ not json")
        self.assertTrue(any(a.startswith("SKIPPED .claude/settings.json") for a in res["actions_taken"]))

    def test_doctor_interpreter_check(self):
        diag = check_interpreter(self.test_dir)
        self.assertEqual(diag["status"], "WARN")  # launcher not written yet
        setup_project(self.test_dir)
        self.assertEqual(check_interpreter(self.test_dir)["status"], "OK")

    def test_repo_launcher_matches_generated_launcher(self):
        repo_launcher = Path(__file__).resolve().parent.parent / "bin" / "band"
        self.assertEqual(repo_launcher.read_text(encoding="utf-8"), LAUNCHER_SCRIPT)


if __name__ == "__main__":
    unittest.main()
