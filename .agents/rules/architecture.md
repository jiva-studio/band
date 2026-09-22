# Architecture & Repository Guidelines

This document outlines the core architectural principles of the `vidya` project.

---

## 1. Monorepo Organization

```text
vidya/
├── Makefile                            # Build and quality-gate entry points (<project>-<action>)
├── scripts/                            # Developer entry points invoked by the Makefile
├── docs/                               # Product docs, ADRs, API reference, ER diagram
└── modules/
    ├── package.json                    # npm workspaces: libs/*, apps/*, services/*
    ├── tsconfig.base.json              # Single compiler contract, owns the @vidya/* path map
    ├── eslint.config.js                # Flat config: structural limits and purity rules
    ├── prettier.config.mjs             # semi: false, singleQuote, printWidth 100
    ├── libs/                           # Reusable libraries (zero application logic)
    │   ├── domain/                     # Permission model and domain constants (0 dependencies)
    │   ├── entities/                   # TypeORM entities for the Vidya schema
    │   └── protocol/                   # Wire contracts (DTO shapes, routes, error codes)
    ├── apps/                           # User-facing clients
    │   ├── admin/                      # School administration console
    │   └── mobile/                     # Student mobile application
    └── services/                       # Deployable backend processes
        ├── api/                        # NestJS REST API — the application
        ├── database/                   # TypeORM datasource and migrations
        ├── gateway/                    # Edge routing
        └── seeder/                     # Development data seeding
```

The three buckets are a contract, not a suggestion:

- **`libs/`** holds code with no knowledge of transport or deployment. A lib must
  compile and be testable without a running server or database.
- **`apps/`** holds user-facing clients. They consume `libs/` and talk to
  `services/` over the wire.
- **`services/`** holds processes that get deployed. They may depend on `libs/`,
  never on `apps/` and never on each other's internals.

### Dependency Flow Rules
- **Libs must NEVER depend on Apps or Services.** Libraries are sharable building blocks.
- **`domain`** has 0 dependencies — constants and the permission algebra only.
- **`protocol`** has 0 runtime dependencies. It describes the wire, it does not implement it.
- **`entities`** depends only on `typeorm` decorators.
- **Apps and Services** depend on `domain`, `protocol`, `entities` — never the reverse.

Cross-package imports always use the `@vidya/*` specifier declared in
`modules/tsconfig.base.json`. Deep relative paths that reach across package
boundaries (`../../libs/entities/user`) are forbidden: they bypass the public
entry point and defeat the dependency rules above.

---

## 2. Shared Contracts & Wire Formats

- Everything crossing the network boundary is declared in `@vidya/protocol`.
- A TypeORM entity is **not** a wire format. Never return an entity from a
  controller. Map it to a DTO through the mappers in `mappers/`.
- DTOs carry `class-validator` decorators so the validation contract lives with
  the shape it validates.

---

## 3. NestJS Layering (services/api)

The API is organised by bounded context (`auth/`, `edu/`), and each context
repeats the same layered vocabulary:

```text
src/<context>/
├── controllers/      # Transport: parse the request, dispatch, shape the response
├── services/         # Domain logic. No `@Res()`, no HTTP status codes, no Express types
├── dto/              # Request/response shapes with class-validator decorators
├── mappers/          # Entity <-> DTO translation
├── pipes/            # Request-scoped resolution and existence checks
├── validations/      # Cross-cutting domain invariants
└── <context>.module.ts
```

- **Transport does not dictate domain.** A service must never be modelled around
  the shape of one endpoint's response. When an endpoint needs data from several
  domains, compose it in the controller by orchestrating separate services.
- **Domain purity.** One service, one bounded context. Combining unrelated
  concerns (mail delivery, token revocation, school creation) into one class is
  forbidden.
- **No god objects.** A class that routes, validates, persists and notifies is a
  refactor, not a design.
- `shared/` holds genuinely cross-context infrastructure (datasources,
  decorators, the Redis client). It is not a junk drawer for anything awkward.

---

## 4. Deterministic Pure Logic & Ports

In `libs/` and in any pure helper:
- **Clocks & timers as ports**: `Date.now()`, `new Date()`, `setTimeout` and
  `setInterval` are forbidden. Time has a lifetime tests must control — inject a
  clock or pass timestamps explicitly.
- **Randomness as ports**: `Math.random()` is forbidden. Inject a randomness
  port so tests can make the sequence deterministic and so security-sensitive
  values can be sourced from a CSPRNG.
- **No error swallowing**: empty `catch (err) {}` blocks are forbidden. Handle
  the error, rethrow it, log it, or write a statement and a comment explaining
  why it is safely ignored.

These are enforced by `no-restricted-syntax` and `no-empty` in
`modules/eslint.config.js`.

---

## 5. Structural Limits

Enforced by ESLint across the workspace:

- **Total file size**: max **350 lines** (blank lines and comments excluded).
- **Cyclomatic complexity**: max **10** per function. Past that, decompose into
  dispatch tables, lookup maps, or focused pure helpers.
- **Control-flow nesting**: max **3** levels. Flatten with guard clauses or
  extract a sub-function.

Spec files are exempt from the line limit: a long, explicit test is better than a
clever short one.
