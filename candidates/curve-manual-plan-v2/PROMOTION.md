# Promotion and remaining integration gates

Status: review plan only. No runtime promotion or migration has occurred.

## One implementation, one consumer

The [candidate package](overlay/manual_plan_v2/) (eleven modules and pinned JSON)
should be moved, once ready, to the Curve package within the existing Plane API.
The [migration](overlay/migrations/0024_manual_draft_reconstruction.py) (new models,
transaction graph guards and separate seal) moves to its existing migration
package. Do not retain a runnable second implementation in this directory after
promotion. Preserve these review/evidence documents and move tests into the
existing Curve test package. Keep the contract JSON as its normal pinned consumer
snapshot; Curve remains the canonical contract repository.

The [promotion patch](promotion.patch) (model imports, exact additive policy
constraint and four routes) is prepared against Plane's recovered app. It passed
`git apply --check`; it has not been applied. It is insufficient by itself: applying
it or copying modules now would invalidate the incumbent recursive runtime proof.
There is intentionally no script that installs code, fills hashes or enables flags.

## Integration work still required before qualification

1. Implement the transient current-authority contract from real current native
   observations and the fixed catalog. The candidate currently compares native
   row/source fences, all current object grants and file observations, but it does
   **not** construct the required authority DTO with membership/source generations.
   Native role/active observations are not monotonic generation counters. Do not
   invent counters from hashes, timestamps or fixture values. Define and test the
   exact generation source and its revocation/change protocol before promotion.
2. Qualify the producer of the synthetic catalog. It must bind immutable semantic
   facts to the actual approved PRD body, exact workflow/quality/repository policy
   catalogs and original protected inventory. Current code validates closed facts,
   native subject/scope/gates, workflow identity, material versions and bytes; it
   does not yet derive all requirement/acceptance/quality facts from those bodies.
   A hand-edited catalog is test input, not evidence of that semantic binding.
3. Qualify the Linux worker's actual resource limits, parser isolation, interruption
   cleanup and two-worker ceiling. Host tests only prove fail-closed Mac behavior
   and orchestration order with doubles.
4. Review and implement the trusted successor loader. It must preserve the two
   historical proof files byte-for-byte, accept only the declared additive model/
   migration/runtime delta, and independently compare the reviewed physical
   catalog. Keep execution, approval and controlling bindings excluded. The current
   missing loader yields 503 and cannot be replaced with a permissive fallback.
5. Integrate the separate scope-reader candidate as its own reviewed successor,
   after the draft successor. Reconcile shared route edits once; do not repin an
   arbitrary combined application directory.

These are concrete remaining implementation gates in addition to Docker access.
Passing host tests is not sufficient to remove them.

## PostgreSQL sequence after access approval

Use the [isolated test profile](../../deployments/curve-local-pilot/README.md)
(synthetic disposable services and the existing read-only source mount). The
source-mount denial remains unresolved; do not retry Docker, change permissions,
copy the source to another mount or alter sharing without the pending approval.

1. Execute the recovered 0023 baseline and its existing PRD/scope/reopening races.
   Record exact image, PostgreSQL version, source HEAD and catalog. Preserve the
   23 predecessor migration bytes and both historical proof files.
2. Run the [SQL function tests](postgres_tests/test_shape_sql.py) (closed schema
   validation and canonical digest behavior) in a disposable transaction on that
   baseline. They create only the two candidate validation functions and roll them
   back. Do not mistake these tests for application-graph or migration tests.
3. Complete the integration gaps above, then exercise the additive migration in
   an explicitly reviewed qualification harness. The candidate's unset
   `CURRENT_CATALOG_DIGEST` rejects execution before SQL. Do not populate it by
   observing a deployed database, monkeypatching the installed runtime or adding
   an environment bypass. Review the expected source/DDL delta and experimental
   evidence before proposing the literal pin and separate immutable seal.
4. Exercise the real service with synthetic fixtures built from the existing
   scoped PRD bridge. A valid fixture needs actual retained PRD/evidence bytes,
   exact semantic facts and grants for every actor/reviewer/owner; the canonical
   contract fixtures alone are not an executable positive integration fixture.
5. Review the candidate's exact migration/source/proof hashes, then run the
   [installed guard tests](postgres_tests/test_installed_guards.py) (distinct seals,
   qualified loader and direct truncation/seal-rewrite rejection) plus the full
   acceptance matrix below. These tests fail rather than skip missing qualification.
6. Check Django migration state versus models, all historical gates with the new
   feature disabled, enabled route behavior, and the authenticated native UI.
   Only then consider a local runtime promotion. Public delivery remains separate.

## Required real-database acceptance matrix

| Scenario | Required evidence | Current state |
| --- | --- | --- |
| Forward migration and exact catalog | All prior hashes preserved; two models, new seal and precise permitted SQL delta | Not run |
| New save | Revision/head/version/policy/audit/event/outbox/idempotency all commit once | Not run; host ordering only |
| Revision append and historical read | Immutable predecessor retained; original private identity and current permissions | Not run |
| Replay after a later revision | Original response reference, current ETag, no new domain effect; current authority rechecked | Not run; host orchestration only |
| Two concurrent saves | Independent connections/barrier; one winner for the same expected versions; no orphan graph | Not prepared as executable integration fixture |
| Lost access or source changes | Revoke each actor/reviewer/owner; change source/catalog/object before final fence; zero partial graph | Host doubles only |
| Missing/forged graph component | Raw SQL omits or substitutes each policy, revision, head, event, outbox, audit or idempotency link | Not run; must be added with positive fixture |
| SQL mutability and seal attacks | Update/delete/truncate, predecessor/workspace substitution, seal/catalog tampering | Smoke tests prepared; full graph tests pending |
| Reversal with evidence | Refused under locks for draft or related retained records, including NO_EFFECT audit | Host gate only; real DB pending |
| Empty reversal | Exact original coverage function/catalog restored, no historical row deleted | Not run |
| Disablement and edition mismatch | Uniform unavailable responses, no private paths/bodies, no false ABSENT status | Host HTTP/gate tests only |
| Normal CSRF and authentication | Real session middleware plus token/origin checks and closed JSON bodies | Host HTTP dispatch tested; authenticated stack pending |

The proposed empty-reversal check holds exclusive table locks until its enclosing
atomic migration completes, preventing new evidence between the emptiness check
and destructive DDL. Its actual locking/deadlock behavior also requires PostgreSQL.

## Gate 2 follows a separate successor

The [qualification delta](overlay/manual_plan_v2/contract_snapshot/qualification-delta-v2.json)
(explicit draft-only writer inventory) excludes plan approval and controlling task
bindings. Do not add those writers to this migration, reuse a draft receipt as a
Gate 2 grant, or treat a saved plan as execution authority. The separate design in
Curve defines the proposed approval/reservation transaction and its required races.
