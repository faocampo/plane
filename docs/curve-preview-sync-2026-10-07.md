# Preview synchronization — 2026-10-07

## Latest position — 2026-10-08

- Upstream and fork `preview` now match `bab49bb978ccb56af1d78dec6c6d54dfe8d03c1c`.
- [PR #47](https://github.com/faocampo/plane/pull/47) (upstream integration and
  conflict resolutions) merged as `0cc166bc480525a8301535eb392e1708b0c555e7`.
  All exact-head CI checks passed: 395 backend tests, 10 skips, web
  format/lint/build/types, API lint, translation sync, copyright and CodeQL.
- The dependent Initiative candidate incorporates that synchronization locally.
  Its 36 conflict paths are resolved, including file relocations, Curve branding,
  navigation, Quicklink validation, image-upload errors, retained CI partitions,
  and new component APIs. React 19 refs and component-test fixtures are updated.
- Candidate evidence: 392 frontend tests across 34 files, 22 script regressions,
  web dependency build and type checking, backend Ruff and public contract
  integrity pass. Repository lint and strict resolution checks pass.
- Candidate publication and new exact-head backend CI remain pending. PR #17
  retains the owner's UX acceptance gate; the component migration requires
  review on the synchronized candidate. No deployment or storage activation.

The sections below preserve the earlier checkpoint and validation sequence.

## Scope

Bring upstream `preview` at `7466675e471efe1c96b122615f7a0d30c9b2eb05`
into the Curve integration line starting at
`9bedb74a77460c65ac681854b714a4607680398e`, then update active development
candidates. The fork preview matches this initial checkpoint; upstream advanced
by three commits during the October 8 refresh (see below).
Recovery checkpoints, historical branches, original edits and stashes remain intact.
This synchronization supplies no deployment or activation authority.

## Resolutions

- Adopt upstream's flattened web source paths; relocate Curve-only components,
  hooks and services into the same structure.
- Migrate Curve foundation controls to the installed Propel 0.7.3 components and
  Plane blocks. Preserve modal navigation, Escape dismissal, cancellation focus,
  sidebar expansion state and controlled-navigation identifiers.
- Combine Quicklink normalization and backend field errors with upstream's new
  dialog and input components, including accessible field-error references.
- Preserve both public/internal storage endpoint coverage and upstream's missing
  object metadata regression coverage.
- Keep upstream's stable sortable identity and updated security dependency pins.
  Seed the lockfile from upstream and add only Curve dependency requirements.
- Use upstream's Node version file in CI while retaining explicit dispatch and
  draft-review gates. API lint is read-only; native tests start their required
  database, cache and queue directly and include storage regression tests.

## Verification checkpoint

Local foundation web tests: 39 passed. Web type checking and dependency builds
passed. Relevant web/blocks lint passed with existing warnings. Five workflow
selection guards and the pinned contract-integrity checks passed.
Thirteen storage unit tests passed in a network-isolated, read-only container
using mocked storage clients and minimal worker bootstrap settings. An initial
minimal-settings attempt failed during unrelated Celery setup; the corrected
worker bootstrap supplied the required isolation. This is unit evidence only.
Exact-head CI and active-candidate checks must be recorded in the associated PRs
before any integration merge. Prior candidate evidence is historical after a sync.

## Status update — 2026-10-08

Fresh fetch found three additional upstream commits, ending at
`bab49bb978ccb56af1d78dec6c6d54dfe8d03c1c`: security dependency updates,
Python dependency management with uv, and the MinIO image replacement.
The fork preview remains at the original checkpoint. The initial merge is committed
as `07e7c5e7cf`, followed by test-fixture correction `2cf64870a0`.
The three-commit delta is merged locally with four conflicts resolved: retain
Curve delivery/document instructions, combine upstream uv lint with Curve tests,
and move Temporal 1.31.0 into the new Python manifest/lockfile. Upstream's default
dev/test groups preserve the old local test dependencies. The lockfile adds only
Temporal, nexus-rpc and types-protobuf; existing upstream package versions remain.
Frozen JavaScript and Python installs pass, backend Ruff passes, 39 web tests and
10 hook/workflow regression tests pass, and contract integrity passes.

The merge-aware hook implementation passed validation. Five isolated Git tests
pass: ordinary commits, unresolved conflicts, blob-based classification including
unusual filenames and partial staging, exact-parent resolutions, and renamed/deleted
files. Merge checks
retain normal repository lint for imported code and strict read-only formatting
and warning checks for resolution files. All 15 repository lint tasks passed;
strict resolution formatting and lint passed with zero warnings or errors.
Publication remains pending the additional upstream delta and exact-head CI.

## Publication gate

The original pre-commit hook applied strict warning checks to every unchanged
upstream import and failed on existing warnings. It restored its attempted edits.
The owner authorized continuation with the tested merge-aware hook. No bypass was
used. The original checkpoint is committed on `integration/preview-sync-20261007`;
validation of the latest delta is in progress. Remote working branches remain unchanged.

Read-only analysis also found 25 conflict reports for the Initiative candidate
and 23 for the retained existing-project branch. These branches remain unchanged
until the shared synchronization is publishable. The original upstream-sync local
branch contains the October 7 preview checkpoint; its user edit and stash
were preserved. It also requires the newly fetched upstream delta.

The Initiative candidate retains its explicit owner UX gate. The replacement
component package can affect presentation even when behavior tests pass; the
exact synchronized candidate remains the review subject.
