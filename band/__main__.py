import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure package root is in sys.path
_pkg_root = str(Path(__file__).resolve().parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from band.yaml_loader import load_yaml
from band.config import TASKS_DIR, REPO_ROOT
from band.validator import validate_done_manifest, validate_intent_file
from band.pipeline_loader import validate_pipeline_manifest
from band.engine import DoneEngine
from band.pipeline_runner import PipelineRunner


def find_active_task_spec() -> Optional[Path]:
    try:
        import subprocess
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True
        )
        branch = res.stdout.strip().replace("/", "-")
        if branch:
            for name in ["done.yaml", "band.yaml"]:
                if (TASKS_DIR / branch / name).exists():
                    return TASKS_DIR / branch / name
    except Exception:
        pass

    if TASKS_DIR.exists():
        candidates = []
        for name in ["done.yaml", "band.yaml"]:
            candidates.extend(TASKS_DIR.glob(f"*/{name}"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return candidates[0]

    return None


def resolve_spec_path(arg_val: str) -> Optional[Path]:
    p = Path(arg_val).resolve()
    if p.is_file():
        return p
    if p.is_dir():
        for name in ["done.yaml", "band.yaml", "intent.md"]:
            if (p / name).exists():
                return p / name
    for name in ["done.yaml", "band.yaml", "intent.md"]:
        if (TASKS_DIR / arg_val / name).exists():
            return TASKS_DIR / arg_val / name
    return None


def main():
    parser = argparse.ArgumentParser(description="Band — Deterministic task completion harness and verification engine.")
    parser.add_argument("--validate", type=str, help="Validate a done.yaml / band.yaml manifest against schema.")
    parser.add_argument("--validate-intent", type=str, help="Validate an intent.md file for anti-pollution and structural completeness.")
    parser.add_argument("--validate-pipeline", type=str, help="Validate a pipeline.yaml file against schema.")
    parser.add_argument("--pipeline", type=str, help="Specify or override pipeline profile name (e.g. hardened, standard, fast, docs).")
    parser.add_argument("--start-pipeline", type=str, nargs="?", const="", help="Initialize pipeline FSM for a task.")
    parser.add_argument("--status", type=str, nargs="?", const="", help="Show pipeline FSM status for a task.")
    parser.add_argument("--spec", type=str, help="Run verification against specific spec path.")
    parser.add_argument("--task", type=str, help="Run verification for specific task slug in tasks/<slug>.")
    parser.add_argument("--hook", action="store_true", help="Run in Stop-hook mode with JSON stdin/stdout.")

    args = parser.parse_args()

    # 1. Validate Intent Mode
    if args.validate_intent:
        p = resolve_spec_path(args.validate_intent)
        if not p or not p.exists():
            print(f"Error: intent.md file not found at {args.validate_intent}", file=sys.stderr)
            sys.exit(1)

        is_valid, errors = validate_intent_file(p)
        if is_valid:
            print(f"✅ intent.md at {p.name} is VALID (clean of technical pollution).")
            sys.exit(0)
        else:
            print(f"❌ intent.md validation failed with {len(errors)} error(s):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

    # 2. Validate pipeline mode
    if args.validate_pipeline:
        p = Path(args.validate_pipeline).resolve()
        if not p.exists():
            print(f"Error: Pipeline file not found at {p}", file=sys.stderr)
            sys.exit(1)
        try:
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

    # 3. Validate manifest mode
    if args.validate:
        p = resolve_spec_path(args.validate)
        if not p or not p.exists():
            print(f"Error: Manifest file not found at {args.validate}", file=sys.stderr)
            sys.exit(1)
        try:
            data = load_yaml(p)
        except Exception as e:
            print(f"YAML Syntax Error: {str(e)}", file=sys.stderr)
            sys.exit(1)

        is_valid, errors = validate_done_manifest(data)
        if is_valid:
            print(f"✅ manifest at {p.name} is VALID.")
            sys.exit(0)
        else:
            print(f"❌ manifest schema validation failed with {len(errors)} error(s):", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

    # 4. Start Pipeline Mode
    if args.start_pipeline is not None:
        target_spec = resolve_spec_path(args.start_pipeline) if args.start_pipeline else find_active_task_spec()

        if not target_spec or not target_spec.exists():
            print(f"Error: Could not locate done.yaml or band.yaml for starting pipeline.", file=sys.stderr)
            sys.exit(1)

        runner = PipelineRunner(target_spec)
        state = runner.init_pipeline(pipeline_override=args.pipeline)
        print(f"🚀 Pipeline [{state['pipeline']}] INITIALIZED for task [{state['slug']}].")
        print(f"👉 Current Stage: [{state['current_stage_id']}]")
        print(f"Active hooks will drive and gate each stage transition.")
        sys.exit(0)

    # 5. Status Mode
    if args.status is not None:
        target_spec = resolve_spec_path(args.status) if args.status else find_active_task_spec()

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

    # 6. Hook mode (Driven by external Stop-hook)
    if args.hook:
        try:
            if (
                os.environ.get("DONE_GATE_DISABLE") == "1"
                or os.environ.get("FORCE_STOP") == "1"
                or os.environ.get("DONE_BYPASS") == "1"
                or os.environ.get("BAND_DISABLE") == "1"
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

    # 7. Direct execution mode
    target_spec = None
    if args.spec:
        target_spec = resolve_spec_path(args.spec)
    elif args.task:
        target_spec = resolve_spec_path(args.task)
    else:
        target_spec = find_active_task_spec()

    if not target_spec or not target_spec.exists():
        print("No active spec found. Provide --spec <path> or --task <slug>.", file=sys.stderr)
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
