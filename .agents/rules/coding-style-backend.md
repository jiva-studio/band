# Backend (NestJS / TypeScript) Coding Style & Guidelines

This document defines the coding standards for backend code in `vidya`
(NestJS 10, TypeORM, TypeScript 5).

---

## 1. Project Structure

Backend code lives under `modules/services/`. Each service is an npm workspace
named `@vidya/<name>` and extends `modules/tsconfig.base.json`.

```text
modules/services/
├── api/                                  # The application (NestJS)
│   └── src/
│       ├── main.ts                       # Bootstrap: pipes, Swagger, listen
│       ├── app.module.ts                 # Composition root
│       ├── configs/                      # @nestjs/config factories, one per concern
│       ├── auth/                         # Bounded context: identity, OTP, tokens
│       ├── edu/                          # Bounded context: schools, roles, users
│       └── shared/                       # Cross-context infrastructure only
├── database/                             # TypeORM datasource + migrations
├── gateway/                              # Edge routing
└── seeder/                               # Development data seeding
```

Within a bounded context the layers are `controllers/` (transport),
`services/` (domain), `dto/`, `mappers/`, `pipes/`, `validations/`. See
[`architecture.md`](./architecture.md) for what each layer may and may not do.

---

## 2. Layer Discipline

### Controllers (transport)
- Parse the request, delegate, shape the response. Nothing else.
- Every route carries its `@ApiOperation` / `@ApiResponse` metadata — the Swagger
  document is part of the contract, not an afterthought.
- Authorization is expressed with the `@Authentication`/permission decorators,
  never with hand-rolled `if (user.role === ...)` inside the handler body.
- A controller **never** returns a TypeORM entity. Map to a DTO.

### Services (domain)
- No `Request`, `Response`, `@Res()`, or HTTP status codes. A domain service that
  imports from `express` is a layering bug.
- Throw domain errors; let filters and pipes translate them to HTTP.
- Injected dependencies are declared `private readonly` in the constructor.

### DTOs
- One class per request/response shape, decorated with `class-validator`.
- Validation lives on the DTO, not in the controller body.
- Shapes shared with clients belong in `@vidya/protocol`; the DTO implements the
  protocol type rather than redefining it.

### Entities
- `@vidya/entities` describes the database, nothing more. No business methods, no
  service imports, no DTO knowledge.

---

## 3. TypeScript Standards

### Async & Errors
- `async`/`await` throughout. Never mix `.then()` chains into an async function.
- Never discard a rejected promise. Every `await` is either handled or allowed to
  propagate deliberately.
- Empty `catch` blocks are forbidden (`no-empty`). Handle, rethrow, log, or write
  a comment explaining why the error is safely ignored.
- Wrap errors with context rather than rethrowing a bare `err` from deep in a
  call stack.

### Types
- `any` is tolerated only at framework seams (decorator metadata, TypeORM
  internals). It is never the type of a domain value.
- Public functions in `libs/` are explicitly typed. Inference is fine locally.
- Prefer `unknown` plus a narrowing guard over `any` when parsing external input.

### Imports
- Sorted and grouped by `simple-import-sort` — run `make lint-fix` rather than
  reordering by hand.
- Cross-package imports use `@vidya/*`. Reaching across a package boundary with
  a relative path is forbidden.

---

## 4. Determinism & Ports

In `libs/` and in pure helpers, ambient non-determinism is forbidden and
enforced by `no-restricted-syntax`:

- `Date.now()`, `new Date()` — inject a clock port.
- `setTimeout`, `setInterval` — inject a scheduler port.
- `Math.random()` — inject a randomness port.

`Math.random()` additionally must never produce a security-sensitive value. OTP
codes, tokens and secrets come from `crypto.randomInt` / `crypto.randomBytes`
behind a port, so the source is both deterministic under test and cryptographically
sound in production.

---

## 5. Structural Limits

Enforced by ESLint:

- **Total file size**: max **350 lines** (`max-lines`, blanks and comments excluded).
- **Cyclomatic complexity**: max **10** per function (`complexity`).
- **Control-flow nesting**: max **3** levels (`max-depth`).

When a controller or service approaches the ceiling, split by responsibility —
`schools.controller.ts` and `schoolConfigs.controller.ts` rather than one file
holding both. Spec files are exempt from the line limit.

---

## 6. Comments

A comment earns its place by saying something the code cannot. Restating the
next line in English is noise that goes stale; explaining *why* a rule exists,
or what a reader would otherwise get wrong, is worth the space.

- **One line.** If the thought does not fit on one line, it is usually an
  explanation that belongs in the rule document or the commit message. Reach for
  a second line only when the reader genuinely needs it there.
- **A blank line above.** A comment introduces what follows; it must not look
  glued to the line before it.
- **Consistent within a group.** Do not document one field, enum member or
  branch and leave its siblings bare — an uneven run reads as though the
  undocumented ones were forgotten. Either annotate the whole group, or let the
  single comment say something that applies to that member alone.
- **No commented-out code.** Git remembers it.
- Prose above a symbol uses `//`. Reserve `/** */` for documentation a consumer
  of the package reads: exported protocol types and public service methods.

---

## 7. Testing

- Unit specs sit next to the code as `*.spec.ts`; controller suites live in
  `specs/` beside the controller with a shared `context.ts` fixture.
- `*.test.*.spec.ts` are in-process tests against a `pg-mem` datasource;
  `*.e2e.*.spec.ts` drive the HTTP surface through `supertest`.
- A test names the behaviour it protects, not the method it calls.

---

## 8. Formatting & Verification

- Prettier owns formatting: `semi: false`, `singleQuote: true`, `printWidth: 100`,
  `trailingComma: 'all'`. Never hand-format around it.
- Run `make check` from the repository root before submitting changes. It is the
  only command that covers the whole workspace:
  1. `make typecheck` — `tsc --noEmit` in every workspace
  2. `make lint` — ESLint flat config (structural limits, purity rules, import order)
  3. `make format-check` — Prettier
  4. `make test` — Jest
- Individual gates exist (`make typecheck`, `make lint`, `make api-test`) for a
  fast inner loop, but a task is not complete until `make check` exits 0.
