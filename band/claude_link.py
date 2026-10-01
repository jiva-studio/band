"""Single canonical agent directory: `.agents/`, with `.claude -> .agents`.

Claude Code reads `.claude/settings.json`, `.claude/skills/`, `.claude/agents/`
and `.claude/commands/`. Band keeps all of that in `.agents/` and exposes it to
Claude Code through a whole-directory symlink `.claude -> .agents`.

If a real `.claude/` directory already exists, its contents are migrated into
`.agents/` first. Migration is all-or-nothing: a dry run collects conflicts,
and if there are any, nothing is touched and the reason is reported.
"""

import copy
import filecmp
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

AGENTS_DIRNAME = ".agents"
CLAUDE_DIRNAME = ".claude"

# Harness-local state that can arrive in .agents/ through the .claude link and must not be committed.
AGENTS_GITIGNORE_ENTRIES = ["settings.local.json", "worktrees/"]

# Directories whose children are merged entry by entry (never overwriting .agents entries).
MERGE_DIRS = ("skills", "agents", "commands")


def claude_link_status(repo_root: Path) -> Tuple[str, str]:
    """
    Returns (state, detail) for <repo>/.claude:
    "linked" (symlink to .agents), "missing", "foreign-link" (symlink elsewhere),
    "directory" (real directory) or "file".
    """
    claude = repo_root / CLAUDE_DIRNAME
    agents = repo_root / AGENTS_DIRNAME
    if claude.is_symlink():
        target = os.readlink(claude)
        try:
            if claude.resolve() == agents.resolve():
                return "linked", target
        except OSError:
            pass
        return "foreign-link", target
    if not claude.exists():
        return "missing", ""
    if claude.is_dir():
        return "directory", ""
    return "file", ""


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _same_content(a: Path, b: Path) -> bool:
    if a.is_file() and b.is_file():
        return filecmp.cmp(a, b, shallow=False)
    if a.is_dir() and b.is_dir():
        cmp = filecmp.dircmp(a, b)
        if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
            return False
        return all(_same_content(a / d, b / d) for d in cmp.common_dirs)
    return False


def merge_settings_dicts(base: Dict[str, Any], incoming: Dict[str, Any], path: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """
    Deep-merges Claude Code settings. Dicts merge recursively, lists are unioned
    (order kept, duplicates dropped), equal scalars are fine; differing scalars
    are conflicts (base value kept). Returns (merged, conflicts).
    """
    merged = copy.deepcopy(base)
    conflicts: List[str] = []
    for key, value in incoming.items():
        where = f"{path}.{key}" if path else key
        if key not in merged:
            merged[key] = copy.deepcopy(value)
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key], sub = merge_settings_dicts(merged[key], value, where)
            conflicts.extend(sub)
        elif isinstance(merged[key], list) and isinstance(value, list):
            for item in value:
                if item not in merged[key]:
                    merged[key].append(copy.deepcopy(item))
        elif merged[key] != value:
            conflicts.append(f"settings.json key '{where}' differs ({merged[key]!r} in .agents vs {value!r} in .claude)")
    return merged, conflicts


def _load_json_object(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as e:
        return {}, f"{path.name} is not valid JSON ({e})"
    if not isinstance(data, dict):
        return {}, f"{path.name} is not a JSON object"
    return data, ""


def plan_migration(repo_root: Path) -> Dict[str, Any]:
    """
    Dry run of migrating a real .claude/ directory into .agents/.
    Returns {"conflicts": [...], "moves": [(src, dst)], "drops": [src], "settings": merged-or-None}.
    """
    claude = repo_root / CLAUDE_DIRNAME
    agents = repo_root / AGENTS_DIRNAME
    plan: Dict[str, Any] = {"conflicts": [], "moves": [], "drops": [], "settings": None}

    for entry in sorted(claude.iterdir()):
        name = entry.name
        dest = agents / name

        if name == "settings.json":
            incoming, err = _load_json_object(entry)
            if err:
                plan["conflicts"].append(f".claude/{err}")
                continue
            existing: Dict[str, Any] = {}
            if dest.exists():
                existing, err = _load_json_object(dest)
                if err:
                    plan["conflicts"].append(f".agents/{err}")
                    continue
            merged, conflicts = merge_settings_dicts(existing, incoming)
            plan["conflicts"].extend(conflicts)
            plan["settings"] = merged
            plan["drops"].append(entry)
            continue

        if name in MERGE_DIRS and entry.is_dir() and not entry.is_symlink():
            if dest.exists() and not dest.is_dir():
                plan["conflicts"].append(f".claude/{name}/ cannot merge: .agents/{name} is not a directory")
                continue
            for child in sorted(entry.iterdir()):
                child_dest = dest / child.name
                if child.is_symlink() and _same_path(child, child_dest):
                    plan["drops"].append(child)  # e.g. old .claude/skills/x -> ../../.agents/skills/x
                elif child_dest.exists() or child_dest.is_symlink():
                    if _same_content(child, child_dest):
                        plan["drops"].append(child)
                    else:
                        plan["conflicts"].append(f".claude/{name}/{child.name} conflicts with existing .agents/{name}/{child.name}")
                else:
                    plan["moves"].append((child, child_dest))
            continue

        if entry.is_symlink() and _same_path(entry, dest):
            plan["drops"].append(entry)
        elif dest.exists() or dest.is_symlink():
            if _same_content(entry, dest):
                plan["drops"].append(entry)
            else:
                plan["conflicts"].append(f".claude/{name} conflicts with existing .agents/{name}")
        else:
            plan["moves"].append((entry, dest))

    return plan


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def ensure_claude_link(repo_root: Path) -> List[str]:
    """Makes .claude a symlink to .agents, migrating a real .claude/ first. Returns action messages."""
    claude = repo_root / CLAUDE_DIRNAME
    agents = repo_root / AGENTS_DIRNAME
    agents.mkdir(parents=True, exist_ok=True)
    state, detail = claude_link_status(repo_root)

    if state == "linked":
        return []
    if state == "foreign-link":
        return [f"SKIPPED .claude -> .agents: .claude is a symlink to '{detail}'; remove it and re-run --init"]
    if state == "file":
        return ["SKIPPED .claude -> .agents: .claude is a regular file; remove it and re-run --init"]

    actions: List[str] = []
    if state == "directory":
        plan = plan_migration(repo_root)
        if plan["conflicts"]:
            return ["SKIPPED migrating .claude/ into .agents/ (nothing changed): " + "; ".join(plan["conflicts"])]
        if plan["settings"] is not None:
            (agents / "settings.json").write_text(json.dumps(plan["settings"], indent=2) + "\n", encoding="utf-8")
            actions.append("Merged .claude/settings.json into .agents/settings.json")
        for src, dst in plan["moves"]:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            actions.append(f"Moved {src.relative_to(repo_root)} -> {dst.relative_to(repo_root)}")
        for src in plan["drops"]:
            if src.exists() or src.is_symlink():
                _remove(src)
        # Everything is migrated; remove what is left (only emptied merge dirs).
        leftovers = [p for p in claude.rglob("*") if not p.is_dir()]
        if leftovers:
            return actions + [f"SKIPPED .claude -> .agents: unexpected leftovers in .claude/: {', '.join(str(p) for p in leftovers)}"]
        shutil.rmtree(claude)

    claude.symlink_to(AGENTS_DIRNAME, target_is_directory=True)
    actions.append("Linked .claude -> .agents")
    return actions


def ensure_agents_gitignore(repo_root: Path) -> List[str]:
    """Ignores harness-local state that lands in .agents/ through the .claude link."""
    gi = repo_root / AGENTS_DIRNAME / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [e for e in AGENTS_GITIGNORE_ENTRIES if e not in (l.strip() for l in lines)]
    if not missing:
        return []
    with open(gi, "a", encoding="utf-8") as f:
        if lines and lines[-1].strip():
            f.write("\n")
        if not lines:
            f.write("# Harness-local state (also reachable as .claude/ via the symlink)\n")
        f.write("\n".join(missing) + "\n")
    return [f"Added {', '.join(missing)} to .agents/.gitignore"]
