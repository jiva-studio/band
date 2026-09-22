# Frontend Coding Style & Component Guidelines

This document defines the strict coding conventions for all frontend code in `vidya` (Vue 3, TypeScript, Tailwind CSS v4).

> **Status.** `modules/apps/mobile` holds the student application, ported from
> `classroom-mobile` and live under the workspace gate. `modules/apps/admin` is
> still greenfield. These conventions bind both: the mobile app was brought to
> them as part of its port, and the first commit of admin UI must satisfy them.
>
> One rule is switched off for the mobile app:
> `vue/no-deprecated-slot-attribute`. Ionic's components are custom elements and
> take their children through the real `slot` attribute.
>
> **Enforcement.** The stock rules below (`vue/*`, `max-lines`, `complexity`,
> `max-depth`, `no-empty`, `no-restricted-syntax`) are live in
> `modules/eslint.config.js` today. The `vidya/*` rules are a local ESLint plugin
> that has not been written yet; until it exists they are reviewer-enforced, and
> `.agents/skills/review/` treats a violation as a finding.

---

## 1. Sizing Limits & Structural Boundaries

To prevent monoliths ("God Components"), the following hard limits are enforced by ESLint:

- **`<template>` block**: Maximum **100 lines**.
- **`<template>` nesting depth**: Maximum **4 levels** (enforced by ESLint `vue/max-template-depth: ['error', { maxDepth: 4 }]`).
- **`<script>` block**: Maximum **300 lines**.
- **Total file size**: Maximum **350 lines**.

If a component approaches these limits, it MUST be decomposed:

1. Extract subcomponents for distinct visual groups (e.g. `DiffFloats.vue`).
2. Extract headless state and interaction logic into composables (e.g. `useKeyNavigation.ts`, `useSurfaceMotion.ts`).
3. Break deeply nested hierarchies into dedicated shallow subcomponents (e.g. `DiffCodeRow.vue`, `DiffFoldRow.vue`).

---

## 2. Template Purity & Architecture

The template must be purely declarative. The following patterns are strictly forbidden and enforced by AST linter rules:

1. **NO Nested Ternaries**:
   ```vue
   <!-- FORBIDDEN (will fail ESLint): -->
   :tokens="row.kind === 'code' ? (row.change === 'added' ? newTokens[...] :
   oldTokens[...]) : undefined"

   <!-- REQUIRED: -->
   :tokens="tokensForRow(row)"
   ```
2. **NO Inline Logical Expressions in Event Handlers**:
   ```vue
   <!-- FORBIDDEN (will fail ESLint): -->
   @note:edit="row.kind === 'note' && remarks.saveEdit(row.annotationId,
   $event)"

   <!-- REQUIRED: -->
   @note:edit="onNoteEdit(row, $event)"
   ```
3. **NO Direct DOM State Extraction**:
   Components must never inspect the DOM (e.g. `querySelector('.input')?.value`) to read state. State must flow through props, emits, and models.
4. **NO Polymorphic God Components (Kind Splitting Principle)**:
   Components that render multiple distinct variants via `v-if/else-if="entity.kind === '...'"` (e.g. `row.kind === 'code' | 'fold' | 'note' | 'composer'`) MUST NOT inline all branch markup, slots, and heavy computations into one file.
   - The parent component is only a shallow dispatcher (depth $\le 4$).
   - Each variant MUST be extracted into a focused subcomponent (e.g. `DiffCodeRow`, `DiffFoldRow`, `DiffNoteRow`, `DiffComposerRow`).
   - Domain-specific computed properties (such as syntax token slicing or span calculations) must live exclusively in the child component that needs them.
   - Heavy dependencies (such as text editors, composers, or modal forms) must NOT be imported into components rendering high-frequency rows like code lines.
5. **NO Dynamic Class Interpolations in Template**:
   Do NOT construct inline class arrays with template literals and boolean conditionals in the template:
   ```vue
   <!-- FORBIDDEN: -->
   :class="[ `cp-row--${row.kind}`, row.kind === 'code' &&
   `cp-row--${row.change}`, phase && `cp-row--${phase}`, ]"

   <!-- REQUIRED: -->
   :class="rowClasses"
   ```
   Always extract class calculations to a `computed(() => [...])` in the component's `State` section.
6. **NO Loops or Heavy Algorithmic Logic inside `computed()` in Vue Components**:
   - `computed()` properties in Vue components must be thin declarative projections (typically 1–3 lines).
   - Iterative loops (`for`, `for...of`, `while`), array index slicing math, string parsing, and complex transformations are strictly forbidden in `.vue` files and enforced by ESLint `no-restricted-syntax`.
   - Pure domain calculations MUST be extracted to dedicated functions in `model/` (e.g. `model/tokens.ts`) or `lib/` with their own unit tests (`.spec.ts`).

---

## 3. Function Naming

1. **A function is named with a verb**:
   A name says what calling it does. A noun, an adjective or a participle names
   the answer instead of the act, and only reads as a function because of the
   file it happens to sit in.
   ```ts
   // FORBIDDEN
   const keep = (file: File) => …          // a verb is missing
   const kindOf = (type: string) => …      // a preposition is not a verb
   const stamped = (sections) => …         // a participle names the result
   const blankBlock = (id) => …            // a noun phrase

   // REQUIRED
   const storeFile = (file: File) => …
   const detectKind = (type: string) => …
   const stampSchema = (sections) => …
   const findBlankBlock = (id) => …
   ```
2. **A predicate may read as one**: `isPublished`, `hasRight`, `canPublish`,
   `fails`, `matches` — a verb in the third person or an `is`/`has`/`can` prefix.
   A bare adjective (`publishable`) names a value, and belongs to a `computed`.
3. **A value is not a function**: `computed`, `ref` and plain constants are the
   place for noun names — `publishable`, `marked`, `chrome`, `titleClasses`.
4. **A name is preferred to a comment that explains it**:
   A docblock that exists to say what a call does is a name that was not chosen.
   Rename first; keep the comment only for what a name cannot carry — a reason,
   a constraint, a trade-off.
   ```ts
   // FORBIDDEN
   /** The list owns focus: it alone knows which row a change left the author in. */
   function focus(caret: AnswerCaret = 'end') { … }

   /** Runs the action and keeps the browser out of the keystroke. */
   function take(event: KeyboardEvent, act: () => void) { … }

   // REQUIRED
   function placeCaret(caret: AnswerCaret = 'end') { … }
   function handleAndStop(event: KeyboardEvent, act: () => void) { … }
   ```

---

## 4. Composable Naming & File Conventions

1. **Exact 1-to-1 Match**:
   Every composable function MUST live in a file named identically to the composable:
   - `export function useDirector(...)` $\to$ MUST be in `useDirector.ts`.
   - `export function useCursor(...)` $\to$ MUST be in `useCursor.ts`.
   - `export function useKeyNavigation(...)` $\to$ MUST be in `useKeyNavigation.ts`.
2. **Never Use Plain Nouns for Composables**:
   Never name a composable file with a plain noun (e.g. `director.ts` for `useDirector` is strictly forbidden).
3. **Single Primary Composable**:
   Each composable file should export exactly one primary composable matching its file name.
4. **NO God / "Junk-Drawer" Composables (Anti-Pattern)**:
   - A composable MUST NOT be used as a dump for an entire component's script (e.g. dumping 300 LOC and 37 exports into a single `useDiffAnnotator.ts`).
   - Rule of thumb: A composable must have a single, coherent responsibility and typically return at most 6–8 properties/methods.
   - When a component is too large, decompose the UI hierarchy into focused child components (e.g. `DiffViewport.vue`, `DiffFloats.vue`) and extract small, cohesive composables (e.g. `useSurfaceMotion.ts`, `useKeyNavigation.ts`). Do NOT create mega-orchestrator composables.

---

## 5. Component File Structure & Sections

Every Vue component (`*.vue`) in `@vidya/ui` must follow this exact section structure and comment banner style inside `<script setup lang="ts">`:

```vue
<script setup lang="ts">
// 1. External & internal imports
import { computed, ref, onMounted } from "vue";
import { cva } from "class-variance-authority";
import type { FloatActionProps, FloatActionEmits } from "./types";
import { cn } from "../../lib/utils";

/* --------------------------------- Props ---------------------------------- */

const props = withDefaults(defineProps<FloatActionProps>(), {
  disabled: false,
  tone: "default",
  class: undefined,
});

/* --------------------------------- Events --------------------------------- */

const emit = defineEmits<FloatActionEmits>();

/* --------------------------------- State ---------------------------------- */

// Reactive state, refs, computed, cva variants
const isOpen = ref(false);

/* --------------------------------- Hooks ---------------------------------- */

// Lifecycle hooks (onMounted, onUnmounted, watch, etc.)
onMounted(() => {
  // ...
});

/* -------------------------------- Handlers -------------------------------- */

// Event handlers triggered by user interactions (DOM events)
function onClick(event: MouseEvent) {
  // ...
}

/* -------------------------------- Helpers --------------------------------- */

// Pure calculations, formatters, local helper logic
function formatLabel(val: string): string {
  return val.trim();
}
</script>

<template>
  <!-- Clean, formatted template without inline tag collapsing -->
</template>
```

### Section Rules:

- Only include headers for sections that actually exist in the component.
- The order is **always**:
  1. `Props`
  2. `Events`
  3. `State`
  4. `Hooks`
  5. `Handlers`
  6. `Helpers`
- Maintain the standardized 80-char banner format: `/* --------------------------------- <Name> ---------------------------------- */`.

---

## 6. Type Extraction & Component Exports

Never declare inline complex props or emits in the `.vue` file.

1. **Adjacent `types.ts`**:
   Every component directory must have a `types.ts` defining:
   - `[ComponentName]Props`
   - `[ComponentName]Emits`
   - Any local domain types, including view models.

   This holds for apps as well as for `libs/ui`. Where a directory holds several
   components — as the mobile app's slices do — one `types.ts` serves them all,
   named per component. Pages follow the same rule: their route props live in
   `pages/types.ts`.

2. **Local `index.ts`**:
   Must export the component as default and re-export types:
   ```ts
   export { default } from "./FloatAction.vue";
   export type * from "./types";
   ```
3. **Package Root `src/index.ts`**:
   Must re-export the component and its types:
   ```ts
   export { default as FloatAction } from "./components/FloatAction";
   export type * from "./components/FloatAction/types";
   ```

---

## 7. Tailwind & Styling Guidelines (No Monolithic Strings)

### Style Extraction Rule: Extract Static Class Arrays and CVA to Adjacent `styles.ts`

To keep `<script setup>` clean and focused strictly on component logic and reactivity:

- **FORBIDDEN**: Static class arrays (`const fooClasses = [ ... ]`) and `cva()` declarations directly inside `<script>` in `.vue` files. Enforced by ESLint: `vidya/no-static-styles-in-script`.
- **REQUIRED**: Extract static class arrays and CVA variants to an adjacent `styles.ts` file in the component directory (e.g. `AnnotationNote/styles.ts`), and import them into the `.vue` component:
  ```ts
  // AnnotationNote/styles.ts
  export const noteClasses = [ ... ]
  export const actionClasses = [ ... ]

  // AnnotationNote/AnnotationNote.vue
  import { noteClasses, actionClasses } from './styles'
  ```

---

## 8. Prettier, Linter & Gatekeeper Standards

- `semi: false`
- `singleQuote: true`
- `printWidth: 100`
- `htmlWhitespaceSensitivity: 'ignore'`
- **Attribute Linebreak Rule**: Prettier wraps attributes only when the total line length of the opening tag exceeds `printWidth: 100`. Tags with short attributes (under 100 chars) remain on a single line unless explicitly broken or forced via `singleAttributePerLine: true`.
- **Enforced Linter Checks**:
  - `vue/max-template-depth: ['error', { maxDepth: 4 }]`
  - `vue/max-lines-per-block: { template: 100, script: 300, style: 80 }`
  - `vue/no-restricted-syntax: [nested ternaries, inline logic in @event, loops in computed]`
  - `vidya/no-nested-component-dirs: 'error'` (forbids arbitrary component subdirectories)
  - `vidya/no-monolithic-template-classes: 'error'` (forbids inline class strings > 80 chars in template)
  - `vidya/no-static-styles-in-script: 'error'` (forbids static class arrays / CVA in `<script>`; extract to `styles.ts`)
  - `vidya/no-dom-state-query: 'error'` (forbids `querySelector(...).value` in Vue components)
- Always verify changes with `make check`.

---

## 9. Component Hierarchy & Directory Boundaries

1. **Top-Level Component Directories**:
   Every reusable UI component must live in its own directory directly under `libs/ui/src/components/<ComponentName>/` (e.g. `DiffAnnotator/`, `DiffRow/`, `DiffFloats/`, `DiffViewport/`).
2. **NO Arbitrary Component Subfolders (Enforced by ESLint)**:
   Never create ad-hoc component subfolders inside another component (e.g. `DiffAnnotator/floats/` or `DiffAnnotator/rows/`). Such subfolders make components private, hide them from the public library API, and cause bloated directories.
   - Enforced by ESLint: `vidya/no-nested-component-dirs`. Any `.vue` file located deeper than `components/<Component>/<Name>.vue` fails linting.
3. **Compound Components (Composition over Monolith)**:
   High-level widgets like `DiffAnnotator` should compose peer components (`DiffRow`, `DiffFloats`, `DiffViewport`). Each peer component has its own `index.ts`, `types.ts`, `[Name].spec.ts`, and `[Name].stories.ts`, and is exported from `@vidya/ui`.
4. **Composables Subdirectory**:
   When a component relies on multiple headless composables, keep them grouped inside `composables/` with a barrel `composables/index.ts`.

---

## 10. Event Parameter Unification Principle

Do NOT declare duplicate sibling events that differ only by scope, granularity, or a boolean flag:

```vue
<!-- FORBIDDEN: -->
defineEmits<{ annotate: [] annotateBlock: [] }>()

<!-- REQUIRED: -->
defineEmits<{ annotate: [block?: boolean] }>()
```

Callers emit `@click="$emit('annotate', false)"` or `@click="$emit('annotate', true)"`, avoiding redundant event bridges and duplicate wrapper handlers.

---

## 11. Strict Props & Emits Contract in Vue

Every Vue SFC must adhere to strict type-based contracts:

1. **Type-Based Props Only**: Always use `defineProps<Props>()` with `withDefaults(...)`. Runtime object declarations (`defineProps({ ... })`) are forbidden (`vue/define-props-declaration: ['error', 'type-based']`).
2. **Explicit Emits**: All events emitted by a component must be declared in `defineEmits<Emits>()` (`vue/require-explicit-emits`).
3. **No Undefined Components**: Every component used in `<template>` must be explicitly imported or defined (`vue/no-undef-components`).
4. **Kebab-Case Event Casing**: Custom component events must be in kebab-case (e.g. `@row-pointer`, `@note-edit`), while standard `update:*` v-model events are permitted (`vue/custom-event-name-casing`).
5. **Attribute Hyphenation**: Props passed in templates must be hyphenated (`@my-prop="val"`) (`vue/attribute-hyphenation`).

---

## 12. Complexity & Nesting Limits

To guarantee readable, maintainable, and testable code:

- **Cyclomatic Complexity**: Maximum **10** per function (`complexity: ['error', 10]`).
  - If branching exceeds 10, decompose into dispatch tables, lookup maps, or focused pure helpers.
- **Control Flow Nesting Depth**: Maximum **3** levels (`max-depth: ['error', 3]`).
  - Deeply nested `for`, `while`, `if`, or `try` blocks must be flattened with early returns (`guard clauses`) or extracted into shallow sub-functions.

---

## 13. Non-Deterministic Environment Restrictions in Pure Logic

In pure computational layers (`model/`, `lib/`, `@vidya/domain`):

- `Date.now()` and `new Date()` are forbidden — inject clock interfaces instead.
- `setTimeout` and `setInterval` are forbidden — pass clock ports with controllable schedule/cancel methods.
- `Math.random()` is forbidden — use seeded generators or parameter ports.

---

## 14. Prohibition of Empty Catch Blocks

Empty catch blocks (`try { ... } catch (err) {}`) are forbidden by AST linter:

- Every catch clause must either handle the error, rethrow it, log it, or contain an explicit statement with a comment explaining why it is safely ignored.

---

## 15. Comments

Comments follow the same rule as the backend — see
[Comments](./coding-style-backend.md#6-comments). One line, a blank line above,
consistent within a group, and no commented-out code. The rule is written down
once so the two sides of the codebase cannot drift apart.
