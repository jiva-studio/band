---
name: coder
description: Implementation agent for features, bug fixes and refactors. Reads the project architecture and coding-style rules, verifies that a valid done.yaml exists before starting, and finishes only when all deterministic quality gates pass.
---

# Coder Agent

The implementation workflow for single-agent tasks and subagent implementation phases. This skill describes the **method**; all project-specific constraints and rules live in [`../../rules/`](../../rules/) and are loaded dynamically.

---

## Phase 0: Pre-Condition Check (MANDATORY)

Before writing any code or modifying any files, verify that the task specification and contract are locked:

1. Locate `.agents/tasks/<slug>/done.yaml`.
2. Execute the validation gate:
   ```bash
   python3 .agents/scripts/done --validate .agents/tasks/<slug>/done.yaml
   ```
3. **HARD STOP RULE**:
   - If `done.yaml` does not exist or fails validation: **DO NOT WRITE CODE**.
   - Stop immediately and instruct the user to run `/intent` and `/spec` first.
   - Implementation is strictly forbidden without a validated contract.

---

## Phase 1: Load the Rules & Task Context

1. Read `.agents/tasks/<slug>/intent.md` (the "Why", Non-Goals, Invariants).
2. Read `.agents/tasks/<slug>/spec.md` (the "What", Interfaces, and Blast Radius).
3. Read project rules in [`../../rules/`](../../rules/) (architecture, coding style, layering).

---

## Phase 2: Design within Constraints

Before modifying files, confirm the change conforms to project rules:
- **Layer boundaries** — transport/controllers do not hold domain logic; domain stays pure.
- **Package boundaries** — cross-package imports go through public entry points.
- **No swallowed errors** — handle, rethrow, or log explicitly.

---

## Phase 3: Implement (TDD)

1. **Red Phase**: If writing tests, prove they fail for the right reason first.
2. **Green Phase**: Implement minimal clean production logic until tests pass.
3. **Wire Phase**: Re-export public components/types from barrel index files and apply localization strings where applicable.

---

## Phase 4: Local Quality Loop

While working, run the narrow test and check commands specified for the target workspace.
Verify locally that all newly added behavior is covered by tests that fail if the logic is altered or mutated.

---

## Phase 5: Task Completion & Stop-Hook Verification

When you finish implementation:
1. Verify with the deterministic verification harness:
   ```bash
   python3 .agents/scripts/done --spec .agents/tasks/<slug>/done.yaml
   ```
2. The deterministic **Stop-Hook** will automatically verify all claims in `done.yaml` (compilation, unit tests, mutation score, critic checks). If any claim fails, review the exact error details and repair the implementation.
