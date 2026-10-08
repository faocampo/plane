# C2b local reopening verification

Status: fresh focused backend acceptance and comparable aggregate regression
passed. Final static, migration-state and Django system checks passed; the
disposable database shut down cleanly. No runtime activation, publication, provider qualification, Gate 2,
planning, controlling binding or execution is claimed.

## Frozen candidate

The implementation is additive to `3e4c5d9e01dd24948131da70efdbcd3988eac4de`.
Integrated client-only HEAD before the backend implementation commit is
`a6733f998705592069f0e6f7aa49923d6f9d72e8`.

- `SCOPE-REOPENING-C2B.md` (atomic replacement and historical-authority contract)
  defines the bounded 1–100-member ProductApprover command.
- `SCOPE-REOPENING-PRECONDITIONS-C2B.md` (minimal protected version-pin read)
  defines the fresh-client remediation read without old-member disclosure.
- `migrations/0023_scope_reopening.py` (successor ledger, lifecycle and physical
  coverage guards) has SHA-256
  `d1f1563d0cf63998635c192a5046df683b059e48c976a520ffc049296d2a56c9`.
- `scope_reopening_qualification.json` (23 migration byte pins, exact model
  catalog, 120 runtime module byte pins and supported writer inventory) has digest
  `sha256:72bdb3b987ec1925754e6a14dee36cecec3c85706605c052d443628d84e7fb52`.
- Successor physical catalog seal:
  `sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7`.

All historical C1/C2a schemas, policy candidates and migrations through 0022 are
byte-unchanged against the supplied baseline. The qualification validator/loader
is explicitly trusted and excluded from recursive self-hashing; this is local
compatibility proof for supported Curve-owned writers, not a defense against
malicious trusted-root replacement, arbitrary outside code or privileged DB
operators.

## Passed fresh PostgreSQL acceptance

176 tests passed across the five new reopening test modules in 344.77 seconds,
using a newly created, fully migrated database after the final migration changes.
The final runtime source closure and qualification remained frozen during the run.
Only expected missing collected-static directory warnings occurred.

Coverage includes:

- ALIGNING, PRD_REVIEW and PLANNING reopening, complete replacement, required
  reason and exact closed raw-input bounds; context-only replacement stays scoped.
- Current action-specific ProductApprover ACL, role separation, native access for
  the actor and every reviewer, restricted guests and explicitly selected subitems.
- Removal of inaccessible historical members without disclosing removed data;
  fresh-client minimal preconditions through a new scoped submission and approval.
- Immutable old checkpoints/readiness/subjects/decisions/accepted commands;
  stale approval/completion replay rejection and pending command no-effect behavior.
- Pending marker, retained historical checkpoint, generic-read suppression, fresh
  scoped submission clearing the marker and mandatory new approval.
- Existing pause/resume/cancel behavior with marker retained and authority cleared.
- Reopen versus submit/approve races in both serialization orders.
- Rollback and raw-SQL partial/forged graph attacks, scoped foreign keys, typed-row
  projection substitution, immutable ledger and direct TRUNCATE denial.
- Provisional ALLOW rollback followed by a distinct DENY on final authority loss,
  source-bound decision digests and last-callback reviewer revocation.
- Migration/runtime-source/model/physical catalog drift, unknown manifest shapes,
  changed verifier and forged self-consistent DB seal rejection by the independent
  application physical-catalog pin.

The five test modules are `test_scope_reopening_contract.py` (closed commands and
byte pins), `test_scope_reopening_services.py` (lifecycle and authority),
`test_scope_reopening_integrity.py` (database graph and compatibility proof),
`test_scope_reopening_preconditions.py` (minimal protected read), and
`test_scope_reopening_races.py` (serialization order).

## Aggregate regression and additional checks

The first comparable run used the prior three exclusions and collected 1,975
cases (1,799 prior cases plus 176 new cases): 1,964 passed and 11 failed in
653.37 seconds. Ten failures were private observability tests suppressed by the
restored harness's global OTEL_SDK_DISABLED=true setting. The remaining failure
was an old metadata selector mock that omitted the new pending marker column;
the fixture now explicitly supplies None and expects both selected columns.
Production field access remains strict. All eleven failed cases passed on the
approved test-only rerun. The corrected final comparable aggregate passed
1,976/1,976 cases in 635.34 seconds: the prior 1,799 cases plus all 177 C2b cases.
The original failed log and corrected-run logs are retained separately. Only
expected missing collected-static directory warnings remain (506 warnings).

The test command removes the global SDK kill switch only for that process, sets
trace/metric/log exporters to none, and keeps ordinary Curve telemetry DISABLED.
The observability fixtures use private IN_MEMORY_TEST providers. One existing
construction-only OTLP test constructs exporters and immediately shuts them down;
it does not register, export or flush them. No collector endpoint or external
telemetry runtime was activated. This correction is unrelated to the separately
forbidden Redocly invocation, which was never run.

A separate added reverse-migration preservation test passed on PostgreSQL, proving
that retained reopening evidence blocks reversal and leaves ledger, marker, head,
revisions and PRD history intact. The new C2b set is therefore 177 cases: 176 passed
in the fresh run and this additional case passed separately. Final migration-state
check reported no changes; Django system check reported zero issues.

## Test teardown boundary

`tests/conftest.py` (framework-only immutable-ledger fixture cleanup) adapts only
Django-generated SQL flush. Inside Django's single rollback-safe teardown
transaction it asserts the ledger TRUNCATE guard is enabled, disables only that
statement-level guard, performs framework cleanup, restores/asserts the guard and
verifies physical coverage before commit. The unmanaged immutable seal is never
flushed. There is no runtime flag, raw-SQL interception or test-body window with
the guard disabled. The separate direct SQL TRUNCATE test runs with the guard
enabled and confirms denial and retained evidence.

## Environment and limits

The disposable local harness was rebuilt after the former runtime disappeared:
Python 3.12.14, Django 5.2.15, PostgreSQL 17.11 and Redis 8.0.2. Baseline migration,
fresh test database creation and service shutdown were checked. No live
credentials or provider accounts were used. Provider/storage evidence is through
the existing synthetic trusted test runtime only.

The checked-in `docker-compose-test.yml` (standard isolated test stack) uses
PostgreSQL 15.7 Alpine. That stack and cross-version physical-catalog rendering
parity were not tested here. A different physical catalog fails closed until
explicitly qualified; local PG17 evidence is not portable deployment approval.
RabbitMQ, MinIO and a Temporal server were not provisioned. The comparable main
regression retains the prior three whole-file exclusions shown below. Existing
local C2a Temporal adapter/activity tests were included. No additional real-server
work was attempted.

The C2b backend mutation is not wired into a new UI flow. The independently
committed client includes the minimal precondition GET adapter, while reopening
mutation transport and successor-revision frontend support remain outside this
slice. Generic protected PRD reads, including observation GET, remain unavailable
while a reopening marker is pending; POST capture returns fresh metadata and can
be repeated after reload to continue submission. Empty replacement remains
unsupported. No real-provider qualification, visual acceptance, broad repository
check, public push, PR, tag movement or live activation occurred.

## Reproduction commands and retained logs

Run from the backend app root using the restored disposable harness. The harness
is temporary local tooling, not a claim that the standard Docker stack was run.

Fresh focused acceptance:

```sh
/tmp/curve-association-runtime/run-with-db.sh \
  pytest plane/curve/tests/test_scope_reopening*.py --create-db -q \
  > /tmp/curve-reopening-final-fresh.log 2>&1
```

Final comparable aggregate:

```sh
/tmp/curve-association-runtime/run-with-db.sh env -u OTEL_SDK_DISABLED \
  OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
  CURVE_TELEMETRY_MODE=DISABLED pytest plane/curve/tests \
  --ignore=plane/curve/tests/test_temporal_orchestration_workflows.py \
  --ignore=plane/curve/tests/test_prd_temporal.py \
  --ignore=plane/curve/tests/test_temporal_contracts.py -q \
  > /tmp/curve-reopening-regression-final.log 2>&1
```

Final system checks:

```sh
/tmp/curve-association-runtime/run-with-db.sh bash -c \
  'python manage.py makemigrations --check --dry-run && python manage.py check' \
  > /tmp/curve-reopening-system-checks-final.log 2>&1
```

Retained evidence:

- `/tmp/curve-reopening-final-fresh.log` (176-case fresh migrated acceptance).
- `/tmp/curve-reopening-regression-final.log` (1,976-case corrected aggregate).
- `/tmp/curve-reopening-regression.log` (initial 11 failures, preserved).
- `/tmp/curve-reopening-affected-rerun.log` (all 11 corrected cases passing).
- `/tmp/curve-reopening-final-checks.log` (reverse-preservation case and checks).
- `/tmp/curve-reopening-system-checks-final.log` (final no-drift/zero-issues checks).

Final Ruff lint passed, all 28 affected Python files passed format check, all 23
migration and 120 runtime-source byte pins matched, and backend whitespace checks
passed. Verification was completed on the source bytes identified above before the
implementation commit; committing those bytes does not change qualification.
