# 📋 Task Specification: <Task Name>

**Branch / Worktree**: `<branch-slug>`  
**Status**: `[ IN_PROGRESS | COMPLETED | FAILED ]`  
**Target Modules**: `[ e.g. modules/libs/protocol, modules/services/api, modules/apps/admin ]`  

---

## 1. Business Context & User Value (JTBD)

### Problem Statement & Trigger
- **Trigger**: <When and under what specific circumstances does the user encounter this problem?>
- **Pain Point**: <What is the core friction, confusion, or inefficiency the user experiences?>
- **Current Workaround**: <How does the user cope with this today? (e.g. manual page refresh, parsing raw terminal logs, multi-step copy-pasting)?>

### User Journey & Workflow (Before vs After)
- **Before**: <Step-by-step description of the suboptimal user workflow>
- **After**: <Step-by-step description of the streamlined, intuitive workflow once shipped>

### Value & Success Criteria
- **Primary Value Delivered**: <Clear statement of user/business benefit (e.g. zero stale search overwrites, 80% fewer clicks)>
- **Observable Verification**: <How do we prove the feature achieved its business intent at runtime?>

---

## 2. Goals, Non-Goals & Scope Guardrails (The 80/20 Rule)

### In-Scope Goals
- <Core functional deliverable 1>
- <Core functional deliverable 2>

### Non-Goals (Strict Scope Boundaries / Anti-Rabbit-Holes)
- <Explicit declaration of adjacent features, legacy refactors, or custom configuration options that will NOT be touched>
- <e.g. Do not restructure the permission model; do not touch the offline sync engine>

---

## 3. Observable Acceptance Criteria (AC)

<!-- Formulate criteria as machine/human-observable facts and assertions -->
- [ ] **AC-1**: `<e.g. Triggering rapid search inputs aborts preceding in-flight requests via AbortController>`
- [ ] **AC-2**: `<e.g. Active loading spinner resets to false immediately on error or abort>`
- [ ] **AC-3**: `<e.g. migration 009_enrollments.sql applies idempotently and is recorded in schema_migrations>`
- [ ] **AC-4**: `<e.g. All new UI states provide distinct visual feedback for Loading, Empty, and Error states>`

---

## 4. Technical Risks, Failure Modes & Edge Cases

| Risk / Failure Vector | Impact | Mitigation Strategy in Code |
| :--- | :---: | :--- |
| **Dependency Outage / Timeout** | High | <e.g. Graceful fallback banner + AbortSignal timeout after 5s> |
| **Race Conditions / Rapid Clicks** | High | <e.g. Request sequencing token + cancel prior promise> |
| **Malformed / Empty Input** | Medium | <e.g. Early return on empty diff string, zero-allocation guard> |
| **Wire Contract / Nullable Drift** | Medium | <e.g. DTO and `@vidya/protocol` type agree; guards for optional fields under `strictNullChecks: false`> |

---

## 5. Blast Radius & Target Files

| File | Action | Purpose & Scope |
| :--- | :---: | :--- |
| `<path/to/file1.ts>` | `[ CREATE | MODIFY | DELETE ]` | <Description of changes and responsibilities> |
| `<path/to/file2.spec.ts>` | `[ CREATE | MODIFY ]` | <Reproduction or adversarial stress test> |

---

## 6. Phased Execution Plan

### Phase 1: Test-Driven Red Phase (Failing Test First)
- [ ] **Step 1.1**: Author targeted failing test `<test-file>` asserting the requirement.
- [ ] **Step 1.2**: Execute test runner and verify non-zero exit code (`exit != 0`).

### Phase 2: Implementation (Green Phase)
- [ ] **Step 2.1**: Implement minimal domain logic in target files.
- [ ] **Step 2.2**: Execute targeted test runner and verify passing exit code (`exit == 0`).

### Phase 3: Wiring & Integration (Anti-Orphan Phase)
- [ ] **Step 3.1**: Re-export new components/composables/types via local `index.ts` and root `src/index.ts`.
- [ ] **Step 3.2**: Register controllers in the NestJS module / pages in the Vue router.
- [ ] **Step 3.3**: Verify event listeners, props, and UI feedback bindings are live.

### Phase 4: Cleanliness & Gatekeeper
- [ ] **Step 4.1**: Verify zero `TODO`, `FIXME`, or stub mock returns in production code paths.
- [ ] **Step 4.2**: Execute quality gate: `<make check / targeted gate>`.

---

## 7. Verification Gate (Final Command)

```bash
# Exact command line to run for complete validation before review
<e.g. npm --prefix modules run test -w @vidya/api -- <target>.spec.ts && make check>
```
