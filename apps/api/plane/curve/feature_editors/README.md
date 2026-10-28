# Product Feature editor persistence candidate

Status: local registered storage migration and runtime qualification; no service route or activation.

The approved policy gives the Product owner and workspace administrators authority
to manage explicit Product-scoped Feature editors. Feature changes require the
current Product owner or a current explicit grant. Restored membership requires
a fresh grant.

`membership-lifetime.sql` (transactional membership lifetime tracking) supplies the
storage identity a grant must bind. It backfills existing memberships at generation
zero and tracks model saves, queryset updates and direct SQL. Deactivation, soft
deletion, identity reassignment and hard deletion advance the generation. Restoration
keeps that generation; UUID reuse advances it again. Unrelated metadata and role
changes preserve it. Truncation advances existing lifetimes. Lifetime records remain
after membership deletion and reject direct mutation or deletion.

The initial SQL candidate was tested in rollback-only PostgreSQL transactions.
Migration 0046 (Feature editor storage) now installs it atomically, with a membership
write barrier covering backfill and trigger installation. Previous migration bytes
and qualification records remain unchanged. A separate pinned storage successor
validates the new catalog and SQL bytes while preserving prior command authority.
Reversal refuses to remove any retained grant, including revoked history.

`../feature_editor_rules.py` (permission decisions over locked server facts) consumes
the membership generation and exact grant scope. It produces a reason code, not a
policy receipt. Future command adapters must lock workspace, relevant memberships,
users, Product and grants in a deterministic order, resolve all facts server-side,
record policy/audit evidence, and repeat current-access checks before successful
idempotent replay. Grant/revoke commands, Feature writes and API integration remain pending. No client-supplied generation grants authority.

Qualification must cover transactional rollback, current membership after waiting
for concurrent writers, duplicate grants, cross-scope references, fresh grants after
restoration, immutable history and retained evidence on reversal. The focused
lifetime tests establish only the currently implemented storage behavior.

## Grant retention storage

`grants.sql` (scoped grant records and final revocation) preserves each original
grant at version 1 and permits exactly one revocation transition to version 2.
Skipped versions, rewinds and additional revocations are rejected. Grant identity, recipient,
Product scope, membership generation, original actor and timestamp are immutable.
A replacement grant uses a fresh UUID. A partial unique index prevents duplicate
unrevoked grants within one membership lifetime; previous lifetimes remain stored
for history and never become current through restoration.

The insert guard locks and verifies the actual membership and lifetime, and the
Product reference has a workspace-scoped foreign key. Revocation remains possible
after target membership loss. Deletion and truncation of retained grants are
rejected. Timestamps are supplied by the application; clock rollback does not
prevent revocation. These constraints prove storage integrity only. Current
human identity, owner/admin authority, Product state/format, policy receipts,
accepted-command evidence and audit/outbox atomicity still belong to the pending
command adapter. This SQL does not authorize direct client or API writes.

The initial focused PostgreSQL group passed 73 cases: 16 grant storage,
17 membership lifetime and 40 permission decisions. Subsequent validation covers
the installed migration, runtime qualification and existing Roadmap regressions.
Command concurrency, the full native suite and application integration remain pending.

## Migration safety qualification

`external-catalog.sql` (fingerprint of Curve triggers on upstream memberships)
adds the external trigger scope omitted by the historical Curve-table catalog.
It records trigger identity, enabled state, definition and function body. The
historical catalog function remains unchanged. The storage qualification successor
validates both the Curve catalog and this external projection, independently
executing the pinned projection query rather than trusting a database function alone.

`storage-reverse.sql` (transactional rollback with retained-grant protection)
locks memberships, lifetimes and grants before checking for any retained grant.
Both active and revoked grants prevent reversal. With no grants, the candidate
removes its objects and restores the exact predecessor catalog fingerprint; the
predecessor coverage verifier passes afterward. Registered migration 0046 and its
runtime qualification successor consume these exact pinned SQL bytes.

The expanded focused group passes 81 cases, including eight migration-safety
cases. Deleted/disabled membership triggers and replaced trigger bodies change
the external fingerprint. Installation qualification must still bind the expected
fingerprint and reject drift before enabling commands. The installed runtime now
performs those fingerprint checks; grant/revoke command writers remain pending.

## Versioned storage validation

The versioned candidate passed 209 installed PostgreSQL and permission cases,
including grant version transitions, membership restoration, migration qualification,
Roadmap and Product compatibility, and four real-lock concurrency cases. The
concurrency tests observe PostgreSQL blocking before changing membership, and
verify that a waiting grant checks the resulting membership state and generation.
These results cover storage behavior; command receipts and connected UI remain
subsequent implementation work.
