# Projects outlook candidate evidence

Status: local implementation and synthetic verification only. Owner experience
review, authenticated workspace qualification and visual QA remain pending.

## Verified behavior

The candidate lists existing native projects inside Curve, shows the native
Project lead, and lazily reads only the selected project's allowed Modules and
Cycles. The transport contains only native list GETs. There are no source
mutations, importer, new Curve records, inferred prior approvals, project
completion percentages or invented deadlines.

The screen contract is `projects-outlook-candidate.md` (scope, source semantics,
review tasks, isolation and the prospective-association gate). The implementation
base is `e2556004ab253a2289677df14c193d845613b722` (protected PRD review UI).

## Automated evidence

- Full web suite: **187 tests passed across 24 files**.
- Required aggregate: **60/60 tasks passed**, with 57 tasks satisfied by the
  content-addressed existing cache; changed web formatting/lint/types ran.
- Changed TypeScript/TSX files: strict focused lint passed with no warnings.
- Whitespace and patch check: passed.
- Fixture-only Vite production build: passed. Shared source-connected hooks are
  replaced by throwing stubs in the isolated review configuration.
- Independent source review inspected native API/permission semantics and the
  read hook, transport, response guards, paths and presentation. One structural
  response-validation gap was fixed and re-reviewed; no remaining must-fix was
  identified in that review.

New tests cover lazy reads, no initial selection, archived filtering, disabled
features, guest/member restrictions, aborts, account/workspace/project transitions,
A→B→A stale responses, repeat selection, refresh, source denial/failure, scoped
response identity, malformed entire-array rejection, empty-source distinction,
Module local dates, Cycle offset instants, owner-name gaps, selection/search,
source ordering/caps, native links, permission-gated shell and account-scoped UI.

## Environment accommodations

The standard pnpm 11 dependency verifier tried to install into an unavailable
home store in this new worktree. Checks instead used the already-installed pnpm
launcher with package-manager self-management and dependency auto-install checks
disabled, plus writable temporary cache/home paths. No dependency was added or
fetched. Unchanged package build outputs were copied from the tested base for
local resolution; subsequent aggregate checks verified the workspace.

The i18n `tsx` launcher cannot create its usual Unix IPC in this environment.
A worktree-local copy of that installed launcher temporarily used Node's official
`--import tsx/dist/loader.mjs` loading path. Its original bytes were restored after
checks. No tracked source or prior worktree launcher was changed for this.

The first aggregate attempt reached 59/60 and its web typecheck was killed with
exit 137 while the full test suite ran concurrently. The serialized final aggregate
completed 60/60. This is a recovered environment-resource failure, not evidence
that the initial attempt passed.

## Unverified boundaries

- The dot cloud browser rejected the local preview URL with
  `net::ERR_BLOCKED_BY_CLIENT`. No alternate route was used, no website was
  published, and no screenshot/visual inspection is claimed.
- The static bundle is a build-verified clickable candidate. Layout, contrast,
  focus, narrow viewport and browser Back/Forward behavior still need visual and
  task-based review on an approved computer.
- No live source API, real tenant, provider, account or project data was accessed.
  Backend permissions were preserved, not independently requalified end to end.
- Native list responses are unpaginated. Lazy requests avoid cross-project
  fan-out, but large-list performance is not established.
- Source-list observations are not an atomic server snapshot or a protected
  metadata consistency fence. Native authentication/revocation remains authoritative.
- Owner UX approval, M2 completion, lifecycle adoption, publication, integration,
  deployment and live activation are all outside this evidence.
