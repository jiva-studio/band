import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from band.config import REPO_ROOT
from band.claude_link import ensure_agents_gitignore, ensure_claude_link
from band.launcher import (
    CLAUDE_GUARD_COMMAND,
    CLAUDE_GUARD_MATCHER,
    CLAUDE_STOP_COMMAND,
    LAUNCHER_REL_PATH,
    LEGACY_GUARD_COMMAND,
    LEGACY_GUARD_MATCHER,
    LEGACY_STOP_COMMAND,
    write_launcher,
)


def detect_project_stack(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """Lightweight discovery of project indicators (language, build files, env files)."""
    stack: Dict[str, Any] = {
        "language": "generic",
        "build_system": "makefile" if (repo_root / "Makefile").exists() else "unknown",
        "has_makefile": (repo_root / "Makefile").exists(),
        "env_files": [],
        "config_files": [],
    }

    # Discover build/project manifests
    if (repo_root / "package.json").exists():
        stack["language"] = "typescript" if (repo_root / "tsconfig.json").exists() else "javascript"
        stack["config_files"].append("package.json")
    elif (repo_root / "pyproject.toml").exists() or (repo_root / "requirements.txt").exists() or (repo_root / "setup.py").exists():
        stack["language"] = "python"
        stack["config_files"].extend([f.name for f in [repo_root / "pyproject.toml", repo_root / "requirements.txt"] if f.exists()])
    elif (repo_root / "Cargo.toml").exists():
        stack["language"] = "rust"
        stack["config_files"].append("Cargo.toml")
    elif (repo_root / "go.mod").exists():
        stack["language"] = "go"
        stack["config_files"].append("go.mod")

    # Discover env files
    for item in repo_root.glob(".env*"):
        if item.is_file():
            stack["env_files"].append(item.name)

    return stack


def legacy_hooks_config() -> Dict[str, Any]:
    """Hook config in the original .agents/hooks.json dialect (non-Claude harnesses)."""
    return {
        "deterministic-done-gate": {
            "enabled": True,
            "PreToolUse": [
                {
                    "matcher": LEGACY_GUARD_MATCHER,
                    "type": "command",
                    "command": LEGACY_GUARD_COMMAND,
                    "timeout": 30
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": LEGACY_STOP_COMMAND,
                    "timeout": 600
                }
            ]
        }
    }


def claude_hooks_config() -> Dict[str, List[Dict[str, Any]]]:
    """Band's hook groups in Claude Code's .claude/settings.json schema."""
    return {
        "PreToolUse": [
            {
                "matcher": CLAUDE_GUARD_MATCHER,
                "hooks": [{"type": "command", "command": CLAUDE_GUARD_COMMAND, "timeout": 30}],
            }
        ],
        "Stop": [
            {
                # Stop hooks have no matcher in Claude Code. The timeout must cover the
                # slowest claim (critic default 300s) plus builds/tests.
                "hooks": [{"type": "command", "command": CLAUDE_STOP_COMMAND, "timeout": 600}],
            }
        ],
    }


def _is_band_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    return ".agents/bin/band" in command or bool(re.search(r"-m\s+band\s+--(guard|hook)\b", command))


def merge_claude_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a copy of a Claude Code settings dict with Band's hooks merged in.
    Existing non-Band settings and hooks are preserved; previous Band hook
    entries are replaced, so the merge is idempotent.
    """
    merged = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    hooks = merged.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    merged["hooks"] = hooks

    for event, band_groups in claude_hooks_config().items():
        groups = hooks.get(event)
        if not isinstance(groups, list):
            groups = []
        kept: List[Any] = []
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                remaining = [h for h in group["hooks"] if not (isinstance(h, dict) and _is_band_command(h.get("command")))]
                if not remaining:
                    continue
                if len(remaining) != len(group["hooks"]):
                    group = dict(group, hooks=remaining)
            kept.append(group)
        hooks[event] = kept + copy.deepcopy(band_groups)

    return merged


def claude_settings_has_band_hooks(settings: Dict[str, Any]) -> Dict[str, bool]:
    """Reports which Band hooks are wired in a Claude Code settings dict."""
    found = {"PreToolUse": False, "Stop": False}
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return found
    for event, marker in (("PreToolUse", "--guard"), ("Stop", "--hook")):
        for group in hooks.get(event) or []:
            if not isinstance(group, dict):
                continue
            for h in group.get("hooks") or []:
                if isinstance(h, dict) and _is_band_command(h.get("command")) and marker in h["command"]:
                    found[event] = True
    return found


def write_claude_settings(repo_root: Path) -> str:
    """
    Merges Band hooks into <repo>/.agents/settings.json, the canonical Claude Code
    settings file (Claude Code reads it as .claude/settings.json via the
    .claude -> .agents symlink). Returns an action message.
    """
    settings_file = repo_root / ".agents" / "settings.json"
    existing: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            return f"SKIPPED .agents/settings.json: existing file is not valid JSON ({e}); fix it and re-run --init"
        if not isinstance(existing, dict):
            return "SKIPPED .agents/settings.json: existing file is not a JSON object"

    merged = merge_claude_settings(existing)
    if settings_file.exists() and merged == existing:
        return ""
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return ("Updated" if existing else "Created") + " Claude Code hooks in .agents/settings.json"


def setup_project(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """
    Initializes standard Band plumbing: the .agents/bin/band launcher,
    .agents/hooks.json (other harnesses), the .claude -> .agents symlink
    (migrating a real .claude/ first), Claude Code hooks merged into
    .agents/settings.json, .agents/.gitignore, .worktreeinclude and the
    root .gitignore entry.
    """
    stack = detect_project_stack(repo_root)
    actions_taken: List[str] = []

    # 1. Ensure .agents directory, launcher & hooks.json
    agents_dir = repo_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    if write_launcher(repo_root):
        actions_taken.append(f"Wrote launcher {LAUNCHER_REL_PATH}")

    hooks_file = agents_dir / "hooks.json"
    if not hooks_file.exists():
        hooks_file.write_text(json.dumps(legacy_hooks_config(), indent=2) + "\n", encoding="utf-8")
        actions_taken.append("Created .agents/hooks.json")
    else:
        # Migrate old `python3 -m band` commands (fail when .agents is not on sys.path).
        try:
            text = hooks_file.read_text(encoding="utf-8")
            data = json.loads(text)
            gate = data.get("deterministic-done-gate") if isinstance(data, dict) else None
            if isinstance(gate, dict) and any(
                isinstance(h, dict) and isinstance(h.get("command"), str) and h["command"].startswith("python3 -m band")
                for ev in ("PreToolUse", "Stop") for h in (gate.get(ev) or [])
            ):
                data["deterministic-done-gate"] = dict(gate, **{
                    k: v for k, v in legacy_hooks_config()["deterministic-done-gate"].items() if k in ("PreToolUse", "Stop")
                })
                hooks_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                actions_taken.append("Migrated .agents/hooks.json commands to the .agents/bin/band launcher")
        except Exception:
            pass

    # 1b. .agents is canonical: link .claude -> .agents (migrate a real .claude/ first),
    #     then merge Band's Claude Code hooks into .agents/settings.json.
    actions_taken.extend(ensure_claude_link(repo_root))
    msg = write_claude_settings(repo_root)
    if msg:
        actions_taken.append(msg)
    actions_taken.extend(ensure_agents_gitignore(repo_root))

    # 2. Setup .worktreeinclude
    wt_inc = repo_root / ".worktreeinclude"
    if not wt_inc.exists():
        inc_lines = ["# Untracked files to copy into new Git Worktrees", ".env", ".env.local", ".env.development"]
        for env_f in stack.get("env_files", []):
            if env_f not in inc_lines:
                inc_lines.append(env_f)
        wt_inc.write_text("\n".join(inc_lines) + "\n", encoding="utf-8")
        actions_taken.append("Created .worktreeinclude")

    # 3. Ensure .agents/worktrees/ in .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        git_content = gitignore.read_text(encoding="utf-8")
        if ".agents/worktrees/" not in git_content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n# Band isolated task worktrees\n.agents/worktrees/\n")
            actions_taken.append("Added .agents/worktrees/ to .gitignore")
    else:
        gitignore.write_text(".agents/worktrees/\n", encoding="utf-8")
        actions_taken.append("Created .gitignore with .agents/worktrees/")

    return {
        "stack": stack,
        "actions_taken": actions_taken,
        "repo_root": str(repo_root),
    }
