# 🥁 Band

> **Deterministic Multi-Agent TDD Harness & Verification FSM for Autonomous Software Engineering.**

`Band` is a lightweight, zero-dependency orchestration harness and external verification state machine (FSM) that drives AI agents through strict Test-Driven Development (TDD) pipelines, mutation analysis, adversarial audits, and deterministic quality gates.

---

## 🌟 Why Band?

Autonomous LLM agents commonly suffer from two critical failure modes:
1. **Premature Completion:** Declaring a task "Done" when tests fail, edge cases are unhandled, or files are left in broken states.
2. **Phase Contamination:** Writing tests and implementation simultaneously, weakening assertions to make broken code pass, or cheating by modifying test suites during the green phase.

`Band` eliminates both issues by enforcing an **external, deterministic state machine**:
* **Phase Isolation:** Subagents are constrained to specific roles (`Test Author`, `Code Implementer`, `Mutation Runner`, `Adversarial Reviewer`). File modifications outside their designated boundaries are blocked at the git level.
* **External Stop-Hook Interception:** An agent cannot exit until the active stage satisfies its declarative claims. When an agent attempts to stop early, the hook interrupts and returns the exact failures.
* **Declarative Claims Engine:** Verification criteria (`make` targets, mutation testing, AI adversarial checks, diff hygiene) are defined in portable YAML manifests.
* **Zero Dependencies:** Pure Python 3 standard library (`subprocess`, `json`, `hashlib`, `unittest`). No external daemons, package managers, or server runtimes required.

---

## 🏗 System Architecture & FSM

```
                  ┌──────────────────────────────────────────────┐
                  │              /band Orchestrator              │
                  └──────────────────────┬───────────────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  [red-phase]                     [green-phase]                   [mutation-gate]
  Test Author                    Code Implementer                 Mutation Runner
  • Write tests                  • Minimal code only              • Diff-scoped Stryker
  • Forbid code edits            • Forbid test edits              • Surface mutants
  • Prove Red failure            • Turn tests Green               • Fail if score < 80%
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         │
                        ┌────────────────┴────────────────┐
                        ▼                                 ▼
              [adversarial-review]                  [gatekeeper]
              Adversarial Reviewer                   Quality Gate
              • Break invariants                     • Run L1-L4 done.yaml
              • Catch null/type leaks                • Check diff hygiene
              • Eliminate mutants                    • Pass/Fail Decision
```

---

## 🚀 Installation & Quickstart

Install `Band` into any repository with a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/jiva-studio/band/main/install.sh | bash
```

This creates the `.agents/` folder structure in your repository:

```text
.agents/
├── hooks.json             # Stop-hook configuration
├── pipelines/             # Declarative stage definitions
│   ├── standard.yaml      # Red -> Green -> Refactor -> Gate
│   ├── hardened.yaml      # Red -> Green -> Mutation -> Review -> Gate
│   ├── fast.yaml          # Green -> Gate
│   └── docs.yaml          # Documentation generation & verification
├── scripts/
│   └── done/              # Verification FSM engine & claim adapters
└── skills/
    ├── band/SKILL.md      # Multi-agent orchestrator skill (/band)
    ├── coder/SKILL.md     # Single-task implementation skill (/coder)
    ├── spec/SKILL.md      # Technical specification authoring (/spec)
    └── intent/SKILL.md    # Requirements discovery & interview (/intent)
```

---

## 📋 Defining Task Claims (`done.yaml`)

Every task defines its verification criteria in `.agents/tasks/<slug>/done.yaml`:

```yaml
slug: feat-media-picker
target: "modules/apps/admin"
pipeline: "hardened"

claims:
  # L1: Compilation, Linting, & Unit Tests
  - id: l1-admin-check
    kind: make
    target: check-package
    params:
      PKG: "@vidya/admin"

  # L2: Mutation Testing (Stryker diff against modified files)
  - id: l2-mutation
    kind: mutation
    target: "@vidya/admin"
    mode: diff

  # L3: AI Adversarial Critic Review
  - id: l3-critic
    kind: critic
    checks:
      - "Follows intent.md and respects all Non-Goals"
      - "No unhandled nulls, temporary blob URLs, or security bypasses"

  # L4: Clean Diff Hygiene
  - id: l4-hygiene
    kind: hygiene
    no_stubs: true
    no_skipped_tests: true
```

---

## 🕹 CLI Usage

### 1. Initialize Pipeline for a Task
```bash
python3 -m .agents.scripts.done --start-pipeline .agents/tasks/<slug>/done.yaml
```

### 2. Inspect Active Pipeline State
```bash
python3 -m .agents.scripts.done --status .agents/tasks/<slug>/done.yaml
```

### 3. Run Claims Verification Directly
```bash
python3 -m .agents.scripts.done --spec .agents/tasks/<slug>/done.yaml
```

### 4. Execute as Agent Stop-Hook
```bash
python3 -m .agents.scripts.done --hook
```

---

## 🛡 Stop-Hook & Circuit Breaker

When registered in `.agents/hooks.json`, the Stop-hook intercepts the agent's exit attempt:

```json
{
  "hooks": {
    "Stop": [
      {
        "name": "done-gate",
        "command": "python3 -m done --hook",
        "timeout": 180000
      }
    ]
  }
}
```

* **If Claims Fail:** Returns `{"decision": "continue", "reason": "⛔ Stage [red-phase] claims not satisfied:\n..."}` to force the agent back to work.
* **If Claims Pass:** Advances the FSM to the next stage and returns instructions for the incoming subagent.
* **Circuit Breaker:** If a specific claim fails repeatedly (3+ consecutive identical failures), the circuit breaker trips with diagnostic guidance to prevent infinite loops.

---

## 🧪 Self-Testing

To run the complete unit and integration test suite:

```bash
make check
# or:
make self-test
```

---

## 📄 License

MIT © [Jiva Studio](https://github.com/jiva-studio)
