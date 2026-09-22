---
name: intent
description: Discovers, grills, and formalizes task intent into a structured .agents/tasks/<slug>/intent.md via prior art web research and a rigorous 5-lens interview (JTBD, Adversarial failure modes, Non-Goals, Pre-Mortem, Invariants). Trigger with "/intent", "intent", "grill intent", or when starting a new feature or task.
---

# Intent Skill (`/intent`)

The `/intent` skill is the **human-and-business layer** of task definition. It clarifies **why** the task is needed, **what** user/business problem it solves, **what** the expected UX behavior is, and **what is strictly out of scope**.

```mermaid
flowchart TD
    UserReq["User Prompt / Feature Idea"] --> Slug["1. Resolve Task Slug & Directory
(.agents/tasks/<slug>/)"]
    Slug --> PriorArt["2. Prior Art Web Search
(Research industry benchmarks & UX patterns)"]
    PriorArt --> Grill5["3. Mandatory 5-Lens Interview
(Ask 5 distinct lens questions via interactive Q&A)"]
    Grill5 --> SaveIntent["4. Author .agents/tasks/<slug>/intent.md
(100% grounded in user answers, Zero Code)"]
    SaveIntent --> Validate{"5. MANDATORY VALIDATION
(python3 -m band --validate-intent <file>)"}
    Validate -->|Exit != 0 (Errors)| FixIntent["Fix intent.md violations"] --> Validate
    Validate -->|Exit 0 (Valid)| NextStep["6. Ready for `/spec` (Technical Architecture)"]
```

## 🚫 Strict Anti-Technical Pollution Rules (Zero Code / Zero Technical Design)

`/intent` MUST NEVER discuss, invent, or record technical implementation details:
- ❌ **NO file names or extensions** (e.g. `.vue`, `.ts`, `.sql`, `.prisma`, `.json`, `.css`).
- ❌ **NO database schema or ORM terms** (e.g. `table`, `column`, `foreign key`, `TypeORM`, `migration`, `schema`).
- ❌ **NO code symbols or architecture terms** (e.g. `DTO`, `interface`, `class`, `function`, `method`, `props`, `endpoint`).
- ❌ **NO HTTP methods or API routes** (e.g. `GET /...`, `POST /...`, `200 OK`).
- ✅ **ONLY user journeys, business goals, UX workflows, visual interaction behaviors, constraints, and non-goals.**

All technical decisions, database schemas, DTOs, migrations, and file-level planning belong exclusively to `/spec`.

## Step 1: Task Slug & Directory Resolution

1. Extract a clean, hyphenated slug from the user request (e.g. `feat-user-auth`, `fix-sync-outbox`).
2. Create the task directory and its workspace subfolders:
   ```bash
   mkdir -p ".agents/tasks/<slug>/artifacts"
   mkdir -p ".agents/tasks/<slug>/scratch"
   ```

## Step 2: Prior Art Web Research

Before questioning the user, execute a web search to discover industry UX patterns, benchmarks, and known edge cases:
1. Search for established UX patterns and product conventions (e.g. `"<feature> UI UX best practices patterns failure modes"`).
2. Gather 3–5 real design patterns, industry leaders, and usability failure modes.
3. Keep findings strictly at the product and UX level (no code snippets).

## Step 3: Mandatory 5-Lens Interview Protocol

Conduct an interactive Q&A interview with the user. The interview **CANNOT be skipped, abbreviated, or compressed**.
You MUST formulate and present questions covering all **5 mandatory lenses**:

| Mandatory Lens | What the Question MUST Clarify |
| :--- | :--- |
| **🔍 Lens 1: JTBD & 80/20 (Core UX & Flow)** | Exact user interaction flow, primary triggers, and visual interaction pattern. |
| **🔍 Lens 2: Adversarial & Limits (Resilience)** | File size/format limits, network drop behavior, retry mechanisms, and empty/huge input handling. |
| **🔍 Lens 3: Negative Requirements (Non-Goals)** | Which related features, screens, or adjacent scopes are strictly OUT OF SCOPE. |
| **🔍 Lens 4: Pre-Mortem (Failure & Recovery)** | What happens if resources are deleted/missing, fallback placeholders, replacement vs removal behavior. |
| **🔍 Lens 5: Invariants (Security & Business)** | Multi-tenancy isolation, user permission boundaries, and visibility rules. |

## Step 4: Author `.agents/tasks/<slug>/intent.md`

Generate `.agents/tasks/<slug>/intent.md` strictly reflecting the user's answers:

```markdown
# Intent: <Title>

**Task Slug:** `<slug>`
**Date:** `<YYYY-MM-DD>`

## 1. Prior Art & Established Solutions
- Source 1: [Name](URL) — Takeaway
- Source 2: [Name](URL) — Takeaway

## 2. Problem & JTBD (The "Why")
- **Root Pain & Trigger:** <User problem in plain language>
- **Target User & Scenario:** <Who uses this and when>
- **Desired Outcome:** <What the user observes upon success>

## 3. Scope Boundaries & Strict Non-Goals
### In Scope (Goals):
- <Clear user-facing capabilities, NO code/file names>
### Strictly Out of Scope (Non-Goals):
- <Explicitly excluded features/screens>

## 4. Adversarial Failure Modes & Mitigations
| Failure Scenario | Impact | Required Mitigation |
| :--- | :--- | :--- |
| Offline / Network Drop | ... | ... |
| Limit Exceeded / Invalid Input | ... | ... |
| Missing / Deleted Resource | ... | ... |

## 5. Invariants & Business Constraints
- Invariant 1: <Business / tenancy rule>
- Invariant 2: <Access / permission rule>
```

## Step 5: Deterministic Validation Gate

Execute the deterministic intent validator:
```bash
python3 -m band --validate-intent .agents/tasks/<slug>/intent.md
```
- If the validator reports errors (exit code != 0), fix `intent.md` immediately until it exits with code 0.
- If the validator passes (exit code 0), the intent is locked and ready for `/spec`.

## Step 6: Hand Off to `/spec`
Inform the user that the intent is validated and ready for technical specification:
> *"Intent validated and locked in `.agents/tasks/<slug>/intent.md`. Run `/spec` to generate the technical architecture and `done.yaml`."*
