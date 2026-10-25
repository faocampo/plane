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
