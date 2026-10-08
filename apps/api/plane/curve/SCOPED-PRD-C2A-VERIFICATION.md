# C2a local verification

Date: 2026-10-04. Contract-first baseline: `e042c4b31` (closed C2a candidate packet
and schemas, committed before implementation). This evidence covers the local
implementation working tree immediately before its parent-coordinated commit.

## Result

Fresh migrated PostgreSQL bounded regression: **1799 passed** in 516.21 seconds.
This includes the 1626-test bounded C1 baseline and 173 new C2a tests:

- [Bridge integration](tests/test_scoped_prd_bridge.py) (27 tests): real C1
  selection/refinement, capture, submit, Gate 1, exact protected HTTP reads,
  metadata refresh, native/ACL revocation, replay, and direct-object parser checks.
- [Integrity](tests/test_scoped_prd_integrity.py) (30 tests): immutable records,
  tenant/digest substitution, transaction provenance, retrofit refusal, exact
  readiness/checkpoint/evidence graph, atomic rollback and Operation identity.
- [Races](tests/test_scoped_prd_races.py) (8 tests): duplicate/competing workers,
  native source/member lock orderings, cancellation, restart and fallback fencing.
- [Scoped Temporal](tests/test_scoped_prd_temporal.py) (30 tests): fake transport,
  local ActivityEnvironment, bounded retry/dead-letter, cancellation, restart,
  exact workflow identity/destination and shared registry.
- [Scoped transport](tests/test_scoped_prd_views.py) (78 tests): closed authenticated
  routes, protected metadata/final-access fencing, request bounds and fixed errors.

Django system check reported no issues. Migration drift check reported no changes.
Ruff E/F, formatting of all 30 changed/new Python files, compilation and whitespace
checks passed. The generated migration explicitly exempts E501 for its frozen
SQL/schema literals; Python formatting left both SQL literal byte hashes unchanged.
The 368 runtime warnings concern the existing absent collected-static directory.

## Reproduction and scope

Using the isolated local runtime wrapper, the final sequence was:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
pytest plane/curve/tests \
  --ignore=plane/curve/tests/test_temporal_orchestration_workflows.py \
  --ignore=plane/curve/tests/test_prd_temporal.py \
  --ignore=plane/curve/tests/test_temporal_contracts.py \
  --migrations --create-db -q
```

These are the same three Temporal suite exclusions as the bounded C1 baseline.
No additional suite was excluded. New scoped Temporal coverage does not require a
Temporal server and does not claim a server-backed history replay. Repository-wide
frontend build/type checks, human visual acceptance and live provider/storage
qualification were not performed by this backend slice.

The final run rebuilt the disposable test database and used the actual migration.
Earlier fast iterations refreshed candidate SQL functions only in the disposable
test database; those iterations are superseded by the fresh final result.
The runtime wrapper returned exit 0, ran owned Redis shutdown and PostgreSQL
fast-stop cleanup, and PostgreSQL confirmed that the server stopped.

## Preserved boundaries

The [contract packet](SCOPED-PRD-C2A.md) (exact Gate 1 and finite-source authority)
and [candidate manifest](scoped_prd_candidate/manifest-v1.json) (raw-byte contract
pins) remain independently versioned. The manifest SHA-256 is
`7543deddb9a56e29c3613b03823afb9cd5e9474dc8bb64016665657cee17b997`.

Gate 1 ends at PLANNING with no controlling task binding or execution. DRAFT scope
membership stays frozen. Source observations contain identity/lifecycle metadata,
not task-body approval or copied descriptions. Ordinary PRD policy and all three
reviewers' current native per-item access remain mandatory. The legacy guard
continues to reject legacy delivery-scope submission/approval, including disabled
feature and replay cases. Association END remains unavailable.

No runtime flag, live provider, storage credential, publication, push or tag was
activated or created. The parent coordinates the implementation commit and a
separate exact-commit targeted smoke before treating that commit as verified.
