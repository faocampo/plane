# Protected PRD review context

## Implementation boundary

This slice integrates the approved metadata-read scope as a session-authenticated,
read-only route and closed contract. It does not activate a production adapter,
provider, protected storage or PRD commands. The separate Initiative UX integration
review and deployment gates remain in place.

The endpoint is:

`GET /api/v1/workspaces/{slug}/curve/initiatives/{initiative_id}/prd/review-context/`

The implementation uses `CURVE_PRD_READ_ENABLED = False` and
`CURVE_PRD_READ_RUNTIME = None` by default. Enabling mutation commands does not
enable this read; enabling this read never enables mutation commands. An absent
or incomplete trusted read adapter produces a fixed, no-store
`PRD_CONTEXT_UNAVAILABLE` response. It never fabricates an empty checkpoint,
readiness result, reviewer or approval.

## Dedicated authorization

`prd-metadata-read-policy-v1.json` (additive pinned metadata-read policy) defines
`CURVE.PRD.METADATA_READ` under `CURVE_PRD_METADATA_READ_POLICY`. The existing
mutation policies, manifests and schema editions retain their original bytes.
This scoped companion is the metadata-read successor boundary; it does not expand
a historical mutation ALLOW or Initiative shell read into protected access.

`prd_read_views.py` (session-authenticated route and local scope selector) resolves
an active authenticated non-bot human, current active workspace membership and
exact same-workspace Initiative version. Only identity/version columns are selected
at this stage. General administrator status or creator ownership cannot bypass
the independent object policy or an explicit denial.

`prd_read_context.py` (current authorization and allowlisted projection) requires
fresh same-scope, same-actor, same-version observations for membership,
classification, object metadata, source metadata and evidence metadata. Unknown
classification or missing/failed observations deny. The authorization covers all
projected references and identities, including current reviewer and historical
decision attribution. Body/rationale access remains a separate policy path.

Before returning data, the service resolves local membership/scope again,
rechecks current protected metadata access, and requires a matching snapshot
revision through a strict read-only consistency fence. The opaque revision must
cover all current subject, assignment and access inputs. A database version by
itself is insufficient evidence of current source permission.

## Trusted adapter interface

An approved implementation of `PrdReadRuntime` (in-process read-only adapter
protocol) must provide:

- `observe(scope, evaluated_at)`: a fresh, closed action/policy/actor/scope/version
  authorization observation with current source/evidence/classification checks.
- `read_metadata(scope, snapshot_revision)`: an allowlisted metadata DTO selected
  using exact authoritative checkpoint, readiness and decision pointers.
- `is_current(scope, snapshot_revision)`: a strict boolean consistency/revocation
  fence for the complete current observation, without mutation or capture.

These are trusted server collaborators. No caller can supply them, roles,
authorization outcomes, risk exceptions or exact-subject observations in HTTP
input. The service accepts only JSON primitives conforming to the pinned input
schema; passing whole ORM records or extra protected fields fails closed.

**Live blocker:** no production `PrdReadRuntime` is installed or qualified in this
slice. It still needs approved source identity/transport and metadata access,
complete authoritative Idea Brief/inventory/evidence observations, correct scoped
record reads, and tested revocation/snapshot fencing in the target environment.
Only then may operators configure and separately activate the read adapter.
The security contract additionally requires redacted auditing of denied and
cross-tenant read attempts, including early denials before a runtime is resolved.
This slice introduces no audit write/sink. A qualified safe audit path and tests
are therefore also required before live activation; generic exception logging is
not an acceptable substitute. Provider credentials, access grants and storage
activation are outside this work.

## Projection semantics

`prd-review-context-v1.schema.json` (closed allowlisted response) exposes:

- Exact Initiative version/state and observation time.
- Binding synchronization metadata and the exact current immutable checkpoint.
- The selected readiness report's original status, reasons, time and profile,
  separately from applicability for `NEW_SUBMISSION`.
- Current Product Approver assignment, authorized identity and validity.
- Only the terminal decision attached to the displayed exact checkpoint,
  preserving original assignment and metadata edition.
- Advisory disabled capabilities and the current strong numeric `commandETag`.

Every capability is false with `COMMAND_RUNTIME_NOT_EVALUATED`. Metadata success
is not command authorization, acceptance or completion. The strong numeric PRD
ETag is distinct from the Initiative shell ETag.

Submission validates readiness at Initiative version N, then advances the
aggregate to N+1. Its immutable report remains historically `READY`, while
applicability for another submission becomes `STALE`. This does not mean the
submitted document changed or invalidate review of that checkpoint. A current
`BLOCKED` report remains blocked; missing current observations are `UNVERIFIED`.

Review outcomes target the exact submitted checkpoint. Approval has an additional
live source-version/digest requirement. Request-changes and rejection can address
the immutable submission after source edits. Current-submission readiness is not
silently imposed on those review outcomes.

Assignments retain the existing rules: exactly three distinct gate assignments,
current active humans, half-open validity windows, and three distinct people for
Standard/High risk. Low risk permits human overlap while preserving all three
assignments. Unknown risk never receives a default exception. Canonical lowercase
UUIDs prevent identity-case aliases from evading uniqueness checks. A historical
decision retains its original assignment even after current reassignment.

`ABSENT` means an authoritative authorized absence. `UNAVAILABLE` does not assert
absence. Unauthorized, nonexistent, malformed and failed reads share fixed,
non-enumerating Problem Details. Responses always use `Cache-Control: no-store`.
Protected bodies, rationale, storage/envelope locators, source file/container IDs,
document titles, raw provider errors and permission topology are excluded. This
slice supplies no source URLs or operation projection.

## Verification and limits

Backend validation uses real Django/DRF initialization and SessionAuthentication,
with synthetic trusted adapter fixtures. Tests for the local ORM selector mock
query results and verify exact tenant/active-human predicates. They do not prove
PostgreSQL constraints or database races.

At the recorded validation point, 547 backend tests passed: 155 new read-service
and request-level tests, plus existing PRD readiness, command, exact-review-subject
and old/new policy regressions. The four new Python files pass Ruff 0.9.7 format
and lint checks. The response schema remains the frozen frontend/backend contract.

From `apps/api` (backend project root), run the following with the repository's
base/test dependencies installed and synthetic local environment configuration:

```sh
python -m pytest \
  plane/curve/tests/test_prd_read_context.py \
  plane/curve/tests/test_prd_read_api.py \
  plane/curve/tests/test_prd_readiness.py \
  plane/curve/tests/test_prd_commands.py \
  plane/curve/tests/test_prd_review_validation.py \
  plane/curve/tests/test_prd_policy.py \
  plane/curve/tests/test_policy_evaluator.py \
  plane/curve/tests/test_policy_v2_evaluator.py -q
```

Covered cases include access denial and revocation, scope changes during a read,
failed resolvers, exact-subject drift, assignment windows/separation, immutable
v1/v2 attribution, forbidden fields, numeric ETags, repeat reads and no capture,
command or workflow side effects. Default-unavailable and authenticated success
paths are request-tested; response literals do not invent permission or readiness.

The full Docker-profile suite, real provider/storage integration and
authenticated live-browser lifecycle remain unrun. Synthetic tests and local
repository integration are not production activation or deployment evidence.

## Additional real-database scope evidence

`test_prd_read_database.py` (real session, workspace and concurrent-revocation
contract tests) adds 21 cases with actual PostgreSQL migrations and ORM selectors.
The protected metadata adapter remains synthetic. Successful GET requests perform
SELECT-only route SQL; personal or workflow records are not changed by the read.

Coverage includes foreign-workspace IDs even when the same human belongs to both
workspaces, missing records, inactive/deleted memberships and workspaces, bot and
inactive users, anonymous/unsupported requests, and disabled flags. Five cases
commit user/membership or Initiative-version changes from a distinct PostgreSQL
connection between the initial and final scope reads; each is denied before any
metadata response is returned.

This additional run used PostgreSQL 17.11 extracted from signed Debian packages,
not the Docker profile's PostgreSQL 15.7. All real migrations were applied. The
21 route tests, six existing persistence-race/tenant-constraint regressions and
one existing metadata round-trip baseline passed. The local loopback server was
stopped and shutdown verified. These results qualify those database boundaries,
not real provider authorization, storage, an operational audit sink or production.

Run the new tests against the supported isolated PostgreSQL test profile:

```sh
python -m pytest --migrations plane/curve/tests/test_prd_read_database.py -q
```

## Frontend read-only integration

The Initiative detail now loads the exact metadata projection through the typed
Curve service. Runtime decoding uses the closed backend-equivalent schema plus
cross-field checks for scope, version, command ETag, decision/checkpoint pins,
readiness applicability reasons and capability observation time. Unknown fields,
protected content and inconsistent responses are rejected with a fixed safe error.

The validator is generated at build time, not compiled with dynamic code in the
browser. `generate-prd-read-validator.mjs` (CSP-safe validator generator) runs for
service build, development and type checks. The generated module is included in
service-specific Turbo cache outputs; an actual cache-restore test recreated a
removed generated file. Native Node ESM and bundled tests cover CommonJS helper
interoperability. Regenerate after changing the mirrored response schema; the
schema-parity and generated-source digest tests detect drift.

The panel presents submitted checkpoint, current reviewer, original decision and
original readiness separately from readiness for a new submission. It does not
fetch document bodies or activate commands. Absent, unavailable, loading and
error states stay distinct. Old metadata is hidden synchronously on viewer,
workspace, Initiative, version or refresh-generation change; cancellation and
late-response guards prevent cross-selection display. Focus/visibility return
revalidates access. Read results are not stored in browser persistent storage.

Frontend validation includes full web tests, direct TypeScript, focused lint and
format checks, native ESM decoding and a static synthetic preview build. A final
rendered check of this new metadata panel remains pending. The earlier Initiative
creation rendered acceptance does not qualify this added surface. The required
workspace aggregate was attempted and remains blocked by the environment's
existing i18n `tsx` Unix-socket restriction after 32 successful tasks; it is not
reported as a complete aggregate pass.
