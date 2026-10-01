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
from band.doctor import run_doctor, format_doctor_report, check_interpreter, check_claude_link
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
        claude = self.test_dir / ".claude"
        self.assertTrue(claude.is_symlink())
        self.assertEqual(os.readlink(claude), ".agents")
        self.assertTrue((self.test_dir / ".agents" / "settings.json").is_file())
        settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
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
        self.assertTrue(claude_dir.is_symlink())
        merged = json.loads((self.test_dir / ".agents" / "settings.json").read_text(encoding="utf-8"))
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
        self.assertFalse(claude_dir.is_symlink())  # unsafe migration -> left alone
        self.assertEqual((claude_dir / "settings.json").read_text(encoding="utf-8"), "{ not json")
        self.assertTrue(any(a.startswith("SKIPPED migrating .claude/") and "not valid JSON" in a for a in res["actions_taken"]))

    def test_setup_does_not_clobber_invalid_agents_settings(self):
        (self.test_dir / ".agents").mkdir()
        (self.test_dir / ".agents" / "settings.json").write_text("[1,", encoding="utf-8")
        res = setup_project(self.test_dir)
        self.assertEqual((self.test_dir / ".agents" / "settings.json").read_text(encoding="utf-8"), "[1,")
        self.assertTrue(any(a.startswith("SKIPPED .agents/settings.json") for a in res["actions_taken"]))

    def test_migrates_existing_claude_directory(self):
        claude = self.test_dir / ".claude"
        (claude / "skills" / "deploy").mkdir(parents=True)
        (claude / "skills" / "deploy" / "SKILL.md").write_text("deploy skill", encoding="utf-8")
        (claude / "agents").mkdir()
        (claude / "agents" / "reviewer.md").write_text("reviewer", encoding="utf-8")
        (claude / "commands").mkdir()
        (claude / "commands" / "ship.md").write_text("ship", encoding="utf-8")
        (claude / "settings.local.json").write_text('{"env": {"LOCAL": "1"}}', encoding="utf-8")
        (claude / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(make)"]}}), encoding="utf-8")
        agents = self.test_dir / ".agents"
        (agents / "skills" / "band").mkdir(parents=True)
        (agents / "skills" / "band" / "SKILL.md").write_text("band skill", encoding="utf-8")
        (agents / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "env": {"A": "1"}}), encoding="utf-8")

        res = setup_project(self.test_dir)

        self.assertTrue(claude.is_symlink(), res["actions_taken"])
        self.assertEqual((agents / "skills" / "deploy" / "SKILL.md").read_text(encoding="utf-8"), "deploy skill")
        self.assertEqual((agents / "skills" / "band" / "SKILL.md").read_text(encoding="utf-8"), "band skill")
        self.assertEqual((agents / "agents" / "reviewer.md").read_text(encoding="utf-8"), "reviewer")
        self.assertEqual((agents / "commands" / "ship.md").read_text(encoding="utf-8"), "ship")
        self.assertTrue((agents / "settings.local.json").is_file())
        settings = json.loads((agents / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls)", "Bash(make)"])
        self.assertEqual(settings["env"], {"A": "1"})
        self.assertEqual(claude_settings_has_band_hooks(settings), {"PreToolUse": True, "Stop": True})
        # Claude Code sees everything through the link
        self.assertTrue((claude / "skills" / "deploy" / "SKILL.md").is_file())
        self.assertTrue((claude / "skills" / "band" / "SKILL.md").is_file())
        gitignore = (agents / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("settings.local.json", gitignore)
        self.assertIn("worktrees/", gitignore)

        # Idempotent
        self.assertEqual(setup_project(self.test_dir)["actions_taken"], [])

    def test_migration_conflict_leaves_everything_untouched(self):
        claude = self.test_dir / ".claude"
        (claude / "skills" / "band").mkdir(parents=True)
        (claude / "skills" / "band" / "SKILL.md").write_text("user's own band skill", encoding="utf-8")
        (claude / "skills" / "other").mkdir()
        (claude / "skills" / "other" / "SKILL.md").write_text("other", encoding="utf-8")
        (claude / "settings.json").write_text(json.dumps({"model": "opus"}), encoding="utf-8")
        agents = self.test_dir / ".agents"
        (agents / "skills" / "band").mkdir(parents=True)
        (agents / "skills" / "band" / "SKILL.md").write_text("band skill", encoding="utf-8")
        (agents / "settings.json").write_text(json.dumps({"model": "sonnet"}), encoding="utf-8")

        res = setup_project(self.test_dir)

        skipped = [a for a in res["actions_taken"] if a.startswith("SKIPPED migrating .claude/")]
        self.assertEqual(len(skipped), 1, res["actions_taken"])
        self.assertIn(".claude/skills/band conflicts", skipped[0])
        self.assertIn("'model' differs", skipped[0])
        self.assertTrue(claude.is_dir() and not claude.is_symlink())
        self.assertTrue((claude / "skills" / "other" / "SKILL.md").is_file())  # nothing moved
        self.assertFalse((agents / "skills" / "other").exists())
        self.assertEqual(json.loads((claude / "settings.json").read_text(encoding="utf-8")), {"model": "opus"})
        link = check_claude_link(self.test_dir)
        self.assertEqual(link["status"], "WARN")
        self.assertFalse(run_doctor(self.test_dir)["ready"])

    def test_migrates_previous_band_layout_with_skill_symlinks(self):
        # Layout written by earlier band versions: real .claude/ with per-skill symlinks into .agents/skills
        agents = self.test_dir / ".agents"
        (agents / "skills" / "band").mkdir(parents=True)
        (agents / "skills" / "band" / "SKILL.md").write_text("band skill", encoding="utf-8")
        claude = self.test_dir / ".claude"
        (claude / "skills").mkdir(parents=True)
        (claude / "skills" / "band").symlink_to(Path("..") / ".." / ".agents" / "skills" / "band")
        (claude / "settings.json").write_text(json.dumps(merge_claude_settings({})), encoding="utf-8")

        res = setup_project(self.test_dir)
        self.assertTrue(claude.is_symlink(), res["actions_taken"])
        self.assertEqual((agents / "skills" / "band" / "SKILL.md").read_text(encoding="utf-8"), "band skill")
        settings = json.loads((agents / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(settings["hooks"]["PreToolUse"]), 1)

    def test_foreign_claude_symlink_is_reported(self):
        other = self.test_dir / "elsewhere"
        other.mkdir()
        (self.test_dir / ".claude").symlink_to("elsewhere")
        res = setup_project(self.test_dir)
        self.assertTrue(any(a.startswith("SKIPPED .claude -> .agents") for a in res["actions_taken"]))
        self.assertEqual(os.readlink(self.test_dir / ".claude"), "elsewhere")
        self.assertEqual(check_claude_link(self.test_dir)["status"], "FAIL")

    def test_doctor_claude_link_check(self):
        self.assertEqual(check_claude_link(self.test_dir)["status"], "WARN")  # missing
        setup_project(self.test_dir)
        self.assertEqual(check_claude_link(self.test_dir)["status"], "OK")

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
