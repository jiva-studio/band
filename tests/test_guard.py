import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from band.guard import is_path_protected, is_command_dangerous, evaluate_tool_call
from band.hook_io import detect_harness, guard_response, stop_response


class TestBandGuard(unittest.TestCase):
    def test_is_path_protected(self):
        # Protected files
        self.assertTrue(is_path_protected("artifacts/state.json"))
        self.assertTrue(is_path_protected(".agents/tasks/feat-media/artifacts/state.json"))
        self.assertTrue(is_path_protected("/home/user/project/.agents/tasks/feat-media/artifacts/state.json"))
        self.assertTrue(is_path_protected(".agents/pipelines/hardened.yaml"))
        self.assertTrue(is_path_protected(".agents/band/pipeline_runner.py"))
        self.assertTrue(is_path_protected("pipelines/standard.yaml"))

        # Unprotected files
        self.assertFalse(is_path_protected("src/components/Button.vue"))
        self.assertFalse(is_path_protected("modules/apps/admin/src/pages/schools/ui/SchoolLogoField.vue"))
        self.assertFalse(is_path_protected("modules/services/api/src/user.service.ts"))
        self.assertFalse(is_path_protected("README.md"))
        self.assertFalse(is_path_protected("package.json"))

    def test_is_command_dangerous(self):
        # Dangerous commands
        dang, _ = is_command_dangerous("echo '{\"status\":\"ok\"}' > .agents/tasks/feat/artifacts/state.json")
        self.assertTrue(dang)

        dang, _ = is_command_dangerous("cat <<EOF > state.json\n{}")
        self.assertTrue(dang)

        dang, _ = is_command_dangerous("sed -i 's/red/green/' state.json")
        self.assertTrue(dang)

        dang, _ = is_command_dangerous("rm -f .agents/tasks/feat/artifacts/state.json")
        self.assertTrue(dang)

        # Safe commands
        dang, _ = is_command_dangerous("python3 -m band --status")
        self.assertFalse(dang)

        dang, _ = is_command_dangerous("npm test")
        self.assertFalse(dang)

        dang, _ = is_command_dangerous("git status")
        self.assertFalse(dang)

    def test_evaluate_tool_call_file_edits(self):
        # Disallow state.json edits
        allowed, reason = evaluate_tool_call({
            "tool_name": "Edit",
            "tool_input": {
                "target_file": ".agents/tasks/feat-auth/artifacts/state.json"
            }
        })
        self.assertFalse(allowed)
        self.assertIn("Direct editing of protected path", reason)

        # Disallow write_to_file on pipelines
        allowed, reason = evaluate_tool_call({
            "tool_name": "write_to_file",
            "tool_input": {
                "TargetFile": "/workspace/.agents/pipelines/hardened.yaml"
            }
        })
        self.assertFalse(allowed)

        # Allow normal project file edits
        allowed, reason = evaluate_tool_call({
            "tool_name": "replace_file_content",
            "tool_input": {
                "TargetFile": "/workspace/modules/apps/admin/src/App.vue"
            }
        })
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_evaluate_tool_call_commands(self):
        # Disallow tampering commands
        allowed, reason = evaluate_tool_call({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 -c 'open(\"state.json\",\"w\").write(\"{}\")'"
            }
        })
        self.assertFalse(allowed)

        # Allow normal test commands
        allowed, reason = evaluate_tool_call({
            "tool_name": "run_command",
            "tool_input": {
                "CommandLine": "npm run test"
            }
        })
        self.assertTrue(allowed)


    def test_claude_code_payloads(self):
        base = {"session_id": "s", "cwd": "/repo", "hook_event_name": "PreToolUse", "tool_use_id": "t"}

        # Write / Edit / MultiEdit carry tool_input.file_path (absolute)
        for tool in ("Write", "Edit", "MultiEdit"):
            allowed, reason = evaluate_tool_call(dict(base, tool_name=tool, tool_input={
                "file_path": "/repo/.agents/tasks/feat/state.json", "content": "{}"}))
            self.assertFalse(allowed, tool)
            self.assertIn("protected path", reason)

        # NotebookEdit carries tool_input.notebook_path
        allowed, _ = evaluate_tool_call(dict(base, tool_name="NotebookEdit", tool_input={
            "notebook_path": "/repo/.agents/band/evil.ipynb", "new_source": "x"}))
        self.assertFalse(allowed)

        # The launcher is protected too
        allowed, _ = evaluate_tool_call(dict(base, tool_name="Write", tool_input={
            "file_path": "/repo/.agents/bin/band", "content": "exit 0"}))
        self.assertFalse(allowed)

        # Bash carries tool_input.command
        allowed, _ = evaluate_tool_call(dict(base, tool_name="Bash", tool_input={
            "command": "echo '{}' > .agents/tasks/feat/state.json", "description": "x"}))
        self.assertFalse(allowed)

        allowed, reason = evaluate_tool_call(dict(base, tool_name="Bash", tool_input={"command": "sh .agents/bin/band --status"}))
        self.assertTrue(allowed, reason)
        allowed, _ = evaluate_tool_call(dict(base, tool_name="Edit", tool_input={
            "file_path": "/repo/src/main.py", "old_string": "a", "new_string": "b"}))
        self.assertTrue(allowed)

        # Garbage payloads never crash the guard
        self.assertTrue(evaluate_tool_call({"raw": "not json"})[0])
        self.assertTrue(evaluate_tool_call({"tool_input": "string"})[0])

    def test_project_settings_protected_but_not_global(self):
        import os, tempfile
        root = tempfile.mkdtemp(prefix="band_guard_")
        os.makedirs(os.path.join(root, ".agents"))
        os.symlink(".agents", os.path.join(root, ".claude"))
        base = {"hook_event_name": "PreToolUse", "cwd": root, "tool_name": "Edit"}
        for path in (".agents/settings.json", ".claude/settings.json", os.path.join(root, ".claude", "settings.json")):
            allowed, _ = evaluate_tool_call(dict(base, tool_input={"file_path": path}))
            self.assertFalse(allowed, path)
        for path in (os.path.expanduser("~/.claude/settings.json"), ".claude/settings.local.json", "src/settings.json"):
            allowed, _ = evaluate_tool_call(dict(base, tool_input={"file_path": path}))
            self.assertTrue(allowed, path)
        for cmd in ("echo '{}' > .claude/settings.json", "sed -i s/a/b/ .agents/settings.json", "rm -f ./.agents/settings.json"):
            self.assertTrue(is_command_dangerous(cmd)[0], cmd)
        for cmd in ("cat .claude/settings.json", "echo x > ~/.claude/settings.json.bak", "jq . .agents/settings.json"):
            self.assertFalse(is_command_dangerous(cmd)[0], cmd)

    def test_harness_detection(self):
        self.assertEqual(detect_harness({"hook_event_name": "PreToolUse"}), "claude-code")
        self.assertEqual(detect_harness({"tool_name": "write_to_file"}), "legacy")
        self.assertEqual(detect_harness({}, "claude-code"), "claude-code")
        self.assertEqual(detect_harness({"hook_event_name": "PreToolUse"}, "legacy"), "legacy")

    def test_guard_response_claude_code(self):
        deny = guard_response(False, "nope", "claude-code")
        self.assertEqual(deny["exit_code"], 2)
        self.assertIn("nope", deny["stderr"])
        body = json.loads(deny["stdout"])
        self.assertEqual(body, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "nope"}})

        allow = guard_response(True, "", "claude-code")
        # Silent allow: never emit permissionDecision "allow" (would bypass user permission prompts)
        self.assertEqual(allow, {"stdout": "", "stderr": "", "exit_code": 0})

    def test_guard_response_legacy_unchanged(self):
        self.assertEqual(json.loads(guard_response(True, "", "legacy")["stdout"]), {"decision": "allow"})
        deny = guard_response(False, "nope", "legacy")
        self.assertEqual(deny["exit_code"], 2)
        self.assertEqual(json.loads(deny["stdout"])["decision"], "deny")

    def test_stop_response(self):
        block = stop_response({"decision": "continue", "reason": "fix tests"}, "claude-code")
        self.assertEqual(block["exit_code"], 2)
        self.assertIn("fix tests", block["stderr"])
        self.assertEqual(json.loads(block["stdout"])["hookSpecificOutput"],
                         {"hookEventName": "Stop", "decision": "continue", "reason": "fix tests"})

        allow = stop_response({"decision": "allow", "reason": "done"}, "claude-code")
        self.assertEqual(allow["exit_code"], 0)
        self.assertEqual(allow["stdout"], "")

        err = stop_response({"decision": "error", "reason": "boom"}, "claude-code")
        self.assertEqual(err["exit_code"], 0)
        self.assertIn("boom", json.loads(err["stdout"])["systemMessage"])

        legacy = stop_response({"decision": "continue", "reason": "r"}, "legacy")
        self.assertEqual(legacy["exit_code"], 0)
        self.assertEqual(json.loads(legacy["stdout"]), {"decision": "continue", "reason": "r"})


class TestStageBoundaryGuard(unittest.TestCase):
    RED = {"id": "red-phase", "role": "Test Author",
           "allow": ["tests/**", "**/*.test.*", "**/*.spec.*", "**/specs/**", "**/__tests__/**"]}
    GREEN = {"id": "green-phase", "role": "Code Implementer", "deny": ["tests/**", "**/*.test.*"]}

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _edit(self, path, tool="Edit", stage=None):
        return evaluate_tool_call(
            {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": self.root, "tool_input": {"file_path": path}},
            stage=stage, repo_root=self.root)

    def test_red_stage_refuses_production_edit(self):
        allowed, reason = self._edit(os.path.join(self.root, "src", "user.py"), stage=self.RED)
        self.assertFalse(allowed)
        self.assertIn("red-phase", reason)
        self.assertIn("src/user.py", reason)
        self.assertIn("not in allow list", reason)
        allowed, _ = self._edit("src/user.py", tool="Write", stage=self.RED)
        self.assertFalse(allowed)

    def test_red_stage_allows_test_file(self):
        self.assertTrue(self._edit(os.path.join(self.root, "tests", "test_user.py"), stage=self.RED)[0])
        self.assertTrue(self._edit("web/src/user.spec.ts", tool="Write", stage=self.RED)[0])
        self.assertTrue(self._edit("user.test.ts", stage=self.RED)[0])

    def test_red_stage_read_only_tools_unaffected(self):
        allowed, _ = self._edit(os.path.join(self.root, "src", "user.py"), tool="Read", stage=self.RED)
        self.assertTrue(allowed)

    def test_paths_outside_repo_unaffected(self):
        self.assertTrue(self._edit("/nonexistent-elsewhere/notes.md", stage=self.RED)[0])

    def test_stage_without_allow_unchanged(self):
        self.assertTrue(self._edit("src/user.py", stage={"id": "free", "claims": []})[0])
        self.assertTrue(self._edit("src/user.py", stage=None)[0])
        # deny-only stage: production code fine, tests refused
        self.assertTrue(self._edit("src/user.py", stage=self.GREEN)[0])
        allowed, reason = self._edit("tests/test_user.py", stage=self.GREEN)
        self.assertFalse(allowed)
        self.assertIn("Denied modification", reason)

    def test_run_guard_uses_stage_resolver(self):
        from band import guard as guard_mod
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": self.root,
                   "tool_input": {"file_path": "src/user.py"}}
        emitted = []
        with mock.patch("band.hook_io.read_stdin_payload", return_value=payload), \
             mock.patch("band.hook_io.emit", side_effect=emitted.append), \
             mock.patch("band.config.REPO_ROOT", Path(self.root)):
            guard_mod.run_guard("claude-code", stage_resolver=lambda: self.RED)
        self.assertEqual(emitted[0]["exit_code"], 2)
        self.assertIn("not in allow list", emitted[0]["stderr"])


if __name__ == "__main__":
    unittest.main()
