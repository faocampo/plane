# C1: local existing-work scope proposals

This independent candidate lets an ordinary STANDALONE Initiative record a finite
proposal while DRAFT. Every selected ordinary native Issue is either
`CONTEXT_EVIDENCE` or `PROPOSED_DELIVERY`. Neither is an approval, binding, reservation,
execution obligation, completion credit, or automatic PRD evidence snapshot.
There is no source mutation, import, descendant expansion, future-task selection,
new gate, plan service, or live provider integration. Association END still returns
503 until its authoritative dependency guard exists.

## Activation and immutable predecessors

Trusted server configuration must enable Curve for the exact workspace, set
`CURVE_ENVIRONMENT` to `LOCAL`, set `CURVE_SCOPE_PROPOSALS_ENABLED` to boolean true,
and supply the established `CURVE_LOCAL_PLANE_INSTALLATION_ID`. The new flag is
false by default and has no environment-variable activation path. Existing
ProjectAssociations must already exist; this flag cannot create or adopt one.

`scope_proposal_candidate/policy-v1.json` (independent C1 authority) has a fixed
SHA-256 pin in `scope_proposal_policy.py` (fresh local authorization).
`scope_proposal_candidate/manifest-v1.json` (closed request/resource/event schema
checksums) is independently pinned by `scope_proposal_contracts.py` (contract
integrity and output validation). No earlier Initiative, PRD, provider, or
association schema/policy bytes are changed.

## HTTP contract

Session authentication and normal CSRF apply. All responses are no-store.
Routes are under `/api/v1/workspaces/{slug}/curve/initiatives/{initiative_id}/`:

- `POST scope-proposal/`: exact body is `expected_scope_revision` (0 initially,
  then current revision) and `items`. Each item has exactly `association_id`,
  `association_version`, `source_issue_id`, and `purpose`. Installation, source
  project, Product, and observations are resolved by the server. Requires
  `Idempotency-Key` and `If-Match: "curve-initiative:{initiative_id}:vN"`.
- `GET scope-proposal/`: current complete immutable revision. No proposal is 404.
- `GET scope-proposal/revisions/{revision_id}/`: exact historical revision with
  current item visibility. No partial/redacted member list is returned.

Successful replacement returns 201 and an immutable revision Location. GET returns
200. ETag captures the Initiative version produced by that revision; it is not a
promise that an unrelated later Initiative edit has not advanced the version.
Obtain current Initiative metadata for a new write precondition.

Maximum request JSON is 65,536 bytes, read at most limit+1 before parsing without
trusting Content-Length. Maximum membership is 100 total. UUIDs are canonical;
versions are bounded integers, never booleans. Unknown/duplicate JSON keys,
non-finite constants, extra selection directives, duplicate issue identities even
across purposes, and oversized manifests fail closed. Ordering is canonical.
An empty replacement explicitly withdraws current scope while preserving history.

Missing preconditions return 428, stale Initiative/scope revisions 412, invalid
closed bodies 422, excessive bytes 413, state conflicts 409, and unavailable source
identities 404. An association-version mismatch is 412 only after the exact
association/project/item is currently visible; inaccessible/wrong-scope identities
remain 404. Changed-subject idempotency-key reuse is 409.

## Native visibility and observations

The selector is grounded in `plane/db/models/issue.py` (IssueManager's ordinary
nondeleted/nondraft/nonarchived/non-triage predicate),
`plane/app/views/issue/base.py` (IssueListEndpoint.get, IssueViewSet.list/retrieve,
and IssueDetailEndpoint.get guest restrictions), and
`plane/app/permissions/base.py` (native role admission).

Require a fresh active non-bot human, active known-role WorkspaceMember, same-tenant
Initiative and Product, exact active ProjectMember, and active same-Product
ProjectAssociation. Even a public project's nonmember is rejected. Editing additionally
requires current Initiative creator or workspace administrator and DRAFT state.
Each selected Issue must be in the association's exact workspace/project, with
nondeleted ordinary State and Project. A project guest (role 5) with
`guest_view_all_features=false` sees only their own created Issues, including
explicitly selected children. Roles other than 5, 15 and 20 fail closed. This native
edition has no separate private-Issue field; DraftIssue and draft ordinary Issues
are excluded. Permissive subissue endpoints and creator shortcuts do not expand C1.

The fingerprint contains only native identity/lifecycle coordinates: Issue,
workspace, project, parent, State, creator, draft/archive/delete flags, Issue
updated_at and State group/updated_at. Source queries defer names and descriptions;
C1 neither fetches nor hashes task bodies. It is an observation, not content proof,
current authorization, or task ownership. A future content-sensitive review bridge
requires its own exact contract. No source names/descriptions/comments/emails are
stored in proposal, policy, event, audit, or outbox projections.

Transactions lock Workspace, User, WorkspaceMember, Initiative, Product, head,
associations, Projects, ProjectMembers, Issues and States in deterministic order.
Final decisions are recorded only after every selected item is authorized, including
the original immutable members on an idempotent replay. Decision inputs bind the
trusted installation and canonical authority/source/association-fence digests. A
forbidden item yields DENY/DENIED; a visible stale version yields ALLOW/NO_EFFECT.
Final rereads fence authority, guest policy, source lifecycle coordinates, and exact
association identity/version. Losing a final authorization fence rolls back the
provisional ALLOW and domain effects before a new immutable DENY is recorded. Replays authorize every original member, not merely
the latest replacement; native progress can change an observation without rewriting
history, but missing/moved/archived/inaccessible identities deny it.

## Storage and PRD compatibility

One head per workspace/Initiative points to immutable revisions and normalized
immutable member rows. Each replacement bumps both the head and existing Initiative
version. Existing Initiative wire projection and three gate assignments are unchanged.
The revision, head, members, event, outbox, completed idempotency outcome, policy
decision and exactly one linked audit commit atomically. No source FK prevents native
Issue deletion or cascades away retained proposal evidence.

`migrations/0021_scope_proposal.py` (additive storage and PostgreSQL guards) enforces
same-tenant references, DRAFT/current authority, next revision/predecessor, member
identity uniqueness, immutable history, current pointer monotonicity and complete
publication. Once a revision is published, child insertion is blocked as well as
update/delete; deferred checks prohibit unsealed/orphan revisions. Destructive
reversal refuses if any C1 rows or policy/audit/event/outbox/idempotency evidence
remain. Disabling the feature preserves all evidence.

`scope_prd_guard.py` (always-on legacy PRD compatibility fence) rejects SUBMIT or
APPROVE whenever current intact scope includes proposed delivery, and rejects
missing/inconsistent scope metadata. It validates actual current members and digest,
not only a cached count. Checks cover intake, accepted replay, worker completion,
prior-success replay and final repository effects under the Initiative fence,
independent of the C1 flag. Empty/context-only scope and truly unscoped Initiatives
retain existing behavior. Historic superseded delivery is not current scope.
Authorized cancellation/failure settlement and terminal failed/cancelled no-effect
results remain available. No new successful PRD effect or prior-success replay is
allowed to bypass the bridge. C2, its exact reviewed subject, and any controlling
binding remain unavailable.

## Verification

`tests/test_scope_proposal_api.py` (real PostgreSQL bounded API, native visibility,
concurrency, integrity and rollback tests) exercises supported construction.
`tests/test_scope_prd_guard.py` (real PRD intake/completion/repository integration)
uses clearly labeled disposable fault injection for otherwise unreachable old
accepted-command/corruption races; production guards are not patched out.
Run with migrations, never SQLite/model-only migration emulation:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest plane/curve/tests/test_scope_proposal_api.py plane/curve/tests/test_scope_prd_guard.py --migrations
python -m pytest plane/curve/tests --migrations \
  --ignore=plane/curve/tests/test_temporal_orchestration_workflows.py \
  --ignore=plane/curve/tests/test_prd_temporal.py \
  --ignore=plane/curve/tests/test_temporal_contracts.py
```

The three excluded suites require the independently qualified Temporal test server.
This bounded suite does not claim live-provider qualification, production activation,
full API/Temporal validation, browser pixels, plan readiness, or controlling bindings.

### Local verification result, 2026-10-03

Against preserved predecessor `ce0fe72b91b5ce32fbc8dc31936e5b01bf93a147`, the final
bounded command above passed **1,626 tests**, including **66 C1 API/permission/audit
cases** and **69 legacy PRD scope-guard cases**, with real migrations. Django system
checks and migration-drift checks passed in the same run. Ruff lint/format, Python
compilation, schema/manifest pin checks, and whitespace checks passed. The fresh
migration was also applied independently to the disposable local database.

The runtime was Python 3.12.14, Django 5.2.15 and PostgreSQL 17.11. The existing
missing-collected-static directory warning remains; it does not qualify browser
behavior. Owned disposable PostgreSQL/Redis services were shut down after testing.
No deployment, publication, checkpoint tag change or live-provider action occurred.
The implementation remains default-off and awaits the separate C2 approval-subject
bridge and any later controlling-binding/gate work.
