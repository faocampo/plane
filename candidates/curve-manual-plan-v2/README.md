# Manual plan v2 persistence candidate

Status: **prepared, not installed or PostgreSQL-qualified**, 2026-10-06.

This is the single Python implementation intended for Plane. Its module layout
matches the proposed runtime delta. It reuses existing scoped PRD authority,
Initiative locking, policy decisions, idempotency, audit, event and outbox services.
It is staged outside the installed application because its recursive source proof
rejects any unreviewed new module, including a default-off writer.

The [verification record](VERIFICATION.md) (executed host checks and unexecuted
runtime gates) and [promotion plan](PROMOTION.md) (remaining integration work,
proof review and migration ordering) define the delivery boundary.

## Prepared behavior

- Two guarded models retain an immutable revision and the current draft head.
  Public revision metadata excludes protected bodies, private identity and receipt.
- A strict closed command binds the typed Initiative ETag, expected draft revision,
  original definition bytes and idempotency identity. New saves produce 201;
  authorized replay returns the original revision with a current ETag and 200.
- The writer prepares one atomic graph: head/revision, Initiative version,
  policy, audit, domain event, local outbox and completed idempotency record.
  A final authority and file observation is required before leaving the transaction.
- The exact local resolver reads bounded owner-only files by opaque UUID. Current
  Initiative grants and per-object grants are required for the actor, all reviewers
  and named owners. Original material/envelope/classification substitutions fail.
- Native PRD and evidence metadata must bind to retained, authorized original
  material. Missing body, selected evidence or excerpt references deny the read/save.
- Validation is inert and isolated before database locks. The proposed Linux worker
  has CPU, wall time, memory, descriptor and concurrency limits. The Mac path fails
  closed; Linux resource enforcement has not been executed in this checkpoint.
- Session authentication uses normal Django CSRF on the original request so DRF
  does not consume JSON before strict parsing. Every response is `no-store`.
- Current/history reads authorize original content again. The separate status
  action is metadata-only; it does not grant old-body access.

These are implemented candidate paths, not claims of integrated backend behavior.
The current-authority projection and reviewed successor loader remain incomplete.
Default feature switches remain off, there are no registered routes, and no
migration or proof has been installed.

## Contents and tests

| Location | Purpose |
| --- | --- |
| `overlay/manual_plan_v2/` (eleven runtime modules) | Intended destination: the same package under Plane's Curve app |
| `overlay/manual_plan_v2/contract_snapshot/` (immutable JSON contract snapshot) | Exact consumer copy; canonical source remains in Curve |
| `overlay/migrations/0024_manual_draft_reconstruction.py` (prepared SQL and model migration) | Stops before DDL while the reviewed current-catalog pin is absent |
| `promotion.patch` (model registration, policy constraint and four routes) | Reviewable patch; checked for applicability but not applied |
| `tests/` (host parser, model, resolver, HTTP and orchestration checks) | No database configured; ORM/service collaborators are doubled where needed |
| `postgres_tests/` (queued SQL and installed-guard tests) | Not executed; function tests target the 0023 baseline, installed tests require a reviewed successor |

Use the existing isolated unit environment, from the Plane repository root:

```sh
.curve-local/unit-venv/bin/python -m unittest discover \
  -s candidates/curve-manual-plan-v2/tests -v
.curve-local/unit-venv/bin/ruff check --config apps/api/pyproject.toml \
  candidates/curve-manual-plan-v2 \
  candidates/curve-manual-plan-v2/overlay/migrations/0024_manual_draft_reconstruction.py
```

The [unit requirements](requirements-unit.txt) (host-only dependency pins) reproduce
that environment. Node.js and the sibling Curve checkout are needed by the exact
JavaScript parity and contract-byte tests. The earlier Python experiment in Curve
has been retired; its historical evidence remains there without a second copy of
the implementation.

## Deliberate limits

This admission profile caps the local catalog at 1 MiB, 128 Initiatives, 128 plans,
512 objects and 16 MiB of total protected input per capture. It is more restrictive
than the contract's individual object maxima and is not production storage.
Selected PRD evidence is bounded at 512 items; all selected bodies and excerpts
are required conservatively, even when a snapshot item is not marked material.
Native membership remains a necessary check, never a sufficient grant.

The SQL functions, constraint timing and rollback behavior require real PostgreSQL.
Gate 2 approval, reservation, execution and completion credit remain excluded from
this draft writer. No provider, AI/model spending or automatic execution is enabled.
