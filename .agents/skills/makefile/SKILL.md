---
name: makefile
description: Manage, edit, and execute targets in the root Makefile following the strict <project>-<action> naming convention.
---

# Makefile Management & Execution Skill

This skill defines the standards for editing and using the repository root `Makefile`.

## Naming Convention: `<project>-<action>`

All project-specific targets MUST use the `<project>-<action>` prefix format:

- `<project>`: the module or subsystem (e.g. `api`, `db`).
- `<action>`: the operation (e.g. `build`, `run`, `test`, `migrate`).

Workspace-wide gates are the exception and stay unprefixed: `check`, `typecheck`,
`lint`, `format`, `test`, `install`, `clean`.

### Standard Targets

**Gates**
- `check` — the full quality gate. Chains typecheck, lint, format-check and test
  across every workspace. The mandatory pre-submit command.
- `check-package PKG=@vidya/api` — the same four stages against one workspace.
  The inner loop, not a substitute: a package's own tests say nothing about the
  packages that import it, so `check` still runs before the branch is handed
  over.
- `typecheck` — `tsc --noEmit` in each workspace.
- `lint` / `lint-fix` — ESLint flat config over `modules/`.
- `format` / `format-check` — Prettier.
- `test` — every suite, backed by pg-mem.
- `test-package PKG=… ARGS=…` — one workspace's suites, optionally narrowed.
- `test-postgres-required` — only the suites a real database is required for
  (`*.postgres.spec.ts`). These skip themselves under pg-mem, so they are only
  proved here. Fast enough to belong on a branch.
- `test-postgres` — every suite with a real Postgres behind it. Broader, slower,
  run locally rather than per change.

**Mutation testing**
- `mutate-diff PKG=…` — mutate only what the branch changed, against the merge
  base with main. The per-change run.
- `mutate-full PKG=…` — mutate a whole package. Hours for a package the size of
  the API; run it on a developer machine, not in CI.

**API**
- `api-build` — `nest build` for `@vidya/api`.
- `api-run` — start the API in watch mode.
- `api-test` — Jest for `@vidya/api` only.

**Database**
- `db-start` — start the local Postgres instance.
- `db-schema-drop` — drop the development schema.
- `db-migrate` — run pending migrations.
- `db-testdb-drop` — drop the databases the test suite created. Each checkout
  reuses one, so this is for reclaiming those of worktrees that are gone.
- `seed` — populate the database with development data.

**Housekeeping**
- `install` — install workspace dependencies.
- `clean` — remove `node_modules`, `dist` and build info.

### Variables

- `PKG` — narrows a per-workspace target to one package, e.g.
  `make check-package PKG=@vidya/api`. Defaults to `@vidya/api`.
- `ARGS` — extra arguments for the underlying runner, e.g.
  `make test-package PKG=@vidya/api ARGS='--testPathPattern edu'`.

### Why Targets Delegate to npm

`modules/` is an npm workspace root. Every target shells out through
`npm --prefix modules` (captured once as `$(NPM)`) rather than hardcoding a
package path, so adding a workspace to `modules/package.json` makes it part of
the gate automatically. Per-package targets use `-w @vidya/<name>` for the same
reason.

### Why Scripts Are Not Inlined

Database targets call `./scripts/vidya-*` rather than embedding a docker or
typeorm invocation. The scripts are the developer-facing entry points and work
without `make`; the Makefile is a convenience layer over them, not a second
implementation that can drift.

---

## Rules for Editing the Makefile

1. **Target Prefixing**
   - Every project-specific rule starts with `<project>-`.
   - Workspace-wide gates stay unprefixed.

2. **Declaration & Phony**
   - Always register targets in `.PHONY`:
   ```makefile
   .PHONY: api-build api-run check clean
   ```

3. **Argument Passing**
   - Use `ARGS ?=` to allow parameters from the CLI:
   ```makefile
   api-test:
   	$(NPM) run test -w @vidya/api -- $(ARGS)
   ```

4. **No Duplicated Logic**
   - A target either delegates to an npm script or to a file in `scripts/`. It
     does not reimplement either.

---

## How to Use the Makefile

```bash
# Install workspace dependencies
make install

# The gate — required before the branch is handed over
make check

# The inner loop — one workspace, all four stages
make check-package PKG=@vidya/api

# Individual gates, workspace-wide
make typecheck
make lint
make lint-fix
make format
make test

# One package's tests, optionally narrowed
make test-package PKG=@vidya/api ARGS='--testPathPattern edu'

# Against a real Postgres
make test-postgres-required
make test-postgres

# Mutation testing
make mutate-diff PKG=@vidya/api
make mutate-full PKG=@vidya/api

# API
make api-build
make api-run
make api-test

# Database
make db-start
make db-migrate
make seed
make db-schema-drop
make db-testdb-drop

# Clean build artifacts
make clean
```

## Script Naming

Files in `scripts/` are named `vidya-<area>-<object>-<action>`, and the name
answers "what will this run", not "which flag does it set":

```text
vidya-workspace-build          build every workspace
vidya-workspace-check          one workspace through all four gate stages
vidya-test-suite-run           the test suites, against a named backend
vidya-mutation-suite-run       mutation testing, on the diff or on a package
vidya-db-server-start          start the local Postgres server
vidya-db-schema-drop           drop the development schema
vidya-db-migrations-apply      apply pending migrations
vidya-db-testdb-drop           drop the databases the test suite created
```

All of them are extensionless `#!/usr/bin/env bash` and run without `make`.
A script that takes a mode takes it as an argument, so that two near-identical
scripts do not drift apart.
