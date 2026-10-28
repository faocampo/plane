# Feature command candidate

This additive candidate creates and edits Product-scoped Features. It preserves
the installed Product Feature editor commands and historical qualification records.
The native Roadmap interface and Initiative linkage are separate delivery work.

## Authority and transport

The current Product owner or a current explicit Product Feature editor may create
or update a Feature. Workspace administrators manage editor grants; editing still
requires ownership or a grant. All callers must be active human workspace members.
Restoring membership requires a fresh editor grant for the new membership lifetime.

The Product-scoped `features/` and `features/<id>/` endpoints use authenticated
sessions. Mutations enforce CSRF, an idempotency key and closed inputs. Updates
require an exact Feature `If-Match` version. Successful retries return the original
receipt only after rechecking current authority and protected-description access.
Responses disable caching. The command endpoint setting defaults to disabled.

Lists expose Product-visible metadata and omit protected description references.
Detail reads require separate current access before returning a description
reference. Read access alone grants no editing permission.

## Local protected descriptions

The fixed local material profile requires explicit enablement and a trusted private
root. Its catalog binds immutable references to workspace, Product, access envelope,
classification and an explicit actor grant for the current membership lifetime.
Catalog roots, paths, permissions and actor identity cannot be supplied in API input.

Each Feature operation owns a durable outermost database transaction; nested callers
are rejected so the material lease cannot end before the final commit. A shared
catalog lease lasts through that commit. Current and replacement
descriptions are checked independently; clearing a description still requires access
to the retained reference. Content digests are rechecked immediately before commit.
The separate operator publisher uses the same lock with digest comparison and
monotonic catalog/access generations. It preserves revoked grant history.

This local profile supplies no production object provider or runtime activation.

## Persistence and evidence

Each successful mutation commits the Feature, typed event, outbox entry, linked audit
and idempotency receipt together. Failure rolls those effects back. Native policy
decisions bind the current authority facts and protected-material observations.
Event classification retains the most restrictive referenced material classification.

Migration `0048_feature_commands` adds the exact Feature policy identity and a new
catalog seal. It independently checks the predecessor and external catalog, retains
old seals and refuses reversal while Feature policy evidence remains. The runtime
qualification names every new module and exact replacement; historical manifests
and migrations retain their original bytes.

Focused and native tests cover command retries, version conflicts, role separation,
membership restoration, authenticated HTTP, protected-reference access and catalog
integrity. Complete regression, concurrency, browser acceptance and activation retain
their separate validation requirements.
