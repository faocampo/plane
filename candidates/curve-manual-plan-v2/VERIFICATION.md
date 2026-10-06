# Manual persistence qualification and installed-source verification

Recorded: 2026-10-06. Evidence covers the recovered baseline and a disposable
complete proposed application, followed by promotion of those exact bytes into
the local source. It does not establish workspace runtime activation,
Gate 2 or a completed manual pilot. The separate scope-reader successor follows
the same manual proof without changing storage or writers.

## Executed checks

| Check | Result and scope |
| --- | --- |
| Recovered PostgreSQL baseline | **186 passed**: project-association qualification, scope API, exact scoped PRD bridge, reopening services and independent-connection reopening races |
| Historical regression on proposed application | **186 passed** with the draft switch disabled, actual new models/migration and complete reviewed successor chain; no old behavior or guard bypass |
| Candidate host unittest suite | **107 passed**, including normalized-PRD subset/traceability adversaries, exact JavaScript parity and **12 Gate 2 kernel tests**; ORM/service collaborators are doubled |
| PostgreSQL shape functions | **14 passed** against the actual frozen SQL: valid closed fixtures, required properties, malformed values, private receipt constraints and canonical digest |
| Transactional DDL experiment | **1 passed**: declared model/SQL delta, denied empty seal/truncation, original recorder untouched, empty reversal restores the exact original physical catalog |
| Actual native authority | **13 passed**: exact approved normalized PRD, nonempty immutable evidence snapshot, separately protected body/excerpt, actor/owner/reviewers, revoked native/object access, source edits and monotonic catalog producer refresh |
| Proposed installed application | **6 passed**: complete forward migration, real pinned loader, distinct exact seals, empty-table TRUNCATE/seal denial and no model/migration drift |
| Complete migration reversal | **3 passed**: empty reversal/forward restore exact catalogs; retained save/replay evidence and a standalone NO_EFFECT audit each prevent reversal |
| Proposed save/API graph | **15 passed**: append/current/history/original replay, exact graph counts, session/CSRF/strict JSON, disabled surface, retained SQL mutations, two independent-connection first-head races, final native/file changes and 16 direct-SQL omission/substitution cases |
| Linux validator | **6 passed**: real valid/invalid jobs, actual limits, memory/descriptor exhaustion, CPU kill, competing processes, interrupted slot holder and parser bounds |
| UI/client unit tests | **27 passed** in two Vitest files; fetch/API responses are synthetic mocks |
| Candidate TypeScript check | Passed for the new service, DTOs, panel and shared button dependencies; not a full application build |
| Visual acceptance | Five synthetic desktop/mobile captures, zero browser JS errors or horizontal overflow, detector findings empty; fresh reviewer disposition **ship** for the unmounted UI/client candidate |
| Protected semantic facts | Derived from exact approved normalized PRD or fixed synthetic PRD and protected workflow/quality/repository bytes; altered fact snapshots rejected |
| Trusted successor | Closed additive delta tests plus the actual complete-application loader; missing pins/proofs reject; no deployed-state rehash or permissive fallback |
| Installed-source rerun | **57 passed** through the original read-only bind: 14 SQL, 6 installed-guard/model, 3 complete-migration, 15 graph/API, 13 native-authority and 6 Linux-worker tests; **107 host tests** also passed after the move |
| Historical preservation | 23 migration byte pins and both historical proofs retained; the tested additive successor now governs the local Curve runtime |

The host uses Python 3.14.7, Django 5.2.15, DRF 3.17.1, jsonschema 4.26.0 and
Ruff 0.15.12. The existing Linux image uses Python 3.12.5, Django 5.2.15,
pytest 9.0.3, psycopg 3.3.4 and PostgreSQL 15.7. Frontend checks use React 18.3.1,
TypeScript 5.8.3 and Vitest 4.1.8 in an isolated local test environment.

The [host instructions](README.md) (unit environment and candidate boundaries),
[isolated test runner](qualification/run_isolated.py) (installed-source phase selection), and [test profile](../../deployments/curve-local-pilot/README.md)
(original read-only source mount and disposable services) provide reproduction.

```sh
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py all
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py regression
```

Run database phases sequentially against this project's disposable database.
At `27a16ae`, the original qualification runner separately exercised the baseline,
SQL/worker/DDL experiment, native authority and a complete reviewed temporary
application. See [qualification history](qualification/README.md) (exact source,
DDL and literal pin review, phase commands and fixture cleanup).
After promotion, `all` passed against the single installed source through the
original read-only bind, without a prospective copy or alternate settings module.
The historical DDL experiment and assembly code remain in Git at the qualification
checkpoint; complete installed migration tests supersede them.

## Defects found by actual runtime tests

- SQL alternative-schema aliases collided with a PL/pgSQL variable. Explicit
  qualified aliases now allow valid fixtures while retaining invalid-input rejection.
- A nullable format predicate still evaluated a timestamp cast for non-date strings.
  A nested format branch now restricts that cast to date-time properties.
- The catalog inspector left `pg_catalog` first in the migration search path.
  It now restores the caller's path before DDL; the test inspector does the same.
- Restricted child imports attempted to write bytecode under the 16 KiB file limit,
  leaving truncated caches. The child now disables bytecode writes before imports.
- The initial manual adapter accepted only the synthetic v2 PRD body, while the
  real approved bridge retains normalized v1 bytes. It now accepts that exact
  metadata/version pair through a conservative closed text subset without
  replacing the original body, evidence snapshot or readiness record.
- Nested fixture cleanup initially verified the full catalog before the new
  TRUNCATE guards were restored. Test cleanup now restores them immediately after
  truncation, before the existing full-catalog check; every test body retains guards.

These failures were corrected in the candidate and the affected real suites passed.

## Exact DDL evidence boundary

The [DDL experiment](qualification/README.md) (explicit DDL/state
operations inside one rolled-back test transaction) leaves the migration's
`CURRENT_CATALOG_DIGEST` unset at its original checkpoint. It verified that the complete migration refused
before DDL, then separately exercised the declared DDL operations without
installing a seal value, successor proof, runtime module or recorder entry.

The original catalog digest remains
`sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7`.
The experiment observed candidate digest
`sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8`.
That observation alone was **not a qualification pin**. Its delta has three tables,
26 columns, six new functions plus one replaced verifier, 12 indexes, 27 added
constraints with one replaced policy constraint, and 33 added triggers including
internal foreign-key triggers. All other original catalog rows are preserved.
Empty reversal restores the exact original catalog and coverage verifier.

The experiment alone does not test a complete writer. The later prospective
application separately executes the complete gated migration, populated graph,
real API/save races and reversal checks listed above, using the reviewed literal
catalog pin. The [installed guard suite](../../apps/api/plane/curve/tests/manual_plan_v2/test_installed_guards.py)
(qualified loader, distinct seals, direct mutation rejection and model consistency)
passes in that application and still fails when its reviewed successor is absent.

The raw-SQL matrix first captures a real save, validates every deferred constraint
and rolls it back. It then proves a complete direct-SQL positive control before
omitting or substituting each of eight components. Failure must leave all record
counts and the Initiative version unchanged. Policy/audit helpers are not used
to repair the deliberately incomplete raw graph. Race tests synchronize only
scheduling after actual Linux validation and use independent native connections.

## Visual and integration limits

The [UI review](UI_REVIEW.md) (fresh bounded review and documenter evidence) covers
five synthetic preview states only. Review used fresh role agents because this
runtime exposes no named finish-reviewer/documenter agent types. Incumbent design
files remain unchanged; existing sidecar drift was not adopted as a new rule.
No candidate panel is mounted. Protected definition preparation, authenticated
browser/API integration, full application type/build checks, complete theme and
accessibility qualification remain pending.

Docker's original Documents mount now works after the operator's authorized retry.
No access bypass, alternate source mount, Full Disk Access change, new credentials,
provider call, model spending, push, PR, merge or deployment was performed.
The [release checklist](PROMOTION.md) (exact remaining implementation and acceptance
gates) remains authoritative for promotion. Passing these checks does not activate
any writer or approve a plan.

## Separate scope-reader successor

The [reader verification](../curve-scope-editor-v2/VERIFICATION.md) (23 prospective
database/API tests and 31 host tests) records the independently qualified
metadata-only addition at `90996fb`. Its exact proof is
`sha256:c2e37caa561e943bf4f2883c62d8ed889c74a55809fa1f5ffc93aed5d4ce093e`.
Only two modules and the route closure change; all manual proof, model, migration,
catalog, writer and exclusion bytes remain intact. The reader and draft settings
are explicitly false outside test overrides. The combined installed suite passed
**80 tests**, and **107 manual plus 31 reader host tests** passed after promotion.
The historical 186-test regression has not yet been repeated for this reader
successor; its prior manual-only qualification remains accurately scoped.
