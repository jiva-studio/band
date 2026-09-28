import fnmatch
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from band.config import REPO_ROOT, TASKS_DIR
from band.yaml_loader import load_yaml
from band.pipeline_loader import load_pipeline_config
from band.validator import TOOL_REGISTRY
from band.cache import ClaimCache
from band.engine import DoneEngine

# Band's own control area. Stage `allow` lists describe the product files a stage
# may touch; task specs/artifacts under these prefixes are never counted against them.
BAND_CONTROL_PREFIXES = (".agents/", ".claude/")


def stage_allow_patterns(stage: Dict[str, Any]) -> List[str]:
    return list(stage.get("allow") or stage.get("allow_edits") or stage.get("include") or [])


def stage_deny_patterns(stage: Dict[str, Any]) -> List[str]:
    return list(stage.get("deny") or stage.get("deny_edits") or stage.get("forbid_edits") or stage.get("exclude") or [])


def matches_any_pattern(file_path: str, patterns: List[str]) -> bool:
    name = Path(file_path).name
    for pattern in patterns:
        if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(name, pattern) or pattern in file_path:
            return True
        # "**/x" should also match "x" at the repository root.
        if pattern.startswith("**/") and fnmatch.fnmatch(file_path, pattern[3:]):
            return True
    return False


def stage_path_violation(stage: Dict[str, Any], file_path: str) -> Optional[str]:
    """Returns a violation message if the stage may not modify file_path (repo-relative), else None."""
    path = file_path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    deny_patterns = stage_deny_patterns(stage)
    if deny_patterns and matches_any_pattern(path, deny_patterns):
        return f"Denied modification: '{path}'"
    allow_patterns = stage_allow_patterns(stage)
    if allow_patterns and not path.startswith(BAND_CONTROL_PREFIXES) and not matches_any_pattern(path, allow_patterns):
        return f"Disallowed modification (not in allow list {allow_patterns}): '{path}'"
    return None


class PipelineRunner:
    """Deterministic, Claims-Driven State-Machine Runner and Hook Controller."""

    def __init__(self, spec_path: Path):
        self.spec_path = spec_path
        self.task_dir = spec_path.parent
        self.state_file = self.task_dir / "state.json"
        self.cache = ClaimCache(self.task_dir)

    def read_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            legacy_state = self.task_dir / "artifacts" / "state.json"
            if legacy_state.exists():
                try:
                    return json.loads(legacy_state.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write_state(self, state: Dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def init_pipeline(self, pipeline_override: Optional[str] = None) -> Dict[str, Any]:
        if not self.spec_path.exists():
            raise FileNotFoundError(f"Specification {self.spec_path} does not exist.")

        manifest = load_yaml(self.spec_path)
        slug = manifest.get("slug", self.task_dir.name)
        pipeline_name = pipeline_override or manifest.get("pipeline", "standard")
        pipeline_cfg = load_pipeline_config(pipeline_name)
        stages = pipeline_cfg.get("stages", [])

        first_stage_id = "gatekeeper"
        if stages:
            first_stage_id = stages[0].get("id") if isinstance(stages[0], dict) else stages[0]

        state = {
            "slug": slug,
            "pipeline": pipeline_name,
            "pipeline_description": pipeline_cfg.get("description", ""),
            "status": "in_progress",
            "current_stage_idx": 0,
            "current_stage_id": first_stage_id,
            "stages_completed": [],
            "stage_outputs": {},
            "claims": {},
            # Files already dirty when the stage starts are not held against its allow/deny boundary.
            "stage_baselines": {first_stage_id: self._get_changed_files()},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self.write_state(state)
        return state

    def get_current_stage(self, state: Dict[str, Any], pipeline_cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        stages = pipeline_cfg.get("stages", [])
        idx = state.get("current_stage_idx", 0)
        if 0 <= idx < len(stages):
            stage = stages[idx]
            if isinstance(stage, str):
                return {"id": stage, "role": stage, "claims": []}
            return stage
        return None

    def _get_changed_files(self) -> List[str]:
        try:
            res = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5
            )
            files = []
            for line in res.stdout.splitlines():
                if len(line) >= 3:
                    path_part = line[3:].strip().strip('"')
                    if " -> " in path_part:
                        old_p, new_p = path_part.split(" -> ", 1)
                        files.append(old_p.strip().strip('"'))
                        files.append(new_p.strip().strip('"'))
                    else:
                        files.append(path_part)
            return files
        except Exception:
            return []

    def _matches_any_pattern(self, file_path: str, patterns: List[str]) -> bool:
        return matches_any_pattern(file_path, patterns)

    def _check_stage_file_boundaries(self, stage: Dict[str, Any], current_files: List[str], baseline_files: List[str]) -> List[str]:
        """Validates stage allow/deny file boundaries against newly modified files relative to baseline."""
        violations = []
        for f in current_files:
            if f in baseline_files:
                continue
            violation = stage_path_violation(stage, f)
            if violation:
                violations.append(violation)
        return violations

    def _check_forbidden_edits(self, forbid_patterns: List[str], current_files: List[str], baseline_files: List[str]) -> List[str]:
        return self._check_stage_file_boundaries({"deny": forbid_patterns}, current_files, baseline_files)

    def _evaluate_stage_claims(self, stage: Dict[str, Any], manifest: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]], str]:
        """Evaluates stage claims using the unified DoneEngine and claim tools."""
        stage_claims = stage.get("claims", [])
        if not stage_claims:
            if stage.get("id") == "gatekeeper":
                engine = DoneEngine(self.spec_path)
                res = engine.run(is_hook_mode=True)
                return res.get("passed", False), res.get("results", []), res.get("error", "")
            return True, [], ""

        context = {
            "task_dir": self.task_dir,
            "slug": manifest.get("slug", "task"),
            "spec_data": manifest,
        }

        all_passed = True
        results = []
        err_messages = []

        for claim in stage_claims:
            kind = claim.get("tool") or claim.get("kind")
            claim_id = claim.get("id", "stage-claim")

            # Check cache
            cached = self.cache.get_cached_result(claim)
            if cached:
                results.append({
                    "claim_id": claim_id,
                    "kind": kind,
                    "passed": True,
                    "message": "CACHED",
                    "details": cached.get("details", {}),
                    "duration_ms": 0.0,
                    "cached": True
                })
                continue

            tool = TOOL_REGISTRY.get(kind)
            if not tool:
                all_passed = False
                err_messages.append(f"Unknown claim tool: {kind}")
                continue

            claim_res = tool.execute(claim, context)
            results.append({
                "claim_id": claim_id,
                "kind": kind,
                "passed": claim_res.passed,
                "message": claim_res.message,
                "details": claim_res.details,
                "duration_ms": claim_res.duration_ms,
                "cached": False
            })

            if claim_res.passed:
                self.cache.store_result(claim, passed=True, message=claim_res.message, details=claim_res.details)
            else:
                all_passed = False
                if claim_res.message:
                    err_messages.append(f"{claim_id}: {claim_res.message}")

        return all_passed, results, "\n".join(err_messages)

    def active_stage(self) -> Optional[Dict[str, Any]]:
        """The current stage of an in-progress pipeline, or None."""
        state = self.read_state()
        if not state or state.get("status") != "in_progress":
            return None
        manifest = load_yaml(self.spec_path) if self.spec_path.exists() else {}
        pipeline_name = state.get("pipeline") or manifest.get("pipeline", "standard")
        return self.get_current_stage(state, load_pipeline_config(pipeline_name))

    def advance_to_next_stage(self, state: Dict[str, Any], pipeline_cfg: Dict[str, Any], stage_id: str) -> Optional[Dict[str, Any]]:
        state["stages_completed"].append(stage_id)
        state["current_stage_idx"] += 1
        next_stage = self.get_current_stage(state, pipeline_cfg)
        state["current_stage_id"] = next_stage.get("id") if next_stage else "completed"
        state["updated_at"] = time.time()
        
        # Snapshot current git modified files for next stage forbidden edits baseline
        if "stage_baselines" not in state:
            state["stage_baselines"] = {}
        if next_stage:
            state["stage_baselines"][next_stage.get("id", "")] = self._get_changed_files()
            
        self.write_state(state)
        return next_stage

    def pause_pipeline(self) -> Dict[str, Any]:
        state = self.read_state()
        if not state:
            return {"status": "not_found", "message": "No active pipeline to pause."}
        state["status"] = "paused"
        state["updated_at"] = time.time()
        self.write_state(state)
        return {"status": "paused", "slug": state.get("slug")}

    def resume_pipeline(self) -> Dict[str, Any]:
        state = self.read_state()
        if not state:
            return {"status": "not_found", "message": "No pipeline state found to resume."}
        state["status"] = "in_progress"
        state["updated_at"] = time.time()
        self.write_state(state)
        return {"status": "in_progress", "slug": state.get("slug")}

    def evaluate_and_advance(self, is_hook: bool = True) -> Dict[str, Any]:
        """Unified FSM and Hook evaluation driven strictly by pipeline stage claims."""
        if not self.spec_path.exists():
            return {"decision": "allow", "message": "No active spec found"}

        manifest = load_yaml(self.spec_path)
        state = self.read_state()
        pipeline_name = state.get("pipeline") or manifest.get("pipeline", "standard")
        pipeline_cfg = load_pipeline_config(pipeline_name)

        if not state:
            if is_hook:
                # Do not auto-initialize or block during hook if pipeline was not explicitly started
                return {"decision": "allow", "message": "Pipeline not initialized"}
            state = self.init_pipeline(pipeline_name)

        current_status = state.get("status", "idle")
        if current_status == "completed":
            return {"decision": "allow", "message": f"Pipeline [{pipeline_name}] already completed"}
        if current_status == "paused":
            return {"decision": "allow", "message": f"Pipeline [{pipeline_name}] is paused"}
        if current_status != "in_progress" and is_hook:
            return {"decision": "allow", "message": f"Pipeline is in status '{current_status}', not active"}

        current_stage = self.get_current_stage(state, pipeline_cfg)
        if not current_stage:
            # All stages completed -> Final Gatekeeper
            engine = DoneEngine(self.spec_path)
            gate_res = engine.run(is_hook_mode=is_hook)
            if gate_res.get("passed"):
                state["status"] = "completed"
                state["updated_at"] = time.time()
                self.write_state(state)
                return {
                    "decision": "allow",
                    "reason": f"🎉 Pipeline [{pipeline_name}] for task [{state.get('slug')}] PASSED all quality claims."
                }
            else:
                return {
                    "decision": "continue",
                    "reason": f"⛔ Final Gatekeeper verification failed:\n{gate_res.get('error', 'Claims not satisfied')}"
                }

        stage_id = current_stage.get("id", "stage")
        stage_role = current_stage.get("role", stage_id)

        # 1. Boundary & forbidden file edits check
        changed_files = self._get_changed_files()
        baseline_files = state.get("stage_baselines", {}).get(stage_id, [])
        if stage_allow_patterns(current_stage) or stage_deny_patterns(current_stage):
            violations = self._check_stage_file_boundaries(current_stage, changed_files, baseline_files)
            if violations:
                return {
                    "decision": "continue",
                    "reason": f"⛔ Stage [{stage_id}] ({stage_role}) modified files outside its allowed boundary:\n" + "\n".join([f"  - {v}" for v in violations])
                }

        # 2. Evaluate stage claims
        passed, results, err_msg = self._evaluate_stage_claims(current_stage, manifest)
        if not passed:
            return {
                "decision": "continue",
                "reason": f"⛔ Stage [{stage_id}] ({stage_role}) claims not satisfied:\n{err_msg or 'Checks failed'}"
            }

        # 3. Advance to next stage upon claim pass
        next_stage = self.advance_to_next_stage(state, pipeline_cfg, stage_id)
        if next_stage:
            next_role = next_stage.get("role", "Next Step")
            next_directive = next_stage.get("directive", "Proceed to next verification.")
            return {
                "decision": "continue",
                "reason": (
                    f"🚀 STAGE ADVANCEMENT [{stage_id} -> {next_stage['id']}]: All claims passed.\n"
                    f"DIRECTIVE FOR {next_role}: {next_directive}"
                )
            }
        else:
            # Reached end
            state["status"] = "completed"
            state["updated_at"] = time.time()
            self.write_state(state)
            return {
                "decision": "allow",
                "reason": f"🎉 Pipeline [{pipeline_name}] for task [{state.get('slug')}] PASSED all stages and claims."
            }
