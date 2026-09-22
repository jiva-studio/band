import json
import re
import subprocess
from pathlib import Path
from typing import Any
from band.config import REPO_ROOT


def _parse_val(v: str) -> Any:
    v = v.strip()
    if not v or v in ("null", "~", "None"):
        return None
    if v in ("true", "True", "TRUE"):
        return True
    if v in ("false", "False", "FALSE"):
        return False
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if (v.startswith('[') and v.endswith(']')) or (v.startswith('{') and v.endswith('}')):
        try:
            return json.loads(v)
        except Exception:
            pass
    if re.match(r"^-?\d+$", v):
        return int(v)
    if re.match(r"^-?\d+\.\d+$", v):
        return float(v)
    return v


def _parse_yaml_lines(lines: list) -> Any:
    if not lines:
        return {}

    first_indent = lines[0][0]
    is_list = lines[0][1].startswith("- ")

    if is_list:
        result = []
        i = 0
        while i < len(lines):
            indent, text = lines[i]
            if indent != first_indent:
                break
            item_text = text[2:].strip()
            child_lines = []
            j = i + 1
            while j < len(lines) and lines[j][0] > indent:
                child_lines.append(lines[j])
                j += 1

            if not item_text:
                result.append(_parse_yaml_lines(child_lines) if child_lines else None)
            elif ":" in item_text and not (item_text.startswith('"') or item_text.startswith("'")):
                k, v = item_text.split(":", 1)
                first_dict_line = (indent + 2, f"{k.strip()}: {v.strip()}".strip())
                all_dict_lines = [first_dict_line] + child_lines
                result.append(_parse_yaml_lines(all_dict_lines))
            else:
                result.append(_parse_val(item_text))
            i = j
        return result
    else:
        result = {}
        i = 0
        while i < len(lines):
            indent, text = lines[i]
            if indent != first_indent:
                break
            if ":" in text:
                k, v = text.split(":", 1)
                k = k.strip()
                v = v.strip()
                child_lines = []
                j = i + 1
                while j < len(lines) and lines[j][0] > indent:
                    child_lines.append(lines[j])
                    j += 1
                if child_lines:
                    result[k] = _parse_yaml_lines(child_lines)
                else:
                    result[k] = _parse_val(v)
                i = j
            else:
                i += 1
        return result


def _parse_simple_yaml(text: str) -> Any:
    clean_lines = []
    for line in text.splitlines():
        stripped = re.sub(r'(?<!["\'])\s*#.*$', "", line)
        if stripped.strip():
            clean_lines.append((len(line) - len(line.lstrip()), stripped.strip()))
    return _parse_yaml_lines(clean_lines)


def load_yaml(file_path_or_text: Any) -> Any:
    """Universal YAML loader with multiple fallbacks (PyYAML -> js-yaml via node -> pure Python -> json)."""
    # 1. Try pyyaml
    try:
        import yaml
        if isinstance(file_path_or_text, (str, Path)) and Path(file_path_or_text).exists():
            with open(file_path_or_text, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        else:
            return yaml.safe_load(str(file_path_or_text))
    except ImportError:
        pass

    content = ""
    if isinstance(file_path_or_text, (str, Path)) and Path(file_path_or_text).exists():
        content = Path(file_path_or_text).read_text(encoding="utf-8")
    else:
        content = str(file_path_or_text)

    # 2. Try js-yaml via Node (if present)
    try:
        candidate_paths = [
            str(REPO_ROOT / "modules"),
            str(REPO_ROOT),
        ]
        if REPO_ROOT.parent.exists():
            for sibling in REPO_ROOT.parent.iterdir():
                if sibling.is_dir() and (sibling / "modules" / "node_modules").exists():
                    candidate_paths.append(str(sibling / "modules"))
                elif sibling.is_dir() and (sibling / "node_modules").exists():
                    candidate_paths.append(str(sibling))

        candidate_paths_json = json.dumps(candidate_paths)
        node_script = f"""
const fs = require("fs");
const candidatePaths = {candidate_paths_json};
let yaml;
for (const p of candidatePaths) {{
    try {{
        const yamlPath = require.resolve("js-yaml", {{ paths: [p] }});
        yaml = require(yamlPath);
        break;
    }} catch (e) {{}}
}}
if (!yaml) {{
    yaml = require("js-yaml");
}}

let input = "";
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {{
    try {{
        const obj = yaml.load(input);
        process.stdout.write(JSON.stringify(obj));
    }} catch(e) {{
        process.stderr.write(e.message);
        process.exit(1);
    }}
}});
"""
        res = subprocess.run(
            ["node", "-e", node_script],
            input=content,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10
        )
        if res.returncode == 0 and res.stdout:
            return json.loads(res.stdout)
    except Exception:
        pass

    # 3. Try pure Python zero-dependency parser
    try:
        parsed = _parse_simple_yaml(content)
        if parsed is not None:
            return parsed
    except Exception:
        pass

    # 4. Fallback: json
    try:
        return json.loads(content)
    except Exception:
        raise ValueError("Could not parse YAML with any available parser.")
