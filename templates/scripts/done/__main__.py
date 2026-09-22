import argparse
import json
import os
import sys
from pathlib import Path

# Ensure .agents/scripts is in sys.path
_scripts_dir = str(Path(__file__).resolve().parent.parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from typing import Optional
from done.yaml_loader import load_yaml
from done.config import TASKS_DIR, REPO_ROOT
from done.validator import validate_done_manifest
from done.pipeline_loader import validate_pipeline_manifest
from done.engine import DoneEngine
from done.pipeline_runner import PipelineRunner

def find_active_task_spec() -> Optional[Path]:
    # 1. Check if git branch matches a task folder in .agents/tasks/
    try:
        import subprocess
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True
        )
        branch = res.stdout.strip().replace("/", "-")
        if branch and (TASKS_DIR / branch / "done.yaml").exists():
            return TASKS_DIR / branch / "done.yaml"
    except Exception:
        pass

    # 2. Check most recently modified done.yaml in .agents/tasks/
    if TASKS_DIR.exists():
        candidates = list(TASKS_DIR.glob("*/done.yaml"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]

    return None

def main():
    parser = argparse.ArgumentParser(description="Deterministic task completion harness and validator.")
    parser.add_argument("--validate", type=str, help="Validate a done.yaml manifest against schema.")
    parser.add_argument("--validate-pipeline", type=str, help="Validate a pipeline.yaml file against schema.")
    parser.add_argument("--pipeline", type=str, help="Specify or override pipeline profile name (e.g. hardened, standard, fast, docs).")
    parser.add_argument("--start-pipeline", type=str, nargs="?", const="", help="Initialize pipeline FSM for a task.")
    parser.add_argument("--status", type=str, nargs="?", const="", help="Show pipeline FSM status for a task.")
    parser.add_argument("--spec", type=str, help="Run verification against specific done.yaml path.")
    parser.add_argument("--task", type=str, help="Run verification for specific task slug in .agents/tasks/<slug>.")
    parser.add_argument("--hook", action="store_true", help="Run in Stop-hook mode with JSON stdin/stdout.")

    args = parser.parse_args()

    # 1. Validate pipeline mode
    if args.validate_pipeline:
        p = Path(args.validate_pipeline).resolve()
        if not p.exists():
            print(f"Error: Pipeline file not found at {p}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = load_yaml(p)
        except Exception as e:
            print(f"YAML Syntax Error: {str(e)}", file=sys.stderr)
            sys.exit(1)

        is_valid, errors = validate_pipeline_manifest(data)
        if is_valid:
            print(f"✅ pipeline.yaml at {p.name} is VALID.")
            sys.exit(0)
        else:
            print(f"❌ pipeline.yaml schema validation failed with {len(errors)} error(s):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

    # 2. Validate done manifest mode
    if args.validate:
        p = Path(args.validate).resolve()
        if not p.exists():
            print(f"Error: File not found at {p}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = load_yaml(p)
        except Exception as e:
            print(f"YAML Syntax Error: {str(e)}", file=sys.stderr)
            sys.exit(1)

        is_valid, errors = validate_done_manifest(data)
        if is_valid:
            print(f"✅ done.yaml at {p.name} is VALID.")
            sys.exit(0)
        else:
            print(f"❌ done.yaml schema validation failed with {len(errors)} error(s):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

    # 3. Start Pipeline Mode
    if args.start_pipeline is not None:
        target_spec = None
        if args.start_pipeline:
            p = Path(args.start_pipeline).resolve()
            target_spec = p if p.name == "done.yaml" else (p / "done.yaml" if p.is_dir() else TASKS_DIR / args.start_pipeline / "done.yaml")
        else:
            target_spec = find_active_task_spec()

        if not target_spec or not target_spec.exists():
            print(f"Error: Could not locate done.yaml for starting pipeline.", file=sys.stderr)
            sys.exit(1)

        runner = PipelineRunner(target_spec)
        state = runner.init_pipeline(pipeline_override=args.pipeline)
        print(f"🚀 Pipeline [{state['pipeline']}] INITIALIZED for task [{state['slug']}].")
        print(f"👉 Current Stage: [{state['current_stage_id']}]")
        print(f"Active hooks in .agents/hooks.json will drive and gate each stage transition.")
        sys.exit(0)

    # 4. Status Mode
    if args.status is not None:
        target_spec = None
        if args.status:
            p = Path(args.status).resolve()
            target_spec = p if p.name == "done.yaml" else (p / "done.yaml" if p.is_dir() else TASKS_DIR / args.status / "done.yaml")
        else:
            target_spec = find_active_task_spec()

        if not target_spec or not target_spec.exists():
            print("No active task spec found.", file=sys.stderr)
            sys.exit(1)

        runner = PipelineRunner(target_spec)
        state = runner.read_state()
        if not state:
            print(f"No active pipeline state found for {target_spec.parent.name}. Run --start-pipeline to initialize.")
            sys.exit(0)

        print(f"Task: {state.get('slug')} | Pipeline: {state.get('pipeline')} | Status: {state.get('status')}")
        print(f"Current Stage: {state.get('current_stage_id')} (Index {state.get('current_stage_idx')})")
        print(f"Completed Stages: {', '.join(state.get('stages_completed', [])) or 'None'}")
        sys.exit(0)

    # 5. Hook mode (Driven by external Stop-hook)
    if args.hook:
        try:
            if (
                os.environ.get("DONE_GATE_DISABLE") == "1"
                or os.environ.get("FORCE_STOP") == "1"
                or os.environ.get("DONE_BYPASS") == "1"
                or os.environ.get("VIDYA_DONE") == "0"
            ):
                print(json.dumps({"decision": "allow"}))
                sys.exit(0)

            spec_file = find_active_task_spec()
            if not spec_file:
                print(json.dumps({"decision": "allow"}))
                sys.exit(0)

            runner = PipelineRunner(spec_file)
            result = runner.evaluate_and_advance(is_hook=True)
            print(json.dumps(result))
            sys.exit(0)
        except Exception as e:
            print(json.dumps({
                "decision": "continue",
                "reason": f"Verification harness internal error: {str(e)}"
            }))
            sys.exit(0)

    # 6. Direct execution mode
    target_spec = None
    if args.spec:
        target_spec = Path(args.spec).resolve()
    elif args.task:
        target_spec = TASKS_DIR / args.task / "done.yaml"
    else:
        target_spec = find_active_task_spec()

    if not target_spec or not target_spec.exists():
        print("No active done.yaml found. Provide --spec <path> or --task <slug>.", file=sys.stderr)
        sys.exit(1)

    print(f"Running verification against: {target_spec}")
    engine = DoneEngine(target_spec)
    result = engine.run(is_hook_mode=False)

    print("")
    print("=" * 60)
    if result["passed"]:
        print(f"🎉 TASK [{result['slug']}] VERIFIED COMPLETED (Total: {result['total_duration_ms']:.1f}ms)")
        sys.exit(0)
    else:
        print(f"❌ TASK [{result['slug']}] VERIFICATION FAILED")
        for res in result["results"]:
            status = "✅ PASS" if res["passed"] else "❌ FAIL"
            cached_str = " [CACHED]" if res.get("cached") else ""
            print(f"  {status}{cached_str} {res['claim_id']} ({res['kind']}) - {res['message']}")
        sys.exit(1)

if __name__ == "__main__":
    main()
