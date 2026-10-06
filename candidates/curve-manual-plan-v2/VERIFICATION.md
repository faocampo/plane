# Manual persistence candidate verification

Recorded: 2026-10-06. This evidence covers the staged candidate, not runtime
qualification, activation, deployment or a completed manual pilot.

## Executed checks

| Check | Result |
| --- | --- |
| Host unittest suite | 67 test methods passed, including adversarial subcases |
| Strict JSON/canonicalization and semantic JavaScript parity | Passed within the host suite |
| Current object ACLs and original material identities | Real temporary owner-only files; changed/missing/symlinked content and denied grants rejected |
| PRD body/evidence binding | Host metadata doubles; exact retained material required; no actual ORM query executed |
| Session/CSRF HTTP behavior | DRF dispatch with normal Django token/origin checks passed; persistence service mocked |
| Save/replay/final authority fence | Host orchestration doubles passed; worker precedes transaction; failure requests rollback |
| Two candidate model shapes and migration state | Exact contract inventory and Django state comparison passed |
| Frozen SQL schema literals | Match fully resolved canonical contract schemas; SQL not executed |
| Contract consumer snapshot | Byte-equal to canonical Curve JSON, with original manifest digest unchanged |
| Predecessor migration preservation | All 23 original raw-byte pins match recovered source |
| Missing migration qualification | Stops before a cursor or DDL; unset catalog pin preserved |
| Missing trusted successor loader | Closed 503; no historical proof or feature flag supplies authorization |
| Ruff lint and formatting | Passed for candidate source, tests and explicitly selected migration |
| Promotion patch applicability | `git apply --check` passed; patch not applied |
| Installed Curve application diff | No change from recovered Plane commit `7d4225d594adf984de1451f16ad2c8ab741c58eb` |

The host used Python 3.14.7, Django 5.2.15, DRF 3.17.1, jsonschema 4.26.0
and Ruff 0.15.12. The [requirements](requirements-unit.txt) (host dependency pins)
and [README](README.md) (commands, component scope and admission limits) describe
reproduction. The maintained Python implementation lives only in this Plane
candidate; the earlier Curve experiment source was removed after relocation.

## Prepared but not executed

The [PostgreSQL function tests](postgres_tests/test_shape_sql.py) (closed schema
and canonical digest behavior on the recovered baseline) and [installed guard
tests](postgres_tests/test_installed_guards.py) (reviewed successor, distinct seals
and direct mutation rejection) are source preparation only. They were not run or
collected against a database. They are not a complete persistence acceptance suite.

No forward/reverse migration, direct SQL guard, real concurrent save, actual
rollback, authenticated application session, Linux worker resource limit, browser
journey or Gate 2 reservation was verified. No production credentials, provider,
AI/model call or paid execution was used. The candidate has no active route.

## Remaining gates

Docker Desktop previously denied the existing source bind mount with
`operation not permitted` before the API container started. The dedicated stack
was cleaned up in the earlier checkpoint. This checkpoint did not retry Docker,
change macOS or Docker permissions, alter mounts, or move source to bypass denial.
The pending operator approval remains required.

Separate implementation gaps remain: current native membership/source generations
and transient authority DTO; catalog facts derived/bound to protected semantic
sources; reviewed successor loader/proof; Linux worker qualification; complete
positive/race/raw-SQL fixtures and real PostgreSQL evidence. The [promotion plan](PROMOTION.md)
(exact integration sequence and acceptance matrix) keeps each gap explicit.
Do not fill the catalog pin from an observed database or report these host tests
as permission to activate a writer. Gate 2 remains a separate proposed successor.
