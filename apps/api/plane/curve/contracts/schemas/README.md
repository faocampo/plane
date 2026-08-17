# Curve M0-S2 Schema Snapshot

These JSON Schemas are a byte-identical validation snapshot of the normative
Curve contracts at revision
`ab2c81a33ede719c02ff0a2a6ab35eabcf304de1`. The pinned context is recorded in
[`m0-s2-context.json`](../m0-s2-context.json) (M0-S2 source revision, ownership,
and context-pack digest).

The Curve repository remains the source of truth. This snapshot exists so the
Plane implementation can run offline, revision-bound contract tests. A later
Curve contract revision requires regenerating the snapshot and updating the
recorded context revision and digest in the same reviewed change.

| Schema                           | Content                                                                       |
| -------------------------------- | ----------------------------------------------------------------------------- |
| `common.schema.json`             | Shared identifiers, references, digests, actors, errors, and classifications. |
| `operation.schema.json`          | Operation aggregate wire representation and lifecycle rules.                  |
| `operation-event-v1.schema.json` | Operation state-change event payload.                                         |
| `event-envelope.schema.json`     | Durable domain-event envelope.                                                |
| `outbox-event.schema.json`       | Reliable-delivery outbox record and state requirements.                       |
| `inbox-message.schema.json`      | Consumer deduplication record and terminal-state requirements.                |
| `idempotency-record.schema.json` | Digest-only command replay record.                                            |
| `audit-event.schema.json`        | Append-only audit event representation.                                       |
