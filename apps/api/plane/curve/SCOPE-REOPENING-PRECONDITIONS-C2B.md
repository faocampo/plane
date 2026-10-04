# C2b minimal protected reopening preconditions

Status: approved contract shape; commit this separate schema/policy packet before
implementing the route. This additive read closes the fresh-client precondition gap
in `SCOPE-REOPENING-C2B.md` (atomic reopening and replacement contract). It adds no
plan, control, execution, membership selection or authorization grant.

GET `workspaces/{slug}/curve/initiatives/{initiative_id}/scope-reopening/v1/preconditions/`
is session-authenticated, LOCAL and default-off under the existing reopening
switches. It resolves the exact already-known workspace and Initiative. There is
no body, provider network call, old member source-access prerequisite or GET side
effect. Fixed non-enumerating 404 covers denied, missing, damaged or unavailable
subjects. All responses are no-store; success has strong numeric Initiative ETag.

`scope_reopening_read_candidate/` (closed minimum DTO and independently pinned
read-only ProductApprover policy) defines schema
`curve.scope-reopening-precondition/v1-candidate`, policy edition
`EXPLICIT_SCOPE_REOPENING_PRECONDITION_READ_V1`, action
`CURVE.SCOPE.REOPEN_PRECONDITIONS.READ`, and policy key
`CURVE_SCOPE_REOPENING_PRECONDITION_POLICY`. The trusted ACL resolver must receive
this exact read action. Current human ProductApprover membership, active gate
assignments and ordinary risk/separation rules remain mandatory. Creator/admin
status is no substitute. Revalidate authority and exact Initiative/head snapshot
under the same database transaction after callbacks. Integrity and qualified
pre-plan coverage checks remain active; retained scope history grants no access.

The only response fields are schema_version, policy_edition, workspace_id,
initiative_id, initiative_version, expected_scope_revision, eligibility and
pending_reopening. The two IDs only bind the already-known request target and
must match on the client. Eligibility is REOPENABLE or STATE_BLOCKED; it is
advisory and never grants permission. Pending state is one boolean. No Product,
source, association, checkpoint, decision, old-member identifiers, titles, names,
counts, descriptions or body data are exposed.

The command still independently checks current ProductApprover/action ACL,
pre-plan coverage, both version preconditions and native access to every member
of the complete replacement for the actor and all reviewers. A stale read may
produce a normal precondition conflict, never bypass authorization. A fresh
client can obtain these minimum pins even after an old member becomes
inaccessible, then submit an accessible explicit replacement.

Required tests: missing/denied/disabled and exact read-action ACL; creator/admin
substitution denied; immutable read snapshot; no-store/ETag; changed authority or
version during callback denied; no old/source/checkpoint fields; fresh-client
inaccessible-old-member -> precondition read -> replacement -> new PRD review;
swapped-target DTO rejection at the transport boundary. Existing C1 and C2a DTOs,
write edition bytes and physical/migration qualification are unchanged.
