# Submitted PRD and evidence metadata persistence

## Public contract and source scope

This increment implements the metadata dependency for external PRD checkpoint
submission. The following contract documents are publicly available:

- [Curve artifact/evidence specification](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/docs/technical/prd-artifact-evidence-records.md)
  (immutable PRD versions, exact evidence snapshots and provenance).
- [Curve integration contract](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/docs/technical/integration-contracts.md)
  (external authoring, current authorization and lifecycle authority).

The three files in `prd_candidate_schemas` (closed artifact/evidence metadata,
external checkpoint/review and AccessEnvelope schemas) are byte-pinned copies of
the public Curve revision above. The validator separately verifies the existing
common, gate-assignment and Product schemas. The
109-file public consumer edition and its execution/capability gates are unchanged.

This backend increment adds four metadata tables and an internal transaction
helper. API routes, provider transport, protected-body storage and lifecycle
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
version and cancellation fence, bind the DocumentCheckpoint, and commit its
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

```sh
pytest plane/curve/tests/test_prd_metadata_models.py --create-db
pytest plane/curve/tests/test_prd_review_validation.py
pytest
python manage.py makemigrations --check --dry-run
```

Use `--create-db` only against the disposable test database. Forward migration
adds metadata tables without rewriting existing Initiative/provider/Plane rows.
Reverse migration locks the new tables and fails atomically if any contains
metadata. Retained use requires a preserving migration or governed retention
operation. These tests perform no live deployment or protected-copy erasure.
