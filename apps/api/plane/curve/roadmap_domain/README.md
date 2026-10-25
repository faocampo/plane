# Roadmap storage candidate

This additive storage layer introduces Roadmap, Milestone, Feature, RoadmapItem
and append-only Item history. It preserves the existing Product and two-stage
review commands and their historical migration and qualification bytes.

The [qualification manifest](storage-qualification-v1.json) (exact storage source,
model, migration and physical-catalog delta) is validated by the trusted runtime
qualification root. Its allowed source changes are the new model module and
registration in the existing model module. The command writer inventory and
excluded authorities are inherited unchanged.

The [relationship SQL](relationships-forward.sql) (scoped foreign keys,
reciprocal deferred Initiative links and retention triggers) binds both halves
of a Roadmap Item/Initiative pair at commit. Milestone positions support atomic
swaps through deferred uniqueness. PostgreSQL creates an OID-derived recheck
trigger for that unique constraint; the migration assigns it a stable name,
preserving its internal function and enforcement, so independently installed
catalogs have the same exact fingerprint.

The [coverage SQL](coverage-forward.sql) (historical seal validation and current
catalog verification) retains all earlier seals and adds a new immutable seal.
Normal migration refuses an unqualified catalog; populated reversal is refused.
An empty reversal restores the prior verifier and removes only the new objects.

Storage checks do not authorize a user, validate protected document access,
approve a PRD, or create a command receipt. Those responsibilities belong to
scoped services and their forthcoming qualification. No Roadmap API, creation
permission, owner assignment policy or document-review transition is enabled by
this storage-only candidate. History payloads and actor references require the
closed application contracts before any command is exposed.

Regression coverage includes physical drift rejection, repeated migration
roundtrips, retained Product and seal preservation, reciprocal insertion orders,
invalid links, schedules, progress, deferred ordering and immutable history.
Full milestone acceptance additionally requires concurrent commands, replay,
current membership and ownership, protected references, approval supersession,
UI acceptance and completion projections.

## Metadata history successor

The [metadata qualification](metadata-qualification-v1.json) (exact model,
additive migration and catalog pins) qualifies priority, health, confidence and
schedule history types. The [metadata migration](../migrations/0044_roadmap_metadata_history.py)
(constraint expansion and retained-history rollback guard) preserves the original
storage migration and qualification. Its source delta replaces only the Roadmap
model module; model columns and command writer authorities remain identical.

The [metadata coverage SQL](metadata-coverage-forward.sql) (new immutable seal and
full predecessor-chain checks) retains the original Roadmap seal. Reversal takes
an exclusive history-table lock and refuses if any new-type history exists.
When only legacy history exists, reversal preserves every row and restores the
original constraint and verifier. Installation and reversal run atomically.

The [metadata tests](../tests/test_roadmap_metadata_storage.py) (new-type roundtrips,
immutability, loss-preventing reverse, legacy preservation and proof tampering)
exercise native PostgreSQL boundaries. The existing storage migration roundtrip
test continues to target its original migration explicitly; independent attack
fixtures target the current seal so application-level rejection remains tested.

Exact before/after payload semantics remain defined by
[Curve PR #177](https://github.com/faocampo/curve/pull/177) (metadata history
contracts and semantic validation). This storage successor permits those type
names while retaining the established JSON payload column. Command integration
must validate the closed payload contract and current authority, then atomically
write item state, history, receipt, event, outbox and audit. Runtime command and
Roadmap UI acceptance remain pending.

## Hierarchy command and API successor

The [hierarchy qualification](hierarchy-qualification-v1.json) (exact command,
read, route, model and migration source pins) adds only Roadmap and Milestone
hierarchy operations. The [policy manifest](hierarchy-policy-v1.json) (creation,
current-owner mutation and active-human requirements) is checked against the
runtime policy. The additive policy migration preserves all earlier policy
identities and coverage seals; retained new policy evidence prevents reversal.

Creation by an authorized Product owner or workspace administrator assigns the
creator as Roadmap owner. Only the current Roadmap owner changes the hierarchy.
Membership, user activity, Product state and format support are checked before
returning a retained command result. Concurrent duplicates share one receipt;
state, events, outbox and audit commit together. Milestone creation and reordering
advance the parent version. Milestone metadata edits use the milestone version.

The API prefix is `/api/v1/workspaces/{slug}/curve/products/{product_id}/roadmaps/`.

| Relative route                            | Methods    | Behavior                                          |
| ----------------------------------------- | ---------- | ------------------------------------------------- |
| Empty suffix                              | GET, POST  | List or create Roadmaps                           |
| `{roadmap_id}/`                           | GET, PATCH | Read or update Roadmap metadata                   |
| `{roadmap_id}/milestones/`                | GET, POST  | List or create Milestones                         |
| `{roadmap_id}/milestones/{milestone_id}/` | GET, PATCH | Read or update Milestone metadata                 |
| `{roadmap_id}/milestones/reorder/`        | POST       | Submit all current Milestone IDs in desired order |

These session-only routes require `CURVE_ROADMAP_HIERARCHY_ENABLED`, whose
repository default is false, plus the normal scoped Curve settings. Setting a
flag supplies no production activation authority. Session writes retain CSRF
checks. API keys cannot enter this human command lane.

Commands require `Idempotency-Key`; changes also require the exact target ETag in
`If-Match`. A creation or reorder uses the Roadmap version, while a Milestone
metadata update uses the Milestone version. Roadmap creation accepts no version.
Responses contain a stable `resource_ref`, ETag and Location; a replay retains
the original result version, and clients fetch Location for current metadata.
All responses use `Cache-Control: no-store`.

Collections support `page_size` from 1 to 100 and an opaque `cursor`, returning
`results` and `next_cursor`. Roadmaps use an ID keyset. Milestones use position/ID
order and bind the cursor to the parent version; reordered lists reject an old
cursor with 412. Detail routes accept no query parameters. Read projections contain
safe hierarchy metadata and no protected document or scope bodies.

Feature and Item commands, joint Initiative creation, protected references,
approval supersession, the Roadmap-backed document journey and UI acceptance
remain separate unfinished parts of M2-01. This hierarchy slice does not complete
the milestone.
