# Scope editor v2 candidate verification

Date: 2026-10-06. Scope: local source preparation only.

## Executed

- Host Python 3.14.7 with Django 5.2.15, DRF 3.17.1 and jsonschema 4.26.0:
  **31 unittest methods passed**, with additional adversarial subcases. No database
  was configured or contacted by this suite.
- Full metadata lineage: absent/orphan distinction, saved empty scope, 1,000/1,001
  boundary, every historical row's identity, broken links, duplicate IDs, sequence,
  chronology, safe integers, unknown editions and valid Initiative-version gaps.
- Query-spy checks: head limit two, initial revision limit 1,001, and inclusive
  Initiative/proposal/current-pointer lookup without hiding cross-workspace rows.
- Mocked current-ORM authority: creator/admin success; inactive/bot/unknown-role,
  non-DRAFT/non-STANDALONE and inactive-Product rejection; LOCAL, installation and
  separate default-off gates; current authority and older-lineage change rejection.
- Actual DRF view dispatch with mocked service: exact eight-field success and typed
  ETag; session-only behavior; fixed 404 for queries, anonymous/API-key-only requests,
  unsupported methods and private exceptions; `no-store` on success and denial.
- Contract pin checks reject changed manifest or schema/policy bytes. The absent
  successor qualification entry point cannot fall back to the historical proof.
- Ruff 0.15.12 lint and formatting checks passed using the repository's backend
  configuration. All three Python files comply. `pip check` passed.
- Five contract snapshot files match the original Curve candidate byte-for-byte.
- Diff against restored Plane `7d4225d` for the installed Curve app is empty.
  Historical source, all 23 migrations, existing routes and proof bytes are intact.
- Whitespace and changed-document Markdown lint passed.

The reproducible commands are in [candidate instructions](README.md)
(source placement, test invocation and integration prerequisites). Raw host test
output is retained locally in `.curve-local/verification/scope-editor-unit.log`
(ignored execution log).

## Not executed or established

No PostgreSQL migration, transaction, row lock, concurrent insert, rollback,
direct-SQL corruption guard, authenticated application API or browser/E2E test ran.
Query spies and simulated authority changes are not evidence of these properties.
The Docker application container remains blocked before startup by the source
bind-mount denial documented in the [test profile](../../deployments/curve-local-pilot/README.md)
(isolated PostgreSQL setup and minimum operator access).

This reader is not installed or routed. Its database/catalog/source qualification
function deliberately does not exist yet. Persistent manual-plan storage and its
successor proof remain prerequisites. Gate 2, exclusive task reservation, native
UI integration, Today/decisions, roadmap and full pilot acceptance remain pending.

No new push, release, provider activation, merge or deployment occurred. No Docker
permissions, sharing settings or source mount paths were changed.
