---
name: reviewer
description: Specialized quality assurance and code review agent that audits changes against architectural standards, code style, template purity, and gatekeeper status.
---

# Vidya Reviewer Agent

This skill guides the automated and semantic review of changes in `vidya`.

## Review Protocol

The reviewer executes a two-level inspection:

### Level 1: Automated Gatekeeper Execution (Programmatic)
Run the full automated verification suite:

```bash
make check
```

The gate is whatever the project's `check` target chains — typically a type
check, a linter, a formatter check and the test suite. The
[`makefile`](../../makefile/SKILL.md) skill documents the targets this project
actually defines.

**Auto-Rejection Criteria** — reject on the first failure, whichever stage it is:

- **Type check fails** -> REJECT. Type errors are never "fixed later".
- **Linter fails** -> REJECT. The structural rules carry meaning, not taste:
  a file over its line ceiling, branching past the complexity limit, ambient
  clocks or RNG where the project requires a port, a swallowed error, unsorted
  imports. [`architecture.md`](../../../rules/architecture.md) states the limits.
- **Formatter fails** -> REJECT. Formatting is decided once, by the tool.
- **Tests fail** -> REJECT.
- **Mutation score on the diff below the package threshold** -> REJECT. Run
  `make mutate-diff PKG=<package>`. New code the suite does not actually
  exercise is untested code with a coverage number attached to it.

**Never accept a partial gate as a passing gate.**
`make lint` alone proves nothing about types, formatting or behaviour, and a
decomposition that satisfies `max-lines` routinely breaks the build in the same
commit. The gate is `make check` exiting 0, in full.

### Level 2: Semantic & Architectural Inspection (Manual)

Once the programmatic checks pass, read the diff against
[`../../../rules/`](../../../rules/). The rules are the authority on what each
item below means in this project; this stage is the checklist that makes sure
each is actually looked at.

1. **Sizing & decomposition**
   - Is each unit single-responsibility, or did it grow into a grab-bag?
   - Was a limit satisfied by genuine decomposition, or by moving code somewhere
     the linter does not look?
2. **Declared structure**
   - Do files follow the section order, naming and layout the style rule requires?
   - Is a helper named for what it is, rather than dumped in a noun-named file?
3. **Comments and docblocks** — against
   [`comments.md`](../../../rules/comments.md). Reject identifiers from
   documents that are not in the repository (`(D-14)`, `(AC-22f)`, `T-S-35`),
   in comments and in test names alike; defect history narrated in a docblock;
   and any explanation out of proportion to what it explains.
4. **Type and contract placement**
   - Are public types declared and re-exported where the rules say, so consumers
     import from the package entry point rather than reaching inside?
   - Do both sides of a wire contract still agree, including optional fields?
5. **Presentation vs logic**
   - Is business logic absent from templates and views?
   - Does any component read state out of the DOM instead of through its inputs?
   - Are style definitions extracted where the rules require, not inlined?
6. **Domain purity & cohesion**
   - REJECT a service that combines concerns from different bounded contexts.
   - REJECT a service shaped after one endpoint's composite response.
     Composition across domains belongs in the transport layer.
   - REJECT a flat catch-all API module or direct network calls made from
     components. Network access goes through a typed client behind a domain service.
7. **Transport separation & god objects**
   - REJECT a unit that routes, validates, persists and notifies at once.
   - Domain code must not know about the transport it is served over.

### Output Integration
All findings from this stage must be integrated into **Stage 1 (Gatekeeper & Architecture)** of the Unified Report defined in [`../SKILL.md`](../SKILL.md). Do not output a separate standalone report.
