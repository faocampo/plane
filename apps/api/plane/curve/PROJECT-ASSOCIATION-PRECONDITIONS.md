# Native project association precondition read

This read-only prerequisite supports the native Curve Projects association flow.
It does not activate a provider, create credentials, approve a command, write a
native source, introduce a controlling binding, or add a new runtime writer.

## Exact boundary

GET `/api/v1/workspaces/{slug}/curve/products/{product_id}/project-association-preconditions/?source_project_id={uuid}`
requires exactly one canonical lowercase UUID query parameter. The Product path
identity and returned workspace, Product and source identities are bound exactly.
Only session authentication is accepted. All failures, including missing/denied
resources, disabled gates, malformed input and unavailable qualification, use the
same fixed 404 problem response. Every response has `Cache-Control: no-store`.

The closed response in
`project_association_read_candidate/project-association-precondition-v1.schema.json`
(minimal advisory wire schema) contains exactly:

- `schema_version`: `curve.project-association-precondition/v1-candidate`
- `policy_edition`: `LOCAL_NATIVE_PROJECT_ASSOCIATION_PRECONDITION_READ_V1`
- `workspace_id`, `product_id`, `provider_installation_id`, `source_project_id`:
  canonical UUIDs
- `product_version`: integer 1 through 9007199254740991
- `availability`: `AVAILABLE`, `ASSOCIATED_WITH_SELECTED_PRODUCT`, or
  `ASSOCIATED_ELSEWHERE`
- `association_id`: UUID only for an ACTIVE association to the selected Product;
  otherwise null
- `observed_at`: UTC date-time ending in Z

The strong ETag is exactly `"curve-product:{product_id}:v{product_version}"`.
It is the existing Product command precondition family. A numeric Initiative
ETag, association ETag, weak ETag or a different Product/version is invalid.
No alternate Product identity or association identity is exposed for a conflict.
No source names, descriptions, task bodies, user identities, rationale or command
capabilities are added. Historical ENDED associations do not block availability
and are not disclosed.

## Current authority and atomic snapshot

`project_association_read.py` (transactional current-authority snapshot) reuses
`project_association_policy.py` (existing trusted native READ membership policy).
The original LOCAL-only, workspace and association feature gates still apply.
The installation UUID comes only from the existing server configuration; no
caller-provided installation, fixture or fallback is used in production.

The current database human must be active and non-bot, with current active
workspace membership and exact current native project membership. Native public
visibility or workspace-admin status does not replace exact project membership.
Read authority does not require command administrator authority. Products must be
ACTIVE and native projects unarchived; archived objects return the same 404 even
if an association exists. Missing or hidden objects never become AVAILABLE.

The transaction holds the existing workspace, human, membership, Product and
project row locks. The common workspace lock serializes supported CREATE/END
commands, including the absent-association-row case. Active association rows are
also locked. The read then rebuilds current authority and the exact association
snapshot; changed identity, version, state, membership or installation fails
closed. Supported concurrent changes serialize on these locks. A subsequent
command still independently authorizes current state and checks Product version,
active association uniqueness and idempotency. An observation is advisory and
cannot promise the next command will succeed.

The read makes no audit, policy-decision, domain-event, outbox, idempotency,
aggregate or native-source writes. It invokes no provider adapter or external
ACL callback. The installation/policy/contract/qualification checks fail closed.

## Explicit read-only successor qualification

`scope_reopening_qualification.json` (immutable original C2b compatibility proof)
remains byte-identical, with digest:
`sha256:72bdb3b987ec1925754e6a14dee36cecec3c85706605c052d443628d84e7fb52`.

`project_association_read_qualification.json` (reviewed read-only successor proof)
has digest:
`sha256:5381243df882c087ab61932cda77e286a76b3b3e4b19853be5eea9cc81574f1b`.
It explicitly names the predecessor and this read edition, retains exactly the
same migrations, model catalog, physical catalog, writer inventory and excluded
writers, and extends 120 source pins to 122. The only added modules are
`project_association_read.py` (locked read implementation) and
`project_association_read_views.py` (session-authenticated fixed-response GET).
The only replaced module is `urls.py` (additive read route registration).

`scope_reopening_qualification.py` (reviewed trusted qualification loader)
requires both pinned documents, closed successor fields and the exact bounded
source delta before checking current runtime and database state. This loader is
an explicitly reviewed trust root and is not falsely described as self-protected.
No operator override, feature flag, deployed-catalog blessing or generic rehash
utility can qualify a new writer. The prior proof and historical evidence remain
available independently.

The physical catalog remains
`sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7`.
Local qualification was tested with PostgreSQL 17.11. The standard repository
Docker stack uses PostgreSQL 15.7 Alpine; that stack and cross-version physical
catalog parity are not established by this local proof. Different physical
catalog bytes fail closed pending explicit qualification.

## Typed client

`packages/services/src/curve/project-association-preconditions.service.ts`
(exact-target session GET client) exports
`CurveProjectAssociationPreconditionsService.retrieve(workspaceSlug, scope,
sourceProjectId, signal?)`. The result contains the validated DTO and exact ETag.
`packages/types/src/curve-project-association-preconditions.ts` (discriminated
advisory DTO) exposes an association UUID only in the selected-Product variant.

The new schema is mirrored separately under the existing-work contract manifest;
previous schema bytes and validators remain governed by their earlier entries.
The deterministic existing Ajv generator emits a static validator. No schema is
fetched or compiled in the browser. The client validates exact request coordinates
before network use, snapshots input, rejects wrong editions/extra fields/malformed
or inconsistent data, binds every response to the requested workspace/Product/
source, enforces the exact Product ETag and supports cancellation. Transport
failures remain unavailable; they never synthesize AVAILABLE. There is no write,
CSRF fetch, automatic retry, generated idempotency key, persistence or recovery
command in this read.
