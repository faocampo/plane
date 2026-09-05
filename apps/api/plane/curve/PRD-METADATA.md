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
helpers. API routes, provider transport, protected-body storage and lifecycle
transitions remain subsequent work. Synthetic tests use fabricated object
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
requires the expected Initiative version, Aligning state, intended Initiative
scope and exact previous checkpoint before appending the snapshot/version,
advancing the Artifact pointer and recording the checkpoint. Outer command
failure rolls all of these changes back. These checks fence stale, paused and
cancelled submissions at this metadata boundary.

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
perform no database mutation. They are not yet wired to command handlers.
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
verified at capture and review. Exact-checkpoint human decisions and the Planning
transition remain subsequent implementation work. Live storage/provider
activation remains subject to its existing approval and infrastructure evidence.

## Tests and rollback

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
pytest
python manage.py makemigrations --check --dry-run
```

Use `--create-db` only against the disposable test database. Forward migration
adds metadata tables without rewriting existing Initiative/provider/Plane rows.
Reverse migration locks the new tables and fails atomically if any contains
metadata. Retained use requires a preserving migration or governed retention
operation. These tests perform no live deployment or protected-copy erasure.
