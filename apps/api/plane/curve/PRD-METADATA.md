# Submitted PRD and evidence metadata persistence

## Public contract and source scope

This increment implements the metadata dependency for external PRD checkpoint
submission. The following contract documents are publicly available:

- [Curve artifact/evidence specification](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/docs/technical/prd-artifact-evidence-records.md)
  (immutable PRD versions, exact evidence snapshots and provenance).
- [Curve integration contract](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/docs/technical/integration-contracts.md)
  (external authoring, current authorization and lifecycle authority).

The artifact/evidence, external checkpoint/review and AccessEnvelope files in
`prd_candidate_schemas` (closed metadata contracts) are byte-pinned copies of
the public Curve revision above. A fourth candidate schema is pinned to
[Curve review-decision records](https://github.com/faocampo/curve/blob/938b1db9bf597bdca8f671cbab67c66ddd0230b8/docs/technical/prd-review-decision-records.md)
(protected rationale and immutable exact-subject metadata).
The validator separately verifies the existing
common, gate-assignment and Product schemas. The
109-file public consumer edition and its execution/capability gates are unchanged.

This backend implementation adds four PRD/evidence metadata tables, one external
DocumentCheckpoint table, one review-decision table and internal transaction
helpers. Candidate authenticated command acceptance routes are available behind
explicit runtime configuration. Provider transport, protected-body storage and
worker transport activation remain subsequent work. Synthetic tests use fabricated object
references; references and digests alone do not prove that stored bytes exist.
Policy values, identities and deployment configuration are excluded from source.

## Records and integrity

| Record | Responsibility |
| --- | --- |
| PRD Artifact | One logical PRD per workspace/Initiative and its current version |
| PRD ArtifactVersion | Immutable submitted version, predecessor/number, object reference, author, body schema and policy/evidence references |
| EvidenceItem version | Immutable exact source version and historical access/provenance metadata |
| EvidenceSnapshot | Immutable ordered membership bound to one ArtifactVersion |
| DocumentCheckpoint | Immutable external capture, exact native version/snapshot, provider version and predecessor |
| PRD ReviewDecision | One immutable terminal outcome per checkpoint, exact human assignment and protected rationale reference |

An explicit empty snapshot represents a PRD with no material evidence. Nonempty
snapshots bind evidence identity/version, source version, content/envelope digests,
material flags, claims and optional excerpt references. Material entries require
claim references. Snapshot digests cover the entire schema record except the
self-referential digest field, including identity, ordering and timestamp.

Bodies and excerpts use closed object references. The schema rejects inline
document content and unknown fields; direct database evidence inserts also reject
inline content or unknown top-level/source/envelope fields. Historical evidence
JSON has no unvalidated provider-response fallback. Canonical metadata encoding
rejects fractional/non-finite numbers, unsafe integers, unsupported types and
excessive nesting/node counts.

Database guarantees include:

- Composite same-workspace foreign keys for Initiative, Artifact, version,
  predecessor, current pointer, snapshot and provider relationships.
- Reciprocal deferred version/snapshot references and a commit-time pointer
  check, requiring the submitted metadata graph to commit together.
- An Artifact row lock, exact predecessor and consecutive version numbers,
  preventing competing submissions from forking the same predecessor.
- ORM and database immutability guards on submitted versions, evidence and
  snapshots; Artifact identity stays immutable while its pointer advances.
- Exact snapshot membership checks against existing immutable evidence versions,
  including scope, source/content/envelope identity, chronology and claims.

The [repository](prd_metadata_repository.py) (workspace-scoped atomic append
helper) locks the Artifact, inserts the snapshot/version and advances its pointer.
It participates in an outer command transaction so audit/outbox failure can roll
back all metadata. Cryptographic digest reproduction is performed by validated
ingestion. Schema-management privileges are outside these row-level guarantees
and must be excluded from runtime application roles.

## External checkpoint persistence

The [checkpoint model](prd_checkpoint_models.py) (closed, append-only source
capture metadata) retains typed object-reference fields rather than document
bytes. It binds one native ArtifactVersion and its EvidenceSnapshot, provider
connection/file/version, historical capture container, normalization schema,
author and access/completeness/retention reference IDs.

The [checkpoint migration](migrations/0011_document_checkpoint.py) (tenant foreign
keys, insertion guards and immutable history) adds database-backed protections:

- Same-workspace Initiative, binding, provider, version, snapshot and predecessor
  references, including same-Initiative binding checks.
- One checkpoint per native ArtifactVersion and consecutive checkpoint numbers
  per binding. The binding lock serializes successor selection; artifact and
  checkpoint predecessor identities must agree.
- Exact object ID/digest/length, author, normalization and policy-reference
  equality with the native version; creation requires its current Artifact pointer.
- Capture chronology checks and immutable updates/deletes, including raw writes.
  Runtime roles must lack schema-management, trigger-disabling and TRUNCATE powers.

The [capture repository](prd_checkpoint_repository.py) (atomic native-record and
checkpoint append) locks Initiative, binding and Artifact in that order. It
requires the expected Initiative version, Aligning or PRD Review state, intended
Initiative scope and exact previous checkpoint before appending the snapshot/version,
advancing the Artifact pointer and recording the checkpoint. Outer command
failure rolls all of these changes back. These checks fence stale, paused and
cancelled submissions at this metadata boundary. PRD Review also permits an
authorized successor submission, which replaces the pending review subject.

Access/completeness evaluation and retention/envelope IDs remain opaque historical
references here. Current same-workspace authority, current provider/evidence
access, complete-document validation and protected byte integrity must be proven
by the consuming command. This metadata helper grants no authorization and does
not advance the Initiative state or write its submitted-checkpoint pointer,
review decision, command result or audit/outbox. Those writes must join the same
outer command transaction before the live workflow is enabled.

## Review-decision persistence

The [decision model](prd_review_models.py) (immutable exact-checkpoint review
metadata) supports approval, changes requested and rejection. Its database
guards bind the same-workspace Initiative, Product Approver, current checkpoint,
native version, evidence snapshot, source version, risk and decision chronology.
All three assignments must be valid; Standard and High risk require distinct
humans. Competing terminal outcomes have one winner. A successor submission
permits a new decision while retaining the preceding decision and assignment
history. Runtime membership and live source/evidence permissions still require
independent authorization at the command boundary.

The [rationale conversion](prd_review_rationale.py) (strict original UTF-8 byte
verification) retains only an object ID, digest, size, media type, AccessEnvelope
and retention-policy version in decision metadata. It verifies original bytes
without whitespace or Unicode normalization. Authorized reads must verify the
same bytes before reconstructing a rationale-bearing response. Missing or
altered bytes produce fixed errors. These conversion helpers perform no storage
access and establish no permission grant.

## Transactional PRD lifecycle

The [lifecycle repository](prd_lifecycle_repository.py) (internal submission and
decision transaction helpers) records the exact current checkpoint and controlling
decision on the Initiative. Submission enters PRD Review; approval enters Planning;
changes requested and rejection return to Aligning. Each change increments the
Initiative version once. A successor clears the controlling decision pointer while
preserving the immutable earlier checkpoint and decision.

The [lifecycle migration](migrations/0013_initiative_prd_lifecycle.py) (same-scope
pointer foreign keys and database state guards) requires a submitted checkpoint
for PRD Review and an approval of that exact checkpoint for Planning. Direct
writes cannot remove the submitted history, bypass a review outcome, select a
foreign subject or change a lifecycle pointer without advancing the version.
Pause/resume and cancellation retain their checkpoint and decision. A preserving
migration is required to reverse after lifecycle use.

These helpers require an outer command transaction. Their own savepoint makes
the native version, checkpoint, controlling decision and Initiative changes
atomic. The consuming authenticated command must independently establish current
authority and commit its idempotency record, result, audit and outbox in that same
outer transaction. Calling a metadata helper is never authorization to approve.
No provider or storage call occurs under these domain locks.

## Current PRD command authorization

The [PRD policy](https://github.com/faocampo/curve/blob/6049d229e13e0384d0d3e4c88229720da5f296c1/docs/technical/prd-command-policy.md)
(four action-specific authorization rules) is copied byte-for-byte into
[the candidate manifest](prd_candidate_policy/prd-policy-v1.json) (digest-pinned
policy contents). Existing core and Initiative policy bytes remain unchanged.
Submission requires an active human creator or explicit contributor grant.
Approval, changes requested and rejection require the active assigned Product
Approver plus current action-specific object access. All three human gates must
be active; Standard and High risk require distinct people.

The [context builder](prd_policy_context.py) (current database-derived actor,
membership, risk and assignments) ignores caller-supplied role and ACL claims.
Its trusted local ACL resolver receives the exact action and versioned Initiative.
Unavailable or malformed authority fails closed, including creator submission.
Acceptance and final commit use row locking within the policy-owned transaction;
provider and protected-body reads remain outside those locks.

The existing Operation kernel accepts scoped PRD policy receipts and reauthorizes
replay against current membership. This internal integration creates no HTTP
command route and does not validate a complete external PRD command. State,
displayed subject, source/evidence access, readiness, protected bytes and final
commit fencing remain required in the consuming handler. The explicit PRD
enablement setting defaults to disabled.

The [policy migration](migrations/0014_prd_policy_identity.py) (exact PRD policy
identity constraint and retained-decision rollback protection) accepts only the
pinned version and digest. Retained decisions require a preserving migration.

## Command input and subject preconditions

The [command boundary](prd_commands.py) (raw JSON validation, immutable input and
current-subject checks) consumes the pinned Submit, Approve and ReturnForRevision
schemas. It rejects duplicate JSON keys, unknown authority fields, invalid UTF-8,
oversized input and malformed precondition/idempotency headers. The candidate
external PRD API uses quoted numeric Initiative ETags as published; existing
Initiative routes retain their separate ETag representation.

The canonical request digest binds the action, expected version and every payload
field, including original rationale bytes. Reordered JSON keys do not change the
identity. Rationale whitespace and Unicode are preserved. The immutable command
keeps rationale and the idempotency key out of its representation; the Operation
request-identity envelope contains only action, expected version and digest.
Callers must never log or serialize the transient command's protected fields.

Current-subject checks require the allowed state, exact aggregate version and
same-workspace binding for submission. Review additionally binds the current
checkpoint, artifact version, content digest, provider version, evidence snapshot,
risk tier and Product Approver assignment. Apply these checks after current
authorization and repeat them under the final Initiative lock. Resolve all
completeness/evidence IDs independently; supplied IDs do not establish readiness.

This boundary is ready for handler integration. No route or provider/storage
activation is introduced by these helpers.

## Durable accepted PRD commands

The [accepted command model](prd_command_models.py) (immutable per-Operation
command metadata) retains the actor, workspace, Initiative, accepted version,
complete-request digest and closed subject fields. Review rationale uses a
protected object ID, digest, byte length, AccessEnvelope and retention-policy
reference. Verified reconstruction compares the supplied protected bytes and
complete original request identity before returning transient rationale content.
It performs no storage read and grants no content access.

The [append repository](prd_command_repository.py) (policy-owned atomic command
append) requires an active matching authorization receipt and the accepted
Operation's exact idempotency identity. It locks and checks the current subject,
then inserts the immutable record in the same transaction as the Operation,
idempotency result, audit and outbox. The Operation ID identifies the durable
command for a future worker. Current-authorized replay returns the existing
record; it must never call append again.

The [command migration](migrations/0015_prd_accepted_command.py) (tenant foreign
keys, closed-subject guards and history preservation) checks Operation scope,
human attribution, target, action and recorded PRD policy identity. It binds
review to the current checkpoint and assigned Product Approver, and rejects
inline rationale, mismatched fields, raw updates and deletion. Reverse migration
requires an empty command table; retained commands need a preserving migration.

This establishes durable metadata and transactional append, with synthetic tests
using fabricated protected-object references. The consuming HTTP handler must
independently authorize storage promotion and current source/evidence/readiness
before acceptance. Submission readiness references still require trusted scoped
resolution. Worker execution, current-authorized replay orchestration, final
lifecycle completion, safe failure/cancellation and cleanup remain integration
work. Metadata persistence alone does not prove that protected bytes exist.

## Remaining runtime integration

The [review validator](prd_review_validation.py) (pure exact-subject and gate
consistency checks) now validates checkpoint binding identity, the entire native
PRD object reference, exact snapshot/digest, author, normalization/access/retention
references, chronology and immediate checkpoint predecessor. Historical source
container moves preserve the captured location. Native artifact sequence and
evidence-member integrity remain responsibilities of the metadata repository.

Its review check covers approval, changes requested and rejection. It compares
the displayed checkpoint, artifact version, content digest, source version and
evidence snapshot to the server's current subject. It requires the authenticated
human Product Approver, exact assignment identity, all three active human gates,
current risk and policy versions, and assignment validity through the final
decision. Standard and High risk require three distinct people. Failures expose
fixed error codes without rationale, document content or schema diagnostics.

These checks consume trusted server records, return no permission grant and
perform no database mutation. The completion service consumes the exact-review
checks inside its final authorization transaction.
Current membership, policy, access and cancellation must be independently loaded
and revalidated at the commit fence. Approval also requires stable live source
validation; a negative outcome may review the exact immutable submission after
live edits. The schema's rationale field remains in memory here. Persisting or
returning rationale requires its separate protected retention/access handling.

The authenticated submission command must check current actor, workspace/object,
source/evidence access, capability, readiness, body integrity and applicable
storage/policy authority before using this helper. It must recheck the Initiative
version and cancellation fence, invoke the capture append, and commit its
idempotency result, audit/outbox and PRD Review transition in the same transaction.
Provider work stays outside the final database transaction.

Stored access/provenance metadata is historical evidence, never a reusable
permission grant. Excerpt derivation and current envelope validity must be
verified at capture and review. Worker transport, live runtime activation and
the Planning UI remain subsequent integration work.
Live storage/provider activation remains subject to its existing approval and
infrastructure evidence.

## Candidate authenticated acceptance

The [acceptance service](prd_acceptance.py) (two-phase authorization and durable
Operation acceptance) authorizes before external preparation and reauthorizes
under database locks before committing. Exact-payload replays recheck current
authority and return the existing Operation without repeating storage preparation.
Stale versions, revoked membership, expired preparation and unavailable authority
fail with bounded error responses.

The [command endpoints](prd_views.py) (session-authenticated submit, approve and
return-for-revision routes) require CSRF protection, conditional version and
idempotency headers. Responses contain safe Operation metadata. Acceptance queues
work; it does not itself complete a PRD lifecycle transition.

Activation requires exact boolean command enablement and a trusted runtime with
action-specific ACL resolution, a preparation context and local final revalidation.
Preparation must prove provider capability, storage policy, current source/evidence
access, readiness and worker availability. The context reconciles unused protected
objects under its approved policy and retains those referenced by a committed
Operation. No provider/storage adapter or worker activation is supplied here.
Requests must run outside an enclosing database transaction so provider work stays
outside database locks.

The [request classifier](request_privacy.py) (early Curve privacy boundary) applies
before authentication. PRD request bodies are bounded to 64 KiB and preserved for
strict duplicate-key validation after session CSRF checks. Curve API-token logs
omit bodies, responses, query strings and freeform headers; ordinary request logs
omit Curve query strings. Infrastructure logging requires equivalent controls.

The [acceptance tests](tests/test_prd_acceptance_api.py) (real-session CSRF,
authorization races, replay, expiration and request-log privacy) use a synthetic
runtime and prove acceptance only. Live provider, protected-copy lifecycle and
worker completion require separate integration evidence.

## PRD completion application service

The [completion service](prd_completion.py) (accepted-command execution and atomic
lifecycle settlement) consumes workspace/Operation IDs from a trusted internal
caller. It reloads the immutable accepted command and rechecks the original
human's current membership, action ACL, gate assignment, risk and exact subject.
Current worker authorization separately controls Operation transitions. An absent
effective-principal override retains the accepted human actor as its subject.

The configured runtime supplies fresh, bounded provider/storage preparation
outside database transactions and local final revalidation. It must verify
current body/source/evidence access, current policy version references, stable
source capture, readiness and approved storage. Preparation has an exact
Operation/request-digest binding and expiry, rechecked after local validation.
The service reproduces retained body and original rationale digests. Approval
additionally compares current source version/content; negative review continues
to address the immutable submitted checkpoint after live edits.

Under the final locks, submission appends the native version/snapshot/checkpoint
and enters PRD Review. Approval enters Planning; changes requested or rejection
returns to Aligning. The Initiative pointer/version, immutable decision when
applicable, Operation result/success, policy audits and existing Operation event
outbox commit atomically. No new public event schema is introduced. An outbox
failure rolls back the domain effect; current worker authority records a safe
terminal failure when persistence remains available. A cancellation request
settles to Cancelled without applying the PRD effect.

Concurrent delivery of one Operation has one domain effect. Distinct accepted
commands racing on an Initiative version have one winner. Unused prepared
objects remain the approved runtime's cleanup/reconciliation responsibility;
the preparation context observes the committed Operation only after commit.
Policy loss or infrastructure failure that prevents safe settlement raises a
fixed unavailable error, retaining authoritative state for worker recovery.

No completion runtime, provider credentials, protected storage or live activation
is installed. Candidate worker transport is described below. The
[completion tests](tests/test_prd_completion.py) (authenticated acceptance through
submission/review settlement, full return-resubmit-approve chain, duplicate
delivery, concurrent review, revocation, cancellation and rollback) use synthetic
runtime observations and real PostgreSQL transactions. They prove the application
service; live-provider end-to-end verification remains open.

## Candidate durable PRD delivery

The [PRD relay](temporal/prd_relay.py) (bounded outbox delivery) binds each accepted
Operation to its stable workspace/Operation workflow ID. The additive
`CurvePrdOperationWorkflowV1` type runs on the existing worker queue; prior workflow
types and histories retain their contracts. Ambiguous startup retries use the
same ID and verify the existing execution's type before acknowledging delivery.
Transport RPCs have a ten-second timeout; three failed dispatch attempts retain
a safe dead-letter record for recovery. Existing workspace lease recovery applies.

Delivery requires exact boolean `CURVE_PRD_DELIVERY_ENABLED`, command enablement,
workspace enablement and a configured trusted completion runtime. Acceptance's
worker-readiness proof must independently establish that this delivery path is
available. Source registration alone establishes no live readiness or storage
approval. Default deployment configuration remains unchanged.

The [PRD activities](temporal/prd_activities.py) (scoped execution and settlement)
check actual Temporal workflow identity and the authoritative Operation binding.
Workflow history carries metadata-only input/results and fixed sanitized failures.
Protected bodies and rationale remain inside the approved runtime's activity
preparation. Completion has a two-minute activity attempt, five-minute total
schedule bound, twenty-second heartbeat bound and at most three attempts. These
are candidate execution bounds, independent of protected-record retention policy.

The completion service checks an execution fence before preparation and at final
commit. Cancellation or deadline expiry fences late thread results. Runtime
provider calls must themselves be bounded and support interruption where available;
a database cancellation does not guarantee an immediate provider-read abort.
Exhausted activity failures use a separate settlement activity that cannot apply
a PRD effect or retrieve protected bodies. Lost worker authority or unavailable
persistence retains authoritative state for authorized recovery.

Authenticated cancellation routes PRD Operations to this destination using the
persisted accepted-command relationship. Pending PRD work can be cancelled before
workflow startup; settlement also works after dispatch failure. A workflow signal
provides no cancellation authority. Final completion rechecks database state,
so an already-recorded cancellation prevents a subsequent PRD effect.

The [delivery tests](tests/test_prd_temporal.py) (isolated Temporal execution,
deterministic replay, duplicate dispatch, bounded failures, cancellation and late
result fences) combine real PostgreSQL/Temporal with synthetic runtime observations.
They establish backend delivery behavior; live provider/storage and UI activation
remain separate work.

## Google Docs response normalization

The [backend normalizer](providers/google_docs_normalization.py) (bounded raw
response parsing and supported all-tab content capture) implements the structural
behavior of the published [Google Docs normalization reference](https://github.com/faocampo/curve/blob/6049d229e13e0384d0d3e4c88229720da5f296c1/scripts/lib/google-docs-normalization.mjs)
(nested tabs, supported elements, suggestions and image-byte substitution).
It consumes the full original UTF-8 response, the expected document identity,
explicit all-tab inline-suggestion read options and trusted image captures.
Duplicate keys, malformed JSON, unsupported nodes and unresolved references
produce fixed errors. Unknown metadata remains in the normalized content.

The runtime must supply positive document-byte and combined-image-byte limits.
Traversal is bounded by depth and node count; strings must be valid UTF-8,
numbers finite, and integer tokens within the interoperable safe-integer range.
The backend also rejects empty referenced image/list definitions. These stricter
checks prevent an incomplete provider response from claiming supported capture.

Authorized image bytes replace temporary content URLs with SHA-256 and byte
length. Rotated URLs with identical bytes normalize identically. The image
capture type carries a trusted-runtime observation; constructing it establishes
no authorization. The consuming runtime must independently check current actor,
workspace, connection, source/evidence access, safe image destinations, response
limits and deadlines before invoking this function. It must request an unmasked
response itself rather than accepting browser-supplied read options.

Revision provenance is returned separately. Normalized content remains protected
in memory; result/image representations omit payload fields. The module performs
no network fetch, storage write, lifecycle transition or live activation. Body
serialization/digest identity and current exact-subject readiness remain duties
of the consuming checkpoint runtime. Comments and unsupported drawings/linked
content require their own reviewed capture contracts.

The [normalization tests](tests/test_google_docs_normalization.py) (synthetic
provider-shaped content, suggestions, images, malformed JSON, limits and unresolved
references) exercise this boundary without Google access. Three isolated
cross-language comparisons also matched the published reference's normalized
values for supported nested content, unknown metadata and images.

## Exact-subject structural readiness

The [readiness evaluator](prd_readiness.py) (required sections, acceptance coverage
and current-record checks) consumes protected normalized PRD and Idea Brief bytes
from trusted capture/storage reads. It verifies each body's actual byte digest
and document/workspace/Initiative identity before extracting content. It preserves
that byte identity rather than reserializing the body to calculate a new digest.
The consuming capture runtime remains responsible for its approved normalization
and canonical serialization contract.

The [readiness profile](prd_candidate_policy/prd-readiness-profile-v1.json)
(required Idea Brief/PRD sections and declaration syntax) is copied byte-for-byte
from the published [Curve readiness profile](https://github.com/faocampo/curve/blob/6049d229e13e0384d0d3e4c88229720da5f296c1/contracts/policy/prd-readiness-profile-v1.json)
(candidate structural rules). Its file digest is checked on every evaluation.
Existing core policy and public-contract pins remain unchanged.

Headings, nested subsections, table cells and section-titled tabs supply body
content. Duplicate, missing, empty and placeholder sections block readiness.
Headers, footnotes and tables of contents cannot replace required body sections.
Requirement and acceptance IDs must have descriptions, be unique and provide
complete declared-requirement coverage. Unsupported body structures fail closed.

Inventory input is closed, bounded and bound to both exact body digests, the
workspace, Initiative and evaluation instant. Blockers require resolution
references; assumptions require active human owners, validation-plan references
and due stages. The consuming runtime must independently establish a complete
inventory and resolve those references and owners through current domain reads.
A browser-supplied completeness flag or reference string grants no authority.

The immutable in-memory result exposes a detached metadata-only report with the
profile digest, exact source/version/subject, evidence snapshot, inventory digest,
evaluation instant and stable reason codes. Final report validation requires every
exact expected subject field and a current READY result. The caller must retrieve
the report through authorized immutable persistence and derive the expected
subject from current records; the validator establishes no permission grant.

The [readiness tests](tests/test_prd_readiness.py) (missing content, traceability,
scope/digest substitution, stale inventory/reports, immutable output, byte limits
and malformed input) use the backend normalizer and fabricated content. Four
cross-language report comparisons matched the published reference for supported
ready, missing-section, unresolved-blocker and stale-inventory cases. Semantic
business review, inventory persistence and checkpoint-runtime wiring remain
required before live submission activation.

## Readiness report persistence

The [readiness record](prd_readiness_models.py) (append-only assessment metadata)
stores READY and BLOCKED reports under an existing workspace, Initiative,
document binding and current human submission policy decision. The
[repository](prd_readiness_repository.py) (active-receipt transactional append)
provides a standalone audited append and a metadata-only helper for composition
inside an owning command's single linked audit transaction.

The [migration](migrations/0016_prd_readiness_record.py) (database scope, shape,
profile and immutability guards) rejects extra payload fields, invalid reason
codes, subject substitution, stale Initiative versions and incompatible policy
decisions. Updates and deletion are refused; reversal requires an empty table
or a separately governed preservation migration. Report bodies, provider
responses, approval rationale and deployment retention values are excluded.

Assessments can precede creation of the final native checkpoint. Idea Brief
version and evidence snapshot IDs are historical metadata references in this
record. Before consuming a report, the trusted runtime must resolve their
same-workspace immutable owners, current complete inventory and exact protected
body subjects. Existing checkpoint completeness references are preserved without
fabricated backfills. Persistence grants no provider or storage permission.

The [persistence tests](tests/test_prd_readiness_models.py) (READY/BLOCKED round
trips, tenant and Initiative isolation, direct-SQL guards, atomic audit rollback,
duplicate identity and retained migration preservation) run against PostgreSQL.
The [completion service](prd_completion.py) (accepted-command final transaction)
requires a fresh READY report for submission and compares it with the current
Initiative, exact checkpoint bytes, provider version, binding and evidence
snapshot. Its identity must equal the accepted completeness-check reference.
The report is persisted under the same active human policy receipt as the
checkpoint, lifecycle transition, Operation result and single linked audit;
failure rolls back the complete domain effect.

Preparation supplies an independently resolved current readiness subject.
The trusted runtime must refresh its Idea Brief, evidence and inventory ownership
and identity during final local revalidation. Copying expected fields from a
browser report does not establish those facts. Assessment occurs after command
acceptance and before checkpoint recording. Completed-command redelivery returns
the committed outcome without inserting another report.

The [completion tests](tests/test_prd_completion.py) (normalized synthetic PRD
assessment, return/resubmit/approve, missing or blocked reports, subject mismatch
and outbox rollback) exercise report persistence through the real lifecycle
service. Live protected-storage runtime activation and user-facing submission
wiring remain subsequent integration work.

## Regression commands

[Database tests](tests/test_prd_metadata_models.py) (empty/material evidence,
successor history, incomplete writes, injection, tenant substitution, concurrent
submissions and reversible migrations) use real PostgreSQL with SQL guards.

[Checkpoint tests](tests/test_prd_checkpoint_models.py) (exact round trips,
cross-tenant/cross-Initiative substitution, raw-write immutability, successor
races, cancellation, outer rollback and migration preservation) cover the
external capture dependency.

```sh
pytest plane/curve/tests/test_prd_metadata_models.py --create-db
pytest plane/curve/tests/test_prd_checkpoint_models.py
pytest plane/curve/tests/test_prd_review_validation.py
pytest plane/curve/tests/test_prd_review_models.py plane/curve/tests/test_prd_review_rationale.py
pytest plane/curve/tests/test_prd_lifecycle_repository.py
pytest plane/curve/tests/test_prd_policy.py plane/curve/tests/test_prd_policy_context.py
pytest plane/curve/tests/test_prd_commands.py
pytest plane/curve/tests/test_prd_accepted_commands.py
pytest plane/curve/tests/test_prd_acceptance_api.py
pytest plane/curve/tests/test_prd_completion.py
pytest plane/curve/tests/test_prd_readiness.py plane/curve/tests/test_prd_readiness_models.py
pytest
python manage.py makemigrations --check --dry-run
```

Use `--create-db` only against the disposable test database. Forward migration
adds metadata tables without rewriting existing Initiative/provider/Plane rows.
Reverse migration locks the new tables and fails atomically if any contains
metadata. Retained use requires a preserving migration or governed retention
operation. These tests perform no live deployment or protected-copy erasure.
