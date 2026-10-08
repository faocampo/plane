# Preview synchronization — 2026-10-07

## Scope

Bring upstream `preview` at `7466675e471efe1c96b122615f7a0d30c9b2eb05`
into the Curve integration line starting at
`9bedb74a77460c65ac681854b714a4607680398e`, then update active development
candidates. The fork and upstream preview refs already match exactly.
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
The fork preview remains at the original checkpoint. Complete this resolved
checkpoint, then integrate and validate the new upstream delta before publication.

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
used. The resolved checkpoint is ready to commit on
`integration/preview-sync-20261007`; remote working branches remain unchanged.

Read-only analysis also found 25 conflict reports for the Initiative candidate
and 23 for the retained existing-project branch. These branches remain unchanged
until the shared synchronization is publishable. The original upstream-sync local
branch contains the October 7 preview checkpoint; its user edit and stash
were preserved. It also requires the newly fetched upstream delta.

The Initiative candidate retains its explicit owner UX gate. The replacement
component package can affect presentation even when behavior tests pass; the
exact synchronized candidate remains the review subject.
