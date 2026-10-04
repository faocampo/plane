# Native association prerequisite verification

This is local engineering evidence for a minimal read-only API and typed client.
No live provider, new credential, activation, public push, merge or deployment was
performed. Native UI evidence is maintained separately by the UI implementation.

## Contract and compatibility

`PROJECT-ASSOCIATION-PRECONDITIONS.md` (route, closed DTO, authorization and
successor-qualification contract) defines the implementation. The source closure
was frozen before runtime verification. Only the two new read/view modules and
additive URL registration differ from the predecessor's protected source closure.

- `scope_reopening_qualification.json` (immutable 120-module C2b predecessor):
  `sha256:72bdb3b987ec1925754e6a14dee36cecec3c85706605c052d443628d84e7fb52`.
- `project_association_read_qualification.json` (reviewed 122-module successor):
  `sha256:5381243df882c087ab61932cda77e286a76b3b3e4b19853be5eea9cc81574f1b`.
- `project_association_read_candidate/manifest-v1.json` (separate read packet pin):
  `sha256:0e2ff6eac36ae52e32e87ae75163b0ba08aa9d27e6c0da87a1c085e171201f68`.
- `project_association_read_candidate/project-association-precondition-v1.schema.json`
  (closed minimal wire response):
  `sha256:5c89be086e2cc7a3efdb7a5247d82f5f8280ed88a4df1c74f7efce7298015a60`.

Original migrations, model catalog, physical catalog, writer inventory, excluded
writers and historical schema bytes are unchanged. The reviewed loader remains
the explicit trust root; it cannot cryptographically protect itself. No generic
repinning tool or runtime override was added.

## Passed verification

- Initial read acceptance: 43 real-PostgreSQL tests passed in 25.06 seconds.
- Association command and complete existing C2b regression plus initial successor
  qualification checks: 253 tests passed in 273.66 seconds.
- Typed client: 43 source-imported Vitest tests passed on the final client bytes.
- Client test and whole services-package source-bound TypeScript checks passed.
- Types-package TypeScript check passed.
- Production services and types builds passed, using this checkout's source
  types. Build outputs were written to isolated temporary directories rather
  than overwriting shared dependency targets from another checkout.
- Deterministic generated validator check and exact backend/client schema parity
  passed. Public consumer contract integrity (109 files) and all seven public
  integrity regression cases passed.
- Changed backend Ruff lint/format checks passed.
- Full services/types formatting passed on 207 files, plus the package-local
  services invocation passed. Root and package ignore files narrowly protect
  raw-byte mirrored schema JSON only; validators, TypeScript and unrelated JSON
  remain checked. The parity test and schema digest manifest remain active.
- Full package lint passed: services retains six unrelated existing warnings;
  types retains one unrelated existing empty-file warning. Changed files have
  zero warnings.
- Git whitespace validation passed.

Fresh full comparable backend aggregate: 2,044/2,044 tests passed in 876.09
seconds on a newly recreated and fully migrated disposable database. This is the
previous 1,976 cases plus all 49 final read and 19 successor cases. The only 554
warnings concern the expected missing collected-static directory. The runtime
source closure and qualification remained frozen throughout. Final Django
checks passed: no migration changes detected and zero system-check issues.
The disposable PostgreSQL and Redis services shut down cleanly.

## Behavior covered

`tests/test_project_association_preconditions.py` (current native authority,
redaction, snapshot fencing and races) covers exact input coordinates, canonical
UUIDs, duplicate/extra query rejection, session authentication, fixed no-store
denials, all three availability states, selected-only association identity,
ENDED-history suppression, fresh Product version/ETag and stale command rejection.
The ENDED projection test supplies only a test-local dependency guard; the
production END guard remains fail-closed and is covered by command regressions.

Tests revoke current workspace/project membership and human active state while
retaining stale authenticated objects; public project visibility, administrator
status and caller headers do not bypass native membership. Archive state and
feature/configuration failures never synthesize availability. A read can succeed
for a member who lacks command administrator authority; CREATE still denies.

Same-transaction membership, human, source archive, Product version, installation,
feature gate and association changes fail the final fence and roll back. Real
transaction tests cover read-before-create, create-before-read,
revocation-before-read and read-before-revocation. Native source data and
aggregate/audit/policy/event/outbox/idempotency counts remain unchanged by GET.
The final enlarged read suite also tests corrupted manifest, policy and schema.

`tests/test_project_association_read_qualification.py` (pinned successor and
closed-delta attacks) checks immutable predecessor bytes and unchanged catalog
sections, predecessor/successor corruption, unknown fields/editions, changed
models/migrations/catalog/writer inventory, missing/read/unrelated/new modules,
unchanged URL delta, runtime source drift and physical database drift. Tests that
forge the successor hash also supply a matching observed source closure; the
fixed allowed delta still denies. Existing C2b positive and tamper tests remain
included with qualification fully enabled.

`packages/services/tests/project-association-preconditions.test.ts`
(synthetic closed-wire and transport tests) covers exact GET/no-store/signal,
input snapshotting, malformed/extra fields and contradictory association states,
wrong target and ETag families/versions, exact schema mirror bytes, safe error
redaction, cancellation and no automatic retry or mutation.

## Environment and limits

Tests use the existing isolated harness with Python 3.12.14, Django 5.2.15,
PostgreSQL 17.11 and Redis 8.0.2. Synthetic credentials and in-memory provider test
runtimes only are used. Exporters are disabled. No external telemetry runtime is
activated, and the denied Redocly telemetry invocation was never attempted.

The checked-in Docker test stack uses PostgreSQL 15.7 Alpine. That stack and
cross-version physical-catalog rendering parity were not tested. The retained
PG17 physical pin fails closed for a differing deployment catalog; these local
results are not deployment or provider qualification. RabbitMQ, MinIO and a
Temporal server are not provisioned. The comparable aggregate retains exactly
three prior exclusions: full Temporal orchestration workflows, PRD Temporal
server integration, and real Temporal contracts. Local Temporal adapter/activity
cases remain included. No browser or visual acceptance is claimed by this API
and client slice.

## Reproduction and local logs

From the repository root, client checks use the existing installed binaries:

```sh
apps/web/node_modules/.bin/vitest run \
  --config packages/services/tests/vitest.association-read.config.mjs
packages/services/node_modules/.bin/tsc \
  -p packages/services/tests/tsconfig.association-read.json
node packages/services/generate-existing-work-validators.mjs --check
node_modules/.bin/oxfmt --check packages/services packages/types
```

The comparable backend aggregate uses the same test-only telemetry setup and
prior exclusions as the earlier C2b evidence:

```sh
/tmp/curve-association-runtime/run-with-db.sh env -u OTEL_SDK_DISABLED \
  OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
  CURVE_TELEMETRY_MODE=DISABLED pytest plane/curve/tests \
  --ignore=plane/curve/tests/test_temporal_orchestration_workflows.py \
  --ignore=plane/curve/tests/test_prd_temporal.py \
  --ignore=plane/curve/tests/test_temporal_contracts.py \
  --create-db --migrations \
  -o cache_dir=/tmp/curve-association-runtime/pytest-cache -q
```

Local retained logs:

- `/tmp/project-association-read-first.log` (initial 43-case backend acceptance).
- `/tmp/project-association-read-regression.log` (253-case association/C2b regression).
- `/tmp/project-association-read-aggregate.log` (fresh comparable backend aggregate).
- `/tmp/project-association-read-client-final.log` (43-case typed client acceptance).
- `/tmp/project-association-read-client-types.log` (source-bound client type check).
- `/tmp/project-association-read-services-types.log` (whole services source
  type check).
- `/tmp/project-association-services-build.log` (production services build).
- `/tmp/project-association-types-build.log` (production types build).
- `/tmp/project-association-public-contracts.log` (seven public contract regressions).
- `/tmp/project-association-read-package-format.log` (full services/types
  format pass).

- `/tmp/project-association-read-django-checks.log` (final no-drift and
  zero-issues Django checks).
