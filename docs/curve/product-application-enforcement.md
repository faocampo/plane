# Product application-enforcement successor

Status: implementation candidate; architecture direction selected; focused conformance passed; full regression and integration evidence pending.

This successor addresses R-027 (Product timestamp and format-version conformance) using application enforcement. The historical [Product relational contract](https://github.com/faocampo/curve/blob/main/contracts/database/m1-00a-product-core-relational-contract.md) (original database target and recorded variance) and released migrations retain their original bytes.

## Persistence rules

| Field               | Supported behavior                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `schema_version`    | Application-owned string `1.0`; callers cannot supply it in create/update payloads.                 |
| `created_at`        | Application-generated aware UTC insertion time, retained across supported mutations.                |
| `updated_at`        | Application-generated aware UTC time on accepted mutations.                                         |
| Aggregate `version` | Starts at 1 and increments once per accepted change; determines ordering when clocks move backward. |

The existing physical columns and constraints are preserved. Direct SQL and unrestricted ORM operations can bypass application rules. This successor qualifies the supported service/API boundaries. It neither rewrites existing records nor adds a timestamp or format-version migration.

Timestamps may differ between the Product row and its event, and may decrease across commands when an application clock moves backward. Aggregate version and event sequence establish mutation order. Unchanged, stale, denied and successfully replayed commands preserve Product timestamps and version.

## Unsupported stored editions

An authorized request encountering an unsupported stored Product edition receives HTTP 503 with the fixed problem type `https://curve.example.invalid/problems/curve-product-format-unavailable`. The response contains no stored edition, Product content or internal diagnostic. Existing authentication and authorization denials take precedence.

- Product list and detail serialization reject unsupported editions before returning a successful representation. A list containing such a row returns an unavailable response.
- Metadata, ownership, archive and restore check the stored edition after authorization and before their mutation callback. Rejected commands retain exactly one linked no-effect audit and preserve authoritative rows, events, outbox and idempotency records.
- Creation replay checks the current Product before returning or recording a replay. Existing receipts remain intact on rejection.
- Initiative creation, refinement and resume into alignment validate the associated Product. Historical lifecycle replay ordering remains unchanged; the association guard applies where the existing command reevaluates that association.
- Supported reads resume after the underlying record is restored to a supported edition by a separately authorized repair. The application never silently coerces an unsupported edition.

An allowed read-authorization audit records permission; it does not assert successful representation delivery.

## Compatibility boundary

The additive source-qualification successor adds the shared Product-format guard and replaces only Product serialization, policy, services, association checks, Initiative service exception handling and the shared API error mapper. It preserves all other runtime source pins, historical proof bytes, models, migrations, database catalog and writer authority. The validator requires the exact predecessor and module sets, rejects malformed digests and unchanged replacements, and refuses missing, modified or linked proof files.

See [format guard](../../apps/api/plane/curve/product_format.py) (shared supported-edition check), [qualification manifest](../../apps/api/plane/curve/product-format-qualification-v1.json) (exact additive source delta), and [qualification tests](../../apps/api/plane/curve/tests/test_product_format_qualification.py) (authority preservation and tamper rejection).

## Verification scope

Conformance tests use synthetic data in a disposable database. Malformed editions are introduced through explicit test-only SQL fixtures. Coverage includes read denial and recovery, authorization precedence, supported Product mutations, creation and mutation replay, Initiative association paths, caller override rejection, UTC representation, clock rollback, unchanged timestamp paths and transaction rollback after event/outbox creation.

The candidate requires completed native conformance, repository checks and current-head integration evidence before R-027 closure. Production qualification and activation retain their separately scoped requirements.

Local candidate validation: 106 focused Product, Initiative, timestamp and qualification tests passed with zero skips; all 56 repository check tasks passed; changed Python modules passed Ruff; migration drift check reported no changes. All 19 historical qualification JSON records retained their original bytes. Full backend regression and hosted current-head checks remain required before integration.
