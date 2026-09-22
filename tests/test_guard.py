import json
import unittest
from band.guard import is_path_protected, is_command_dangerous, evaluate_tool_call


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


if __name__ == "__main__":
    unittest.main()
