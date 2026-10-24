# C2b bounded scope reopening

Status: candidate packet for parent review; commit this packet and closed schemas
before implementation. Baseline: `3e4c5d9e01dd24948131da70efdbcd3988eac4de`.
Only local pre-plan reopening is authorized. No Gate 2, manual plan, controlling
work binding, execution, completion credit, association END change, publication,
provider qualification or runtime activation is included.

## Explicit successor contract

`scope_reopening_candidate/` (closed command, receipt, event, successor-revision,
policy and pre-plan baseline schemas) pins a new edition:
`curve.scope-reopening/v1-candidate`, policy
`EXPLICIT_EXISTING_WORK_SCOPE_REOPENING_V1`, action
`CURVE.SCOPE.REOPEN_AND_REPLACE_SCOPE`. Old C1 and C2a schema/policy/digest bytes
remain unchanged. New scope revisions explicitly identify schema `2.0` and policy
`REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1`; no optional-key or absent-scope dispatch.

Session-authenticated POST under
`workspaces/{slug}/curve/initiatives/{initiative_id}/scope-reopening/v1/reopen-and-replace/`
requires numeric strong Initiative If-Match, Idempotency-Key, explicit edition
constants, expected_scope_revision >= 1, required reason and a complete replacement
of 1–100 explicit members. Empty replacement is unsupported in this bounded slice:
C2a has no empty-subject review path. Context-only replacement is supported but
still requires a fresh scoped submission and approval; it never regains legacy
unscoped approval compatibility. Raw JSON limit is 64 KiB; unknown/duplicate keys,
duplicate issue IDs, nonfinite numbers, empty/whitespace-only reason and invalid
UUIDs fail closed. Reason is 1–2000 characters. Reason bytes contribute to the
canonical request identity but only reason_digest is retained; reason plaintext
must not enter database JSON, audit, event, log or history. This digest is not
claimed to be retained rationale evidence or a human Gate 1 decision.

Canonical JSON is UTF-8, sorted keys, compact separators, nonfinite prohibited.
Commands hash the envelope edition/action/expected_version/payload. Member
ordering is by source issue ID. The receipt digest hashes the closed public record
minus its digest key. Record limit is 256 KiB. Same-command replay returns the
original 201 only under current authority, intact current successor scope, pending
reopening marker and ALIGNING. A changed current scope or newly submitted PRD
makes that earlier reopening response unavailable as current success.

## Authority and source access

`policy-v1.json` (exact reopening-only ProductApprover policy) is a new policy key,
`CURVE_SCOPE_REOPENING_POLICY`, with one action. It uses the ordinary current human
assignment, object-ACL, classification and separation-of-duty algorithms. The ACL
resolver receives the exact reopening action; CURVE.PRD.APPROVE permission is not
silently substituted. Workspace administrator, creator or project lead status
cannot substitute for ProductApprover. Standard/High require three distinct
currently active human gate assignees; Low follows the existing explicit rule.

All three reviewers and acting human must currently pass native ordinary Issue
access for every replacement member, including restricted guests and explicit
subitems. Resolve exact active association version/provider/project and reject
moved/draft/triage/archived/deleted sources. No implicit child expansion, new task
creation, imported body, persistent permission evidence or source mutation.
Old scope history is integrity-checked without demanding access to removed items;
this permits remediation of deleted, inaccessible or obsolete historical members.
The public receipt contains only replacement members, never removed-item data.
The C1 precondition-discovery gap is closed by the separate read in
`SCOPE-REOPENING-PRECONDITIONS-C2B.md` (minimal protected version pins). It exposes
only already-known target IDs, version preconditions and advisory pending/eligible
status to the current ProductApprover. It grants no write or source permission.

All current checks are repeated after callbacks and before commit under workspace,
Initiative, assignments, Product, human/member, scope head/revision, association,
project/member, Issue and State fences. Native predicates remain necessary because
native writes do not acquire the Curve workspace lock. No network work under locks.

## History, pointers and invalidation

`ScopeReopening` (immutable typed reopening ledger) links the prior scope revision,
new successor revision, prior Initiative version/state, historical checkpoint and
controlling decision, prior pending marker, exact policy decision and event. It
has composite workspace/Initiative foreign keys, closed public receipt JSON and
canonical digest. Protected historical references are internal ledger fields.
The ledger is not a PRD review decision and never fabricates rejection evidence.

One atomic transaction appends ledger/revision/members, advances existing scope
head, sets Initiative to ALIGNING, increments its version, clears
controlling_prd_decision_id, sets pending_scope_reopening_id, and commits policy,
audit, DomainEvent, OutboxEvent and idempotency result. It is allowed only from
ALIGNING, PRD_REVIEW or PLANNING in a verified pre-plan model edition. DRAFT,
PAUSED, terminal and unsupported state/domain editions fail closed. Existing
authorized pause/resume/cancel transitions remain available after reopening with
the marker retained and approval cleared: ALIGNING -> PAUSED (from ALIGNING),
PAUSED -> ALIGNING, and ALIGNING/PAUSED -> CANCELLED. Reopening never resumes a
paused Initiative or reactivates a terminal one. Ordinary ALIGNING metadata edits
may advance the version without clearing the marker or restoring PRD authority.

current_prd_checkpoint_id remains the last retained checkpoint solely as the
predecessor for a later submission. Pending marker explicitly invalidates its
current subject/readiness/approval authority. No checkpoint, readiness, subject,
decision, accepted command or historical Operation status is rewritten. The public
receipt says prd_authority=REQUIRES_FRESH_SCOPED_SUBMISSION and distinguishes NONE
from RETAINED_STALE historical checkpoint status; approval_invalidated is a boolean,
not a disclosure of a prior decision ID. It exposes no previous member list.

Generic PRD metadata and current/scoped subject reads fail closed while pending;
their closed DTOs are not widened. Observation GET also remains unavailable while
pending because it uses that same protected read seam. POST observation returns
its fresh closed DTO directly, and a new POST capture after reload can recover
the required submission inputs; this is a bounded usability limitation, not a
permanent submission dead end. Scope GET dispatches the exact successor revision
schema, which conveys membership but makes no PRD authority claim. A fresh C2a
observation may be captured; a fresh exact scoped checkpoint/subject/readiness and
submission must commit atomically before the marker can clear. The new checkpoint
retains the historical predecessor. A new ProductApprover approval is then required
to reach PLANNING. Successor scope always fences legacy PRD submission/approval,
including context-only replacements and successful historical result replay.
Pending accepted submit/approve commands are immutable history but cannot apply
against new version/scope. Cancellation/failure may settle without domain effects.

## Additive database contract

C1 DRAFT receipt/policy remains unchanged. A separate exact reopening write receipt
is the sole application route to successor revision/ledger writes. DB guards branch
on exact revision edition and require matching same-transaction ledger provenance;
a supplied boolean or forged sidecar does not authorize writes. Immediate/deferred
checks enforce predecessor, version, actor, receipt, members, event, outbox,
idempotency, policy and audit correspondence. Raw SQL cannot publish a partial
head, clear marker without exact fresh scoped subject, restore stale approval,
append a ledger to old history or reopen a nonallowed state. Historical migrations
are not edited; successor migration explicitly replaces relevant guard functions.
Reverse migration refuses retained reopening evidence.

## Bounded pre-plan coverage proof

`pre-plan-baseline-v1.json` (actual C2a model/table-column catalog, migration byte
hashes, known writer inventory and proposed C2b additions) freezes the baseline.
Migration names alone are never proof of deployed bytes or absence of an approved
plan. Qualification has two independent parts:

1. Application verifies exact supported Curve runtime Python module names and
   bytes, pinned migration source bytes and exact registered Curve
   model/table/column catalog against a server-owned local qualification. The final
   0023 digest is pinned in a separate qualification artifact only after its code
   is finalized; the migration does not contain its own source hash. Unknown
   migration successors, source tampering, registered models or catalog changes
   deny reopening. Tests are excluded from runtime writers; migrations are pinned
   separately. The small `scope_reopening_qualification.py` (qualification
   validator/loader) is the explicit trusted root excluded from its own source
   closure to avoid recursive self-hashing. Unknown manifest shapes fail closed.
   This reviewed local compatibility proof does not detect malicious replacement
   of that trusted root, arbitrary outside code, or privileged DB operators.
   External/dynamic writers are unsupported and default-off. No operator boolean
   can waive this proof.
2. DB guards independently verify the deployed physical Curve table/column,
   constraint, trigger and relevant function-definition catalog against an immutable
   versioned coverage seal. Seal installation must validate expected known
   structure/definitions, not bless arbitrary observed database state. Additional
   unmigrated Curve tables/columns or guard drift deny reopening. No privileged
   filesystem read such as pg_read_file is used. A future plan/control writer must
   replace and requalify this proof before it can be enabled.

The qualified writer inventory includes only existing Initiative/Product lifecycle,
C1 selection, C2a/legacy Gate 1, associations and Operation settlement plus this
C2b command. It explicitly excludes every plan approval/control/execution writer.
This is a bounded proof of the supported local pre-plan implementation, not an
assertion that arbitrary external writers or future plan formats are understood.
If reliable coverage enforcement cannot be established in this slice, reopening
stays blocked and verification reports that limitation.

## Required verification

Use newly restored real migrated PostgreSQL, not mocked repositories. Verify all
three allowed starting states; denied ProductApprover substitutes/ACL/revocation;
three-role separation; actor and each reviewer selected-member access; guests,
subitems, association/project/source lifecycle changes; replacement-only access;
malformed/duplicate/oversized/empty input; independent schema/digest pins; source
migration and physical-catalog drift; new model/migration/table; raw-SQL bypass;
immutable and composite-tenant ledger; exact history preservation; no false
approval/readiness read; context-only legacy denial; fresh observe/submit/approve
round trip; replay before and after subsequent work; pending accepted effects;
reopen-vs-submit/approval races in both serialization orders; rollback faults;
marker clearing; repeated reopen; and absence of plan/control/execution effects.

Run C1, C2a, PRD, policy and lifecycle regression subsets plus applicable lint and
migration drift checks. Report Temporal-server exclusions and broad repository,
real-provider, visual and live-runtime checks separately. Local synthetic adapter
coverage does not imply provider qualification, human acceptance or activation.
