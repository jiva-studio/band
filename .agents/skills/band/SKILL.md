---
name: band
description: Hook-driven multi-agent pipeline orchestrator for autonomous feature implementation and deterministic verification. Dynamically loads workflow stages defined in .agents/pipelines/<name>.yaml and lets external harness hooks drive and gate transitions. Trigger with "/band", "band", "orchestrate band", or "run band".
---

# Hook-Driven Multi-Agent Pipeline Orchestrator (`/band`)

The `/band` skill is a **deterministic, hook-driven workflow orchestrator**. Rather than relying solely on LLM prompt instructions that can be skipped or hallucinated, `/band` initializes the state machine (`state.json`), and the **external harness hook** (`python3 .agents/scripts/done --hook` in `.agents/hooks.json`) actively intercepts actions, runs deterministic checks, blocks premature stopping, and pushes the agent from stage to stage.

```mermaid
flowchart TD
    Trigger["User: /band"] --> InitFSM["1. Initialize Pipeline FSM\n(python3 .agents/scripts/done --start-pipeline)"]
    
    InitFSM --> HookLoop["2. External Hook Loop (.agents/hooks.json)\n- Hook intercepts turn completion / stop attempts\n- Evaluates active stage condition in pipeline.yaml\n- Runs verification tools & diff mutation analysis\n- Injects next stage directive or blocks completion"]
    
    HookLoop --> StageAgent["Agent / Subagent Action\n- Executes current stage role (Author / Implementer / Reviewer)\n- Enforces forbidden edits & boundaries"]
    
    StageAgent --> HookLoop
    
    HookLoop -->|All Stages Pass & Gatekeeper Green| GatePass["3. Gatekeeper Verified\n- Hook returns decision: allow\n- 100% claims verified & cached"]
    
    GatePass --> Handover["4. Final Handover to User"]
```

---

## 1. How the Hook Drives the Pipeline

1. **Activation**:
   When `/band` is invoked, start the pipeline for the active task:
   ```bash
   python3 .agents/scripts/done --start-pipeline
   ```
   This loads the configured pipeline profile (from `done.yaml` or `.agents/pipelines/`), creates `artifacts/state.json`, and outputs the initial stage directive.

2. **External Hook Enforcement (`.agents/hooks.json`)**:
   Every time the agent completes an action or attempts to finish a turn, the harness hook executes:
   ```bash
   python3 .agents/scripts/done --hook
   ```
   - **Blocks early exit**: Returns `{"decision": "continue", "reason": "..."}` if current stage requirements are unmet.
   - **Evaluates stage transitions**:
     - *Red Phase*: Proves tests exist and fail (Red) before allowing implementation.
     - *Green Phase*: Confirms test files were not modified and test suite turns Green.
     - *Mutation Gate*: Analyzes diff mutations, caches results (`state.json`), and extracts surviving mutants.
     - *Adversarial Review*: Directs reviewer to surviving mutants; routes fix loops until killed.
   - **Advances the FSM**: Updates `current_stage_idx` and provides the exact directive for the next subagent role.

3. **Final Gatekeeper & Completion**:
   When the final gatekeeper stage verifies all claims in `done.yaml`, the hook issues `{"decision": "allow"}` and marks the pipeline `status: "completed"`.

---

## 2. Dynamic Stage Execution Guidelines

When working within the pipeline directed by the hook:
- Follow the high-priority directive emitted by the hook for the active stage.
- For subagent stages: spawn specialized subagents (`invoke_subagent`) matching the stage's `role` and context.
- For tool verifications: let the hook and `.agents/scripts/done` run deterministic checks and leverage content-addressed caching.
- Check current status anytime with:
  ```bash
  python3 .agents/scripts/done --status
  ```
