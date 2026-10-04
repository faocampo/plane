# Native Projects and Product association candidate

Status: local implementation candidate. Owner visual and task-based acceptance,
merge, deployment and backend activation remain separate and unfulfilled gates.

## Scope and source

The base is Plane `82b4ca976e58c1e8d8d065ace70667b3ce2b6a73` (existing-work,
scoped-PRD and reopening-precondition foundation). This UI consumes the additive
project-association precondition reader implemented alongside it. The existing
Curve workspace shell gate is preserved. No feature flag, backend setting,
provider identity or permission grant is supplied by the frontend.

The native route is `/{workspace}/curve/projects/` (Projects outlook and Product
association entry). Its component boundary is:

- `core/components/curve/projects/project-outlook.tsx` (authenticated container),
  `project-outlook-view.tsx` (source-owned, reusable Projects outlook view).
- `core/components/curve/projects/project-association-flow.tsx` (inline choice,
  exact relationship review, result and recovery), `project-association-panel.tsx`
  (production wiring and protected navigation).
- `core/hooks/use-curve-project-association.ts` (ephemeral actor/workspace-scoped
  intent, independent request generations and safe replay).
- `core/services/curve-project-association.service.ts` (authenticated Product
  pagination and typed discovery/command adapter).

The established Curve logo, Inter/IBM Plex typography, semantic theme tokens and
Propel controls are retained. The inline flow avoids a new modal or identity.
The Product relationship and its consequence precede transport detail. At narrow
widths fields and relationship columns stack in reading order. Focus moves to
review/result headings, returns to choices, and the leave warning is keyboard
reachable. Layout and actual color contrast still require rendered review.

## Real discovery and guarded command

1. Native source Projects come from the existing accessible-project reader.
   Archived and wrong-workspace rows cannot be selected for association.
2. Active Products come from the current authenticated Curve Product list.
   Nothing is automatically selected. Every page is validated; malformed,
   wrong-workspace, duplicate or incomplete results never become a partial list.
   Pagination fails explicitly above 100 pages of at most 100 records each.
3. Review reads the typed, exact-project/Product precondition endpoint. It
   distinguishes AVAILABLE, ASSOCIATED_WITH_SELECTED_PRODUCT and
   ASSOCIATED_ELSEWHERE. Hidden/unavailable never means unassociated. The
   installation identity is server-owned; there is no fixture or environment
   fallback in production.
4. Only an explicit reviewed AVAILABLE relationship can submit. The command
   contains exactly the selected source project and trusted installation. The
   fresh Product version and a generated idempotency key accompany it. All
   authorization is rechecked by the existing command service/backend.
5. A verified typed response alone yields a confirmed receipt. A transport loss,
   abort after sending or unverifiable response remains an uncertain outcome.
   Stop waiting does not claim cancellation. Recovery replays the exact same
   input/version/key; the UI does not silently create a new command.
6. Conflict and invalid preconditions preserve choices and demand a fresh review.
   Permission denial clears protected details and refreshes native access.
   Account/workspace changes synchronously clear the visible session, abort
   supported requests and discard late results. The legacy Product list method
   cannot abort an already-started HTTP page, so its late results are discarded
   and no subsequent page is requested.
7. Router navigation, browser Back and browser unload are guarded while the
   request is pending/uncertain. An explicit informed leave remains available;
   it cannot undo a server effect. No request is persisted to browser storage.

Plane remains authoritative for source work, project leads, membership, Modules
and Cycles. This candidate has no task writes, automatic Initiative scope,
reopening mutation, approval grant, association END command or agent execution.

## Isolated native review harness

`tests/curve/review-harness/` (standalone native React component review) reuses the
same outlook view, association component and hook. Its injected adapter is
synthetic and memory-only. Production never imports it. An always-visible
synthetic notice and a `connect-src 'none'` CSP block any API/provider request;
source-navigation destinations are disabled in this harness.

It includes available, already associated, associated elsewhere, version
conflict, access denied, uncertain-then-recover, no Products and unavailable
states. These are simulation choices, not runtime configuration or authority.

From `apps/web` (frontend workspace), with installed dependencies:

```sh
node_modules/.bin/vite build --config tests/curve/review-harness/vite.config.mts
node_modules/.bin/vite preview --config tests/curve/review-harness/vite.config.mts
```

The generated `tests/curve/review-harness/dist/` (static review build) is not
committed. Serve it with a local static server; file-URL module behavior varies
between browsers. No backend needs to run or be enabled.

## Verification evidence

- 319 tests passed across 22 Curve, home and navigation regression files,
  including 42 new controller, DOM and adapter cases. They cover current
  version/identity, repeated clicks, cancellation, exact-key uncertain recovery,
  conflict, denial/redaction, scope switching, stale reads, Product pagination,
  focus and Router Back/leave behavior.
- Full web TypeScript check passed after React Router type generation using
  `tsconfig.curve-source.json` (source-bound package resolution). This prevents
  stale built artifacts in a sibling worktree from being mistaken for this
  checkout's services/types. It disables composite output only for this
  supplemental source check and preserves application strictness.
- The static native harness builds with Vite from the actual React components,
  incumbent styles and local fonts. Its build is not screenshot evidence.
- Focused formatting and lint passed. One bounded Impeccable static detector run
  on the changed rendered components returned zero findings. This is not pixel,
  contrast, assistive-technology or owner acceptance.
- The first ordinary `pnpm check` attempt stopped at the environment's pnpm
  home-store preflight. A temporary environment-only pnpm launcher then ran the
  aggregate without installing dependencies or changing tracked configuration:
  44 of 48 tasks succeeded (34 cached), and `@plane/services#check:types` failed
  because its normal package resolution selected an older sibling-worktree
  `@plane/types` build without current existing-work/precondition exports. No
  successful aggregate result is claimed; current-checkout source-bound checks
  remain separate evidence.

Reproducible source-bound commands, from `apps/web` (frontend workspace):

```sh
node_modules/.bin/react-router typegen
node_modules/.bin/tsc --noEmit -p tsconfig.curve-source.json
node_modules/.bin/vitest run --config vitest.curve-source.config.ts tests/curve tests/home/curve-home-overview.test.tsx tests/navigation/curve-navigation-placement.test.tsx
```

`vitest.curve-source.config.ts` (current-checkout service alias) changes only test
resolution; it never injects synthetic adapters into a production route.

## Remaining human and environment gates

No desktop/mobile screenshots were captured. The allowed browser capture route
was unavailable; no browser-security or socket workaround was attempted. Owner
review must inspect desktop and mobile together, exercise keyboard focus,
readable contrast, long names, overflow and the available/recovery states,
apply one grouped correction if needed, and confirm once. The existing
Initiative-shell document/reviewer/operational-flow UX gate is retained.

No cloud source/provider API, publication, PR creation, merge, flag activation,
deployment or visual-acceptance action was performed for this slice.
