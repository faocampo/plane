# Manual Gate 2 local reconstruction

Status: one qualified successor is installed in local source after 23 prospective
PostgreSQL/API tests. Installed-source regression is in progress. All flags remain
off; this is not runtime activation.
This is new reconstruction, not recovered backend evidence. The implementation
extends the qualified manual draft and scope reader without changing old pins.

## Behavior

PREPARE freezes a currently valid saved draft and original protected inputs.
Only the currently assigned human TechnicalApprover may APPROVE or REQUEST_CHANGES.
Approval atomically reserves every proposed delivery task. A new draft before
approval needs a new PREPARE; after approval, pre-plan editing/reopening is closed.

Native Initiative state remains PLANNING. The separate control state is
PLAN_REVIEW, CHANGES_REQUESTED, MANUAL_APPROVED or RELEASED. PAUSED/CANCELLED
retain ACTIVE ownership physically; their effective hold is displayed separately.
Lost access blocks reads and commands without releasing ownership. No execution,
provider action, model call, repository write, spend or completion credit follows.

Claims are unique by workspace, installation and stable native issue identity.
Existing workspace/native issue row locks serialize first acquisition before the
unique constraint. A moved issue retains its identity; release rechecks its new
project association and every current principal's access. Same-workspace decisions
serialize; this version makes no high-throughput concurrency claim.

RECONCILE retains an immutable observation of explicit claim generations, current
native state, authority and protected rationale. Started work cannot reconcile.
RELEASE requires that same approver, rationale, exact subset, generations and
unchanged observation. This is a human reconciliation attestation; it does not
prove external work is complete. Partial release is supported by the domain rules.
A later owner increments the generation; old command replay never reacquires it.

## Trust and persistence

The [installed proof](../../apps/api/plane/curve/manual_gate2_reconstruction_qualification_v2.json) (closed additive
writer inventory) adds four models, nine runtime modules and migration 0025. Only
model registration/policy identity and routes replace previous runtime sources.
The trusted loader explicitly validates the delta; it does not accept observed
source or database hashes as permission. Historical migration and proof bytes,
and the C2b/manual database seals, remain intact.

The [reviewed catalog](qualification/reviewed-catalog.json) (literal expected DDL
pin) is checked independently against actual PostgreSQL definitions. The catalog
query adds a deterministic constraint-name tie break for multiple composite
foreign keys; no integrity relation is removed. Empty reversal restores the exact
0024 catalog. Retained Gate2 evidence, including isolated NO_EFFECT audit, blocks
reversal. Feature disablement retains the records instead of rolling them back.

The runtime lives in [manual_gate2_v2](../../apps/api/plane/curve/manual_gate2_v2/)
(nine installed modules and pinned schemas); no second candidate runtime remains.
The complete prospective assembler is preserved at local commit
`8fc8e15fb36fa0a8aa7890b40971c8df814c0753`.

Every successful command commits Initiative version, control, immutable record,
claim/history changes, policy, audit, event, outbox and idempotency as one graph.
Deferred SQL guards require the complete exact graph, including original assigned
approver and bound subject. Replay reauthorizes current original materials, returns
the original result/current ETag, and records only a new policy and NO_EFFECT audit.

## Protected manual interface

The [manual control panel](../../apps/web/core/components/curve/initiatives/manual-control-panel.tsx)
(review, reservations and deliberate retry) reads definitions and rationale only
through fresh protected access. A prepared replacement is displayed separately
from the saved draft being approved. The client verifies closed shapes, scope,
ETag, material bytes/digest and returned command identity; server authority remains
mandatory. Focus, identity change and failures clear previously displayed material.
An uncertain POST keeps one in-memory command for deliberate identical retry.
The entry is mounted only with `VITE_CURVE_MANUAL_PLAN_V2_ENABLED=true`, a signed-in
viewer and PLANNING/PAUSED/CANCELLED lifecycle. The independent API flag
`CURVE_MANUAL_GATE2_V2_ENABLED` is explicitly false by default, with the existing
workspace allowlist and draft flag still required. No environment activates the API
flag. Local operator configuration and protected catalog provisioning remain explicit.

Definitions/rationales must already exist in the owner-only synthetic catalog,
with explicit grants for the actor and original owners/reviewers. Preparation lists
at most 25 qualified definitions; it creates no documents or grants. This version
has no production protected-storage/provider adapter or browser authoring editor.
The [adapter contract](../curve-manual-plan-v2/ADAPTERS.md) (synthetic object formats,
monotonic permissions and bounded worker) remains applicable. Do not infer object
access from native membership, nor write protected bodies into Git.

## Verification and remaining boundary

The [verification record](VERIFICATION.md) (executed gates and limits) separates
prospective tests, installed-source checks and synthetic visual evidence.
The [isolated test profile](../../deployments/curve-local-pilot/README.md)
(disposable PostgreSQL/Valkey with no published ports) is the only test target.
No production, existing checkout, remote branch or deployed service is changed.
