# C2a exact existing-work Gate 1 bridge

Status: local candidate contract for parent review and commit before implementation.
Baseline: `67e418f7c932d21c56493ce71bbbb229c5c2c567`. No runtime enablement, provider
qualification, publication, controlling work binding, Gate 2, execution, reopen or
association END is authorized by this packet.

## Closed edition and files

The `scoped_prd_candidate/` directory (independent closed command and metadata
schemas, edition policy and raw-byte manifest) defines
`curve.scoped-prd/v1-candidate` and `EXACT_EXISTING_WORK_SCOPED_PRD_V1`. Every
command contains both constants explicitly. Dispatch is by the concrete scoped
command type and these validated constants, never by UUID shape, optional legacy
keys, presence of a sidecar, feature-flag bypass or a runtime boolean.

The new command subject remains a tuple of scalar values. Its canonical request
digest is SHA-256 of UTF-8 JSON with sorted keys, compact separators, no NaN,
and envelope `{edition, action, expected_version, payload}`. Original payload
includes rationale; protected rationale bytes are never retained in command JSON,
events, workflow history or audit. Existing PRD parsers, request digests, accepted
rows, closed schemas, readiness reports and historical decision bodies remain
unchanged. New command records are separate, not subclasses of old table records.

All record digests use the same canonical encoding over the entire corresponding
closed record minus its `digest` key. Members sort by source issue UUID; reviewers
sort by gate type. IDs and timestamps are included. No automatic member expansion
or body capture occurs. Raw command limit is 64 KiB before parsing; every serialized
metadata record is limited to 256 KiB; member count remains 1–100. Duplicate JSON
keys, duplicate member IDs, unknown fields, missing edition, external refs and
non-finite values fail closed. The C1 selection limit remains 64 KiB and unchanged.

## Explicit local routes

All routes are session-authenticated and return no-store responses, under
`workspaces/{slug}/curve/initiatives/{initiative_id}/scoped-prd/v1/`:

- POST `observations`: closed observe command; numeric strong Initiative If-Match
  and Idempotency-Key required. Returns the immutable observation, 201 (same 201
  on replay). An authorized metadata capture, never a GET side effect.
- GET `observations/{observation_id}`: exact protected metadata projection.
- POST `submit`, `approve`, `return-for-revision`: closed scoped commands; same
  headers; asynchronous Operation result, 202. Separate accepted-command table,
  command scope `SCOPED_PRD_V1_{suffix}:{initiative_id}`, command type
  `SCOPED_PRD_V1_{suffix}`, destination `CURVE_SCOPED_PRD_CANDIDATE_V1`.
- GET `subjects/{scoped_subject_id}`: exact checkpoint-bound metadata projection.
- GET `subjects/current`: resolves the current checkpoint subject under the same
  authorization, letting reviewers discover the displayable ID and digest.

These routes are default-off behind `CURVE_SCOPED_PRD_COMMANDS_ENABLED` and LOCAL;
existing PRD command/read and workspace gates still apply. No setting is enabled
by the implementation. No MCP mutation route currently exists: any future adapter
must invoke these guarded application services, never write repository rows.

## Source observation and refresh

`ScopedPrdObservation` stores exact workspace, Product, Initiative/version, C1
proposal/head/revision/version/membership digest, explicit member identities and
purposes, current source_version/fingerprint, all three assignment IDs and human
approvers, capture actor/time, digest and `controlling:false`. It does not revise
C1 source observations or alter Initiative version/state. Creation requires the
current ordinary `CURVE.PRD.SUBMIT` action policy and ACL. It is allowed in ALIGNING
or PRD_REVIEW only, after selection has frozen. All three assignments must be
currently valid human assignments; Standard/High require distinct humans.

Capture atomically appends observation, ordinary policy decision, linked audit,
DomainEvent, OutboxEvent and idempotency response. A no-effect failure rolls back
all domain and idempotency effects; safe denial evidence may remain. Replay
reauthorizes current ordinary action, exact source visibility and unchanged
reviewed metadata before returning an original observation. It never uses old
membership/role/installation as authority.

Every phase locks and validates current Initiative, Product and intact C1 head.
The complete finite set must resolve through `resolve_scope_items`
(native per-item ordinary-Issue access, explicit ProjectMember, restricted guest
ownership and ACTIVE exact-version association fencing). This predicate runs for
the acting human and each of the three currently assigned reviewers separately.
No public-project shortcut, parent/subitem traversal or stored permission proof.
Source outage, unknown native role, moved/draft/triage/archived/deleted sources,
missing/ended/stale association or damaged scope fails closed.

Reviewed coordinates are the existing C1 identity/lifecycle fingerprint plus
source_version, along with exact association/provider/project/member purpose and
reviewer assignment identities. C1 fingerprints include updated_at but no title,
body or acceptance text. A changed reviewed coordinate requires a NEW observation
and NEW scoped submission/checkpoint before approval; old subjects stay immutable.
This conservative behavior catches any updated_at change without claiming to
classify native edits semantically. Observation refresh is allowed after DRAFT;
selection replacement is not. Existing PRD remaining-outcome/acceptance content
and protected evidence are the approval basis; a source fingerprint does not
approve task bodies. Any material task-body evidence must use an independently
authorized existing protected artifact capture, never copied into these tables.

## Additive durable graph

1. `ScopedPrdObservation`: append-only schema-validated bounded payload with typed
   workspace/Product/Initiative, proposal/revision, actor, digest and time columns.
2. `ScopedPrdAcceptedCommand`: independent immutable durable command with scalar
   subject, edition, original digest, actor/action/version, protected rationale
   reference; Operation primary key. Existing legacy rows always use their old
   parser/digest. Only IDs cross the existing worker/activity boundary.
3. `ScopedPrdReadiness`: typed immutable one-to-one link to the original structural
   `PrdReadinessRecord`, exact observation and scope, base-report digest and its own
   closed-record digest. The old readiness report remains structural only.
4. `ScopedPrdSubject`: typed immutable one-to-one checkpoint link; exact artifact
   version/content/provider version/evidence snapshot; C1 scope and purpose-split
   member identities; observation ID/digest; scoped readiness ID/digest; actor/time
   and canonical digest. Checkpoint, original structural readiness, scoped
   readiness and subject commit atomically with the operation/audit/outbox.
5. `ScopedPrdDecision`: typed immutable one-to-one ordinary `PrdReviewDecision`
   link, exact scoped subject ID/digest, state, actor/time and digest. Ordinary
   decision and sidecar commit atomically. A sidecar cannot be appended later to
   retrofit an old decision or checkpoint into scoped authority.

Use composite workspace/Initiative foreign keys and DB immutable triggers. Guard
required sidecars and graph correspondence with deferred transaction-end checks
so a partially written checkpoint/decision cannot commit. Checkpoint and decision
identity, action receipt and current-scope fence are required in scoped repository
entry points; a supplied bool is never a receipt. Reverse migration refuses to
drop retained evidence. No legacy backfill or controlling registry is introduced.

## Acceptance, completion and protected reads

Reuse the ordinary PRD policy context to require the current creator/ACL submit
permission or actual Product Approver gate permission, including ordinary risk
and three-assignment rules. Keep a separately pinned scoped edition policy for
the additional finite-set requirement; no workspace administrator or project
lead gains gate authority. Provider/storage preparation continues through the
existing trusted `prepare`/`revalidate` and `prepare_completion`/
`revalidate_completion` seams outside network-held DB locks; only synthetic
validated local test adapters are in scope.

Native scoped guards run before preparation, acceptance replay, final acceptance,
completion preparation, final completion and successful-result replay, and after
runtime callbacks immediately before commit. Approved source/evidence/body/readiness
checks remain mandatory in the ordinary runtime. Capture neither supplies nor
claims those proofs. Accepted-command recovery reconstructs the exact new parser
and digest. Cancellation/failure can settle safely without applying scope effects;
previous SUCCEEDED operations still require current guarded access and exact
scope in every error/replay path.

Protected GET reads first satisfy the existing trusted PRD read authorization
seam (current object/source/evidence/classification access) and then independently
reauthorize the requested current source and all reviewers under DB fences.
They return only the new closed observation or subject DTO. Original PRD metadata
DTO is not widened. Subject fields supply the exact checkpoint/artifact/evidence,
observation and readiness references required by approve; observation supplies
reviewer identities and finite metadata list. Remaining outcomes are displayed
through the existing protected PRD artifact view, not task-body fields. Hidden or
unavailable records return a non-enumerating response. Historical payloads remain
unchanged but do not grant bypasses of current access or current-head checks.

## Transition and lock contract

DRAFT replacement remains C1-only. Refinement freezes membership. Scoped submit
uses ALIGNING/PRD_REVIEW -> PRD_REVIEW and clears the ordinary current decision.
Approve requires current PRD_REVIEW and reaches PLANNING only. Return for revision
uses PRD_REVIEW -> ALIGNING. There is no post-DRAFT scope-reopen action and no
Gate 2, plan, controlling row, execution, completion credit or association END.

Lock hierarchy follows the existing ordinary policy receipt, then the scoped
current guard: workspace -> current human memberships -> Initiative -> assignments
-> Product -> current users/memberships -> C1 head/revision/items -> sorted
associations -> sorted projects/memberships -> sorted Issues -> States. The
workspace row is a coarse fence serializing Curve policy and lifecycle commands;
native source rows are separately locked because native edits do not acquire that
Curve workspace fence. Operation locks stay inside the existing authorized
callback. Repeat native predicates after all source locks. Reads/commands and
settlement must follow the same hierarchy. Scope head, association and source
lifecycle mutations must either precede validation and fail the command or follow
its commit. C1 DRAFT-only mutation cannot race past a completed refinement or
submission under the Initiative lock.

`scope_prd_guard.py` (always-on legacy delivery-scope fence) remains active at all
legacy acceptance, repository and completion paths independent of C1/C2 flags.
New scoped lifecycle functions are separate and invoke their own exact guard;
they do not catch/ignore a legacy guard failure. Direct legacy services and old
commands on delivery scope remain unavailable even when a sidecar exists.

## Required evidence before claiming C2a complete

Real migrated PostgreSQL tests: immutable observation/readiness/subject/decision;
compound cross-tenant graph constraints; wrong schema/digest/record substitution;
atomic checkpoint/subject/decision/audit/outbox and rollback fault injection;
current-head and association/source races in both serialization orders;
metadata refresh without C1 replacement; actor and individual reviewer access
revocation at prepare/replay/commit; current assignment changes; original-response
and successful-completion replay after revocation; restart and duplicate completion;
cancellation/failure settlement; concurrent completion and subject changes;
unscoped/context-only legacy compatibility; legacy delivery failure with disabled
flags, alternate internal entry points and forged sidecars; approval PLANNING with
zero controlling/execution rows. Negative read/API tests must be non-disclosing.

Run targeted new tests, unchanged C1 guard tests and the bounded legacy Curve
backend suite. Report separately any Temporal-server exclusions, full repository
checks not run, real provider/storage qualification and visual acceptance. Local
synthetic backend evidence is not human UI acceptance or live activation.
