---
name: spec
description: Authors a formal technical specification in .agents/tasks/<slug>/spec.md and a strictly validated done.yaml based on intent.md. Performs codebase reconnaissance, maps blast radius, and defines declarative verification claims. Trigger with "/spec", "spec", "create spec", or "write spec".
---

# Technical Specification Skill (`/spec`)

The `/spec` skill transforms a validated business intent (`intent.md`) into a technical implementation blueprint (`spec.md`) and a machine-readable verification contract (`done.yaml`).

```mermaid
flowchart TD
    ReadIntent["1. Read .agents/tasks/<slug>/intent.md"] --> Recon["2. Codebase Reconnaissance
(Scan existing types/utilities in repository)"]
    Recon --> WriteSpec["3. Author .agents/tasks/<slug>/spec.md
(DTOs, Interfaces, Blast Radius Table)"]
    WriteSpec --> WriteDone["4. Generate .agents/tasks/<slug>/done.yaml
(Declarative Claims: make, mutation, critic)"]
    WriteDone --> ValidateDone{"5. MANDATORY VALIDATION
(python3 -m band --validate)"}
    ValidateDone -->|Exit != 0 (Errors)| FixDone["Fix done.yaml schema/params"] --> ValidateDone
    ValidateDone -->|Exit 0 (Valid)| Complete["6. Spec Locked! Ready for /band"]
```

## Step 1: Locate Active Task and Validate Intent

1. Identify active task folder:
   - If argument passed (e.g. `/spec .agents/tasks/feat-enroll`): use that directory.
   - Otherwise, detect branch slug:
     ```bash
     BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null | tr "/" "-")
     TASK_DIR=".agents/tasks/${BRANCH}"
     ```
2. Validate `.agents/tasks/<slug>/intent.md`:
   - Run the deterministic validator:
     ```bash
     python3 -m band --validate-intent .agents/tasks/<slug>/intent.md
     ```
   - If `intent.md` does not exist or fails validation (exit code != 0), STOP and instruct the user to run `/intent` first. Do NOT proceed to technical design on an invalid intent.

## Step 2: Codebase Reconnaissance (Anti-Hallucination Gate)

Before inventing new classes, types, or utilities, search the codebase:
1. Search existing DTOs, models, and domain entities across the workspace.
2. Check if a similar helper, enum, or event already exists.
3. Note all target packages that will be modified or imported.

## Step 3: Author `.agents/tasks/<slug>/spec.md`

Generate `spec.md` with:
1. **Target Architecture & Interfaces**: exact type signatures and contracts.
2. **Blast Radius Matrix**:
   | Package / Dir | File | Action (Create/Modify) | Downstream Consumers |
   | :--- | :--- | :--- | :--- |
   | `libs/domain` | `src/auth.ts` | Modify | `services/api`, `apps/web` |
3. **Negative Invariants**: explicit architectural prohibitions.

## Step 4: Generate Declarative `.agents/tasks/<slug>/done.yaml`

Generate the machine-readable contract. Select the appropriate pipeline profile (`hardened`, `standard`, `fast`, `docs`) and declare verification claims:

```yaml
slug: <task-slug>
pipeline: hardened               # hardened | standard | fast | docs
target: "modules/libs/domain"

claims:
  # L1: Compilation, Linting, Unit Tests
  - id: l1-check
    tool: make
    target: check-package
    params:
      PKG: "@domain/auth"

  # L2: Mutation Testing (diff mutation against branch base)
  - id: l2-mutation
    tool: mutation
    target: "@domain/auth"
    mode: diff

  # L3: Deterministic Critic Agent Review
  - id: l3-critic
    tool: critic
    runner: "auto"
    checks:
      - "Follows intent.md and respects all Non-Goals"
      - "No unhandled nulls or security bypasses"

  # Optional: Diff Hygiene Check
  - id: l4-hygiene
    tool: hygiene
    no_stubs: true
    no_skipped_tests: true
```

## Step 5: MANDATORY GATE — Validate `done.yaml`

Run the validation command in the terminal:
```bash
python3 -m band --validate .agents/tasks/<slug>/done.yaml
```

* **HARD RULE**: The specification process **CANNOT finish** until this command exits with code `0`.
* If validation reports errors (missing fields, invalid claim tool, bad parameters), fix `done.yaml` and re-run the validation until it returns `✅ done.yaml is VALID`.

## Step 6: Hand Off to Orchestrator or Implementation

Once validated, output:
> *"Specification and contract locked in `.agents/tasks/<slug>/`. Ready for `/band` (or `/coder`)."*
