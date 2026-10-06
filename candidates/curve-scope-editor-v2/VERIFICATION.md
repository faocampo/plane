# Scope editor v2 verification

Date: 2026-10-06. The host suite passed **31 tests** and the real PostgreSQL/API
suite passed **23 tests** against the reviewed disposable application. The reader
is now integrated in local source and remains disabled. The combined installed-source
suite passed **80 tests** (57 manual and all 23 reader cases), with **31 reader
and 107 manual host tests** also passing after promotion. The historical 186-test
regression remains to be repeated after this separate source successor.

## Completed evidence

- **31 host tests passed again** after the reader's current source was frozen.
  They cover complete metadata lineage, the 1,000/1,001 boundary, cross-identity
  rows, broken links, duplicate IDs, chronology, safe integers, unknown editions,
  valid Initiative-version gaps, query bounds and simulated fresh authority.
- Host DRF dispatch covers exact fields/ETag, session-only authentication, fixed
  denial and `no-store`. These service collaborators are doubles.
- The five contract snapshot files retain their original Curve bytes.
- The reviewed delta adds only two reader modules and replaces the URL module.
  The manual proof remains
  `sha256:b4f16de1a78f0ffb7f62df770f6fe2e50636da3961e22bb193ba5e914b87215b`.
  The installed reader proof is
  `sha256:c2e37caa561e943bf4f2883c62d8ed889c74a55809fa1f5ffc93aed5d4ce093e`.
- Every model, migration, physical catalog row, writer and excluded authority
  remains the manual predecessor's qualification. No database migration is added.

The [runtime suite](../../apps/api/plane/curve/tests/scope_editor_v2/test_scope_reader.py) (actual database/API
qualification) exercises intact absence and three saved-empty revisions, a real
session's GET/HEAD, every feature gate, creator/admin separation, revoked native
source access, final-fence rollback, bounded-history admission, immutable SQL
mutation denial, missing/tampered proof and two read/write serialization orders.
It checks zero domain writes and the current ETag after a competing scope save.
All 23 cases passed with the actual qualified loader and active SQL guards.
An initial fixture attempted a bulk Product update that the model forbids; it was
corrected to use valid native model fixtures and immutable-mode creation. No
production guard or qualification was relaxed.

## Limits

The lineage admission test lowers the bound to exercise rejection on actual
stored rows; the full 1,000/1,001 boundary uses host fixtures. Neither is described
as a thousand real database writes. Concurrency tests use independent PostgreSQL
connections and inspect actual blocking where the reader holds the row lock.

The [reproduction instructions](README.md) (commands and source boundaries)
distinguish host doubles from the actual application. Raw logs stay in
`.curve-local/verification` (private ignored execution evidence).

No browser journey, Gate 2 persistence, exclusive reservation, pilot operations,
publication, release or deployment is established by this reader qualification.
