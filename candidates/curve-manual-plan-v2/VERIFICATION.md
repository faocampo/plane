# Manual persistence candidate verification

Recorded: 2026-10-06. Evidence covers the staged candidate and recovered baseline.
It does not establish an installed draft writer, Gate 2 or a completed manual pilot.

## Executed checks

| Check | Result and scope |
| --- | --- |
| Recovered PostgreSQL baseline | **186 passed**: project-association qualification, scope API, exact scoped PRD bridge, reopening services and independent-connection reopening races |
| Candidate host unittest suite | **102 passed**, including adversarial subcases, exact JavaScript parity and **12 Gate 2 kernel tests**; ORM/service collaborators are doubled |
| PostgreSQL shape functions | **14 passed** against the actual frozen SQL: valid closed fixtures, required properties, malformed values, private receipt constraints and canonical digest |
| Transactional DDL experiment | **1 passed**: declared model/SQL delta, denied empty seal/truncation, original recorder untouched, empty reversal restores the exact original physical catalog |
| Linux validator | **6 passed**: real valid/invalid jobs, actual limits, memory/descriptor exhaustion, CPU kill, competing processes, interrupted slot holder and parser bounds |
| UI/client unit tests | **27 passed** in two Vitest files; fetch/API responses are synthetic mocks |
| Candidate TypeScript check | Passed for the new service, DTOs, panel and shared button dependencies; not a full application build |
| Visual acceptance | Five synthetic desktop/mobile captures, zero browser JS errors or horizontal overflow, detector findings empty; fresh reviewer disposition **ship** for the unmounted UI/client candidate |
| Current authority and catalog | Owner-only temporary files, monotonic local observation counters, exact grant fences, atomic CAS publication, retained tombstones and workspace/material/plan identities |
| Protected semantic facts | Derived from actual synthetic PRD/workflow/quality/repository body bytes; altered fact snapshots rejected |
| Trusted successor preparation | Closed additive delta tests; missing pins/proof reject, no fallback or installed successor |
| Historical preservation | 23 migration byte pins and both historical proofs retained; installed Curve runtime unchanged from recovered Plane `7d4225d594adf984de1451f16ad2c8ab741c58eb` |

The host uses Python 3.14.7, Django 5.2.15, DRF 3.17.1, jsonschema 4.26.0 and
Ruff 0.15.12. The existing Linux image uses Python 3.12.5, Django 5.2.15,
pytest 9.0.3, psycopg 3.3.4 and PostgreSQL 15.7. Frontend checks use React 18.3.1,
TypeScript 5.8.3 and Vitest 4.1.8 in an isolated local test environment.

The [host instructions](README.md) (unit environment and candidate boundaries),
[isolated test runner](qualification/run_isolated.py) (bounded candidate material
sent to container temporary storage), and [test profile](../../deployments/curve-local-pilot/README.md)
(original read-only source mount and disposable services) provide reproduction.

```sh
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py sql
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py worker
python3 candidates/curve-manual-plan-v2/qualification/run_isolated.py ddl
```

The runner neither relocates the API source nor changes its mount. It extracts
only regular candidate Python/JSON test files into the disposable container. The
original API remains mounted read-only; no app module, proof, route or migration
recorder entry is installed by these phases.

## Defects found by actual runtime tests

- SQL alternative-schema aliases collided with a PL/pgSQL variable. Explicit
  qualified aliases now allow valid fixtures while retaining invalid-input rejection.
- A nullable format predicate still evaluated a timestamp cast for non-date strings.
  A nested format branch now restricts that cast to date-time properties.
- The catalog inspector left `pg_catalog` first in the migration search path.
  It now restores the caller's path before DDL; the test inspector does the same.
- Restricted child imports attempted to write bytecode under the 16 KiB file limit,
  leaving truncated caches. The child now disables bytecode writes before imports.

These failures were corrected in the candidate and the affected real suites passed.

## Exact DDL evidence boundary

The [DDL experiment](postgres_tests/test_ddl_experiment.py) (explicit DDL/state
operations inside one rolled-back test transaction) leaves the migration's
`CURRENT_CATALOG_DIGEST` unset. It verifies that the complete migration refuses
before DDL, then separately exercises the declared DDL operations without
installing a seal value, successor proof, runtime module or recorder entry.

The original catalog digest remains
`sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7`.
The experiment observed candidate digest
`sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8`.
This is review evidence, **not a qualification pin**. Its delta has three tables,
26 columns, six new functions plus one replaced verifier, 12 indexes, 27 added
constraints with one replaced policy constraint, and 33 added triggers including
internal foreign-key triggers. All other original catalog rows are preserved.
Empty reversal restores the exact original catalog and coverage verifier.

This does not test the complete gated forward migration, populated graph guards,
retained-evidence reversal refusal, real save/replay transactions or save races.
The [installed guard suite](postgres_tests/test_installed_guards.py) (qualified
loader, distinct seals and direct mutation rejection) remains unexecuted and
intentionally fails when the reviewed successor is absent.

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
