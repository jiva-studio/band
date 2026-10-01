import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from band.adapters import critic_tool
from band.adapters.critic_tool import (
    CriticClaimTool,
    DEFAULT_TIMEOUT_S,
    collect_task_diff,
    resolve_base_ref,
)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class TestCriticTool(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="band_critic_test_"))
        _git(self.repo, "init", "-b", "main")
        _git(self.repo, "config", "user.email", "test@band.ai")
        _git(self.repo, "config", "user.name", "Band Test")
        (self.repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-m", "base")
        _git(self.repo, "checkout", "-b", "task/feat")

        self.task_dir = self.repo / ".agents" / "tasks" / "feat"
        self.task_dir.mkdir(parents=True)
        (self.task_dir / "intent.md").write_text("# Intent\nDo the thing.\n", encoding="utf-8")

        self.tool = CriticClaimTool()
        self.context = {"task_dir": self.task_dir, "slug": "feat", "spec_data": {}}
        self._patch = mock.patch.object(critic_tool, "REPO_ROOT", self.repo)
        self._patch.start()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for var in ("BAND_CRITIC_TIMEOUT", "BAND_CRITIC_MAX_DIFF_CHARS", "BAND_CRITIC_MAX_INTENT_CHARS", "BAND_BASE_BRANCH"):
            os.environ.pop(var, None)

    def tearDown(self):
        self._env.stop()
        self._patch.stop()
        shutil.rmtree(self.repo, ignore_errors=True)

    def _commit_change(self, name, content):
        (self.repo / name).write_text(content, encoding="utf-8")
        _git(self.repo, "add", name)
        _git(self.repo, "commit", "-m", f"change {name}")

    def test_diff_spans_all_task_commits_uncommitted_and_untracked(self):
        self._commit_change("a.py", "A = 1\n")
        self._commit_change("b.py", "B = 2\n")  # HEAD~1 alone would miss a.py
        (self.repo / "app.py").write_text("print('v2')\n", encoding="utf-8")  # uncommitted
        (self.repo / "new.py").write_text("NEW = 3\n", encoding="utf-8")  # untracked

        base = resolve_base_ref({}, {}, self.repo)
        self.assertEqual(base, "main")
        ok, desc, diff = collect_task_diff(self.repo, base)
        self.assertTrue(ok, desc)
        self.assertIn("merge-base of main", desc)
        for needle in ("A = 1", "B = 2", "print('v2')", "NEW = 3"):
            self.assertIn(needle, diff)
        # Band's own bookkeeping is excluded from the reviewed diff
        self.assertNotIn("Do the thing", diff)

    def test_base_precedence(self):
        _git(self.repo, "branch", "develop", "main")
        self.assertEqual(resolve_base_ref({"base": "develop"}, {"base_branch": "main"}, self.repo), "develop")
        self.assertEqual(resolve_base_ref({}, {"base_branch": "develop"}, self.repo), "develop")
        self.assertEqual(resolve_base_ref({"base": "does-not-exist"}, {}, self.repo), "main")

    def test_oversize_diff_fails_instead_of_truncating(self):
        self._commit_change("big.py", "X = 1\n" * 5000)  # ~30k chars
        with mock.patch.object(self.tool, "_find_cli_runner") as find_runner:
            res = self.tool.execute({"id": "crit", "checks": ["ok"], "max_diff_chars": 1000}, self.context)
            find_runner.assert_not_called()  # never reaches the reviewer
        self.assertFalse(res.passed)
        self.assertEqual(res.details["status"], "DIFF_TOO_LARGE")
        self.assertEqual(res.details["limit"], 1000)
        self.assertGreater(res.details["size"], 1000)
        self.assertIn("never reviews partial input", res.message)

    def test_oversize_diff_limit_from_env(self):
        self._commit_change("big.py", "X = 1\n" * 500)
        os.environ["BAND_CRITIC_MAX_DIFF_CHARS"] = "100"
        res = self.tool.execute({"id": "crit", "checks": ["ok"]}, self.context)
        self.assertFalse(res.passed)
        self.assertEqual(res.details["status"], "DIFF_TOO_LARGE")

    def test_oversize_intent_fails(self):
        self._commit_change("a.py", "A = 1\n")
        (self.task_dir / "intent.md").write_text("x" * 5000, encoding="utf-8")
        res = self.tool.execute({"id": "crit", "checks": ["ok"], "max_intent_chars": 100}, self.context)
        self.assertFalse(res.passed)
        self.assertEqual(res.details["status"], "INTENT_TOO_LARGE")

    def test_empty_diff_fails(self):
        res = self.tool.execute({"id": "crit", "checks": ["ok"]}, self.context)
        self.assertFalse(res.passed)
        self.assertEqual(res.details["status"], "EMPTY_DIFF")

    def test_full_prompt_sent_via_stdin_with_default_timeout(self):
        payload = "Y = 2\n" * 3000  # well past the old 8000-char truncation
        self._commit_change("mid.py", payload)
        captured = {}

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/fake/claude":
                captured["cmd"] = cmd
                captured["input"] = kwargs.get("input")
                captured["timeout"] = kwargs.get("timeout")
                return subprocess.CompletedProcess(cmd, 0, stdout='{"passed": true, "findings": []}', stderr="")
            return real_run(cmd, **kwargs)

        real_run = subprocess.run
        with mock.patch.object(self.tool, "_find_cli_runner", return_value=("claude", "/fake/claude")), \
                mock.patch.object(critic_tool.subprocess, "run", side_effect=fake_run):
            res = self.tool.execute({"id": "crit", "checks": ["ok"]}, self.context)

        self.assertTrue(res.passed, res.message)
        self.assertEqual(captured["timeout"], DEFAULT_TIMEOUT_S)
        self.assertEqual(DEFAULT_TIMEOUT_S, 300)
        self.assertIn("+Y = 2\n" * 3000, captured["input"])  # every line, untruncated
        self.assertNotIn("Y = 2", " ".join(captured["cmd"]))

    def test_timeout_reports_clear_failure(self):
        self._commit_change("a.py", "A = 1\n")
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd and cmd[0] == "/fake/claude":
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            return real_run(cmd, **kwargs)

        with mock.patch.object(self.tool, "_find_cli_runner", return_value=("claude", "/fake/claude")), \
                mock.patch.object(critic_tool.subprocess, "run", side_effect=fake_run):
            res = self.tool.execute({"id": "crit", "checks": ["ok"], "timeout": 7}, self.context)
        self.assertFalse(res.passed)
        self.assertEqual(res.details["status"], "TIMEOUT")
        self.assertIn("7s", res.message)

    def test_validate_numeric_settings(self):
        self.assertEqual(self.tool.validate({"checks": ["x"], "timeout": 60, "max_diff_chars": 10}), [])
        errors = self.tool.validate({"checks": ["x"], "timeout": "soon", "max_diff_chars": 0})
        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()
