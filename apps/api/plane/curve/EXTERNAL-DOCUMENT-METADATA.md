# External PRD metadata persistence

## Scope and contract

This source-only increment implements `ExternalDocumentBinding`, the durable
reference needed by immutable external PRD checkpoints. Its exact application
base is `358e2f5fe5d6130b8a81018177a9ecfb6b0e7c19` (the preceding cancellation
fix on the public contract-consumer branch).
The additive migration follows the Curve
[integration contract](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/docs/technical/integration-contracts.md)
(external authoring, source identity, reconciliation and lifecycle authority),
[candidate schema](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/contracts/schemas/external-prd-v1.schema.json)
(closed PRD binding and checkpoint fields), and
[relational contract](https://github.com/faocampo/curve/blob/3b5861401f327a01234d7c27b56e4a6d5384b945/contracts/database/external-prd-v1-relational-contract.md)
(same-workspace references, immutable identity and versioned observations).
The existing vendored public contract edition is preserved byte-for-byte.

This increment has no registered API, provider calls, worker activity, document
body storage, checkpoint/approval endpoint or Initiative transition. The current
provider table continues to accept only its existing local synthetic profile.
The existing Initiative external-resource and lifecycle constraints remain
intact. Source development and isolated synthetic database verification can
proceed while live storage/provider activation evidence is collected.

## Physical representation and enforcement

`curve_external_document_binding` stores only the binding schema fields. Provider
versions remain strings, preserving values beyond integer precision limits.
Nullable revision IDs support providers without durable revision history.
Observations default to `UNKNOWN` access and `RECONCILIATION_REQUIRED`.

- One PRD binding per workspace/Initiative is enforced by a unique constraint.
- Composite foreign keys bind the Initiative and provider connection to the
  same workspace. Parent deletion or a workspace change cannot orphan/re-scope
  the binding. Supporting `(workspace_id, id)` unique indexes are additive.
- A database trigger preserves ID, workspace, Initiative, artifact kind,
  provider connection/file, schema and original human attribution. Deletes
  require a separately governed preservation/successor migration.
- Projection updates require exactly the next version. Concurrent writers
  reading the same version have one winner; stale updates fail atomically.
  Reconciliation time cannot regress or disappear after an observation.
- Database checks constrain schema, state, bounded provider references, HTTPS
  URL shape and the closed human-actor record. ORM bulk mutation is rejected.
- New model instances force insertion; a colliding UUID cannot fall through
  Django's update-before-insert behavior and overwrite an existing row.

Stored access status and creator metadata are historical observations. They do
not establish current authentication or authorization. URL validation checks
shape only; the consuming provider controller must derive the canonical URL
from approved identity/configuration and apply its allowlist. This model never
fetches a URL. Database superuser and schema-management privileges are outside
these row-level guards and must be excluded from the runtime application role.

## Required consuming command work

An authenticated command service must provide current workspace/object/source
authorization, capability checks, Picker receipt or approved template selection,
actor/action/target-scoped idempotency, cancellation fencing and transactional
audit/outbox before exposing binding creation or reconciliation. Provider reads
stay outside the final database transaction. Under the Initiative lock the
command must recheck the accepted version and authority, persist the binding,
record the external-resource boundary, and commit the event/result together.
Those operations require a separately tested lifecycle-constraint amendment;
inserting this persistence primitive alone never creates a live external link.

Checkpoint ArtifactVersion/EvidenceSnapshot records, protected object integrity,
PRD readiness, assigned-human review and the PRD Review to Planning transition
remain the next increments. Retention/storage and documentation-provider gates
remain in force for activation. Actual policy values, approval identities and
deployment configuration belong to approved private governance storage.

## Verification and rollback

[Model tests](tests/test_external_document_models.py) (real PostgreSQL tenant,
identity, version, concurrent-writer and migration tests) exercise ORM and direct
database writes using fictional data. Run them inside the isolated API test stack:

```sh
pytest plane/curve/tests/test_external_document_models.py -q
pytest plane/curve/tests
python manage.py makemigrations --check --dry-run
```

The API test defaults now apply real migrations, including SQL triggers and
composite foreign keys. When reusing an older syncdb-created test database, run
with `--create-db` once. The suite must not use `--nomigrations`: model-only
table creation omits the database guards this increment verifies.

The forward migration creates an empty metadata table and supporting constraints;
it rewrites no existing Initiative, provider or Plane row. Reverse migration
locks the new table and succeeds only when it is empty. Once populated, reversal
fails atomically with a preservation-migration requirement, retaining the table
and guards. The tests prove forward/reverse/forward operation and preservation
of pre-existing parent rows, plus rejection of a populated rollback.

No live migration or deployment is part of this increment. Production activation
requires the accepted consuming command, private storage/access evidence, and a
separately verified migration/rollback plan against the deployment inventory.
