import json
import unittest
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


if __name__ == "__main__":
    unittest.main()
