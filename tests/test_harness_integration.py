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
        shutil.copytree(repo_root / "bin", self.agents_dir / "bin")
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

    def _run_band(self, args, env=None, stdin=None):
        # Go through the launcher exactly like the generated hooks do: it must find
        # .agents/band without PYTHONPATH and without python3 necessarily on PATH.
        cmd = ["sh", str(self.agents_dir / "bin" / "band")] + args
        current_env = os.environ.copy()
        current_env.pop("PYTHONPATH", None)
        if env:
            current_env.update(env)
        return subprocess.run(
            cmd,
            cwd=self.test_dir,
            env=current_env,
            input=stdin if stdin is not None else "",
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

    def test_stop_hook_claude_code_blocks_with_exit_2(self):
        """Claude Code Stop hook: blocking = exit 2 + reason on stderr + hookSpecificOutput JSON."""
        self._run_band(["--start-pipeline", str(self.spec_file)])
        event = json.dumps({"session_id": "s", "hook_event_name": "Stop", "stop_hook_active": False, "cwd": self.test_dir})
        res = self._run_band(["--hook", "--harness", "claude-code"], stdin=event)
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("Stage [implementation]", res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertEqual(out["hookSpecificOutput"]["decision"], "continue")
        self.assertIn("Stage [implementation]", out["hookSpecificOutput"]["reason"])

    def test_stop_hook_claude_code_allows_when_no_active_pipeline(self):
        event = json.dumps({"session_id": "s", "hook_event_name": "Stop", "stop_hook_active": False})
        res = self._run_band(["--hook", "--harness", "claude-code"], stdin=event)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_guard_claude_code_payload_via_launcher(self):
        deny_event = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(self.task_dir / "state.json"), "content": "{}"},
        })
        res = self._run_band(["--guard", "--harness", "claude-code"], stdin=deny_event)
        self.assertEqual(res.returncode, 2)
        out = json.loads(res.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("decision", out)

        allow_event = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        })
        res = self._run_band(["--guard"], stdin=allow_event)  # auto-detects Claude Code
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "")

    def test_init_writes_claude_settings_and_links_skills(self):
        res = self._run_band(["--init"])
        self.assertEqual(res.returncode, 0, res.stderr)
        settings = json.loads((Path(self.test_dir) / ".claude" / "settings.json").read_text())
        self.assertIn("--guard --harness claude-code", settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertIn("--hook --harness claude-code", settings["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertTrue((Path(self.test_dir) / ".claude" / "skills" / "band" / "SKILL.md").exists())

    def test_spec_claims_verification(self):
        """Verify direct claims verification against a done.yaml spec."""
        res = self._run_band(["--spec", str(self.spec_file)])
        self.assertEqual(res.returncode, 0, f"Claims verification failed: {res.stderr}")
        self.assertIn("VERIFIED COMPLETED", res.stdout)


if __name__ == "__main__":
    unittest.main()
