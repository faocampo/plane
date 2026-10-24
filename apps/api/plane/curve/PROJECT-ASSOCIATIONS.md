# Existing-project association: local candidate

The additive `EXPLICIT_EXISTING_PROJECT_ASSOCIATION_V1` edition links an existing
native Plane Project to a Curve Product. It does not import source data, edit
Plane projects or tasks, create Initiative bindings, imply historical approvals,
or enable a remote provider.

## Activation boundary

This code is disabled by default. It requires all of:

- The existing Curve enable flag and exact workspace allowlist.
- `CURVE_ENVIRONMENT == "LOCAL"`.
- `CURVE_PROJECT_ASSOCIATIONS_ENABLED is True` in trusted server configuration.
- A valid, stable `CURVE_LOCAL_PLANE_INSTALLATION_ID` UUID in trusted server
  configuration identifying this native Plane database installation.

These new settings have no environment-variable activation path. A setting
change, provider registration or successful read does not grant command authority.
No current provider registry/schema pin was rewritten. The independent candidate
policy and closed wire schemas live in `project_association_candidate/` (policy
and request, response and event contracts).

## HTTP surface

All routes are under `/api/v1/workspaces/{slug}/curve/`. Session authentication
with its normal CSRF checks is the only authentication mechanism. Responses are
`Cache-Control: no-store`; API keys and caller role/capability assertions do not
grant authority.

- `POST products/{product_id}/project-associations/`: body contains exactly
  `provider_installation_id` and `source_project_id`. Both are canonical lowercase
  hyphenated UUIDs. Requires `Idempotency-Key` and the current Product `If-Match`
  value, `"curve-product:{product_id}:vN"`. The Product is locked and must be active;
  its version is a precondition and is not incremented. Returns 201, association
  ETag and Location.
- `GET project-associations/{association_id}/`: current authorized identity-only
  projection; no persisted source name, descriptions, comments or member emails.
- `POST project-associations/{association_id}/end/`: exact body is
  `{"expected_product_version": N, "reason": "..."}`. Requires `Idempotency-Key`
  and `"curve-project-association:{association_id}:vN"`. Reasons must contain
  non-whitespace text and have at most 1000 characters. The reason is operational
  metadata visible to currently authorized readers, not protected PRD rationale;
  callers should not include confidential rationale. Product archival does not
  strand reconciliation. The dependency guard currently always returns 503:
  absence of a binding repository is not evidence that no active bindings exist.
  A successful END is implemented and exercised only with explicit test doubles;
  no runtime override or empty dependency fallback is provided.

Missing expected versions return 428; wrong or stale ETags return 412; malformed
closed bodies return 422; active conflicts return 409. Exact versions are positive
integers no greater than 9007199254740991, never booleans. Missing/revoked/cross-scope
resources return a uniform 404 without echoing source details.

## Authority and consistency

Every command requires a freshly loaded active non-bot human, an active workspace
administrator membership, and an active exact ProjectMember row. Even a public
project requires that row. Product authority is resolved from the same-workspace
Product and the current owner-or-administrator rule; the stricter administrator
requirement still applies. Reads permit current workspace members with that exact
project membership and current same-workspace Product visibility.

The transaction locks the Workspace, User, WorkspaceMember, Product, Project and
ProjectMember rows and the association when present. Default native managers
exclude soft-deleted rows. A final trusted reread compares the authority fence
before commit; cached request user flags never substitute for current database
authority. Workspace locking also serializes competing local association commands.
The database separately enforces one ACTIVE association per exact workspace,
installation and project, regardless of Product. Product can have many projects.

Association creation and ACTIVE-to-ENDED are guarded by a live in-process policy
receipt scoped to the exact identity and human attribution. Database triggers
independently preserve identity, initial observation, exact version increments,
terminal state and nondeletion. Cross-workspace Product references have a composite
foreign key, and INSERT checks an active same-workspace native project. There is
no source-project foreign key that would block source deletion or delete history.

Association, immutable DomainEvent, outbox and idempotency completion commit in the
same transaction. Each persisted policy decision has exactly one linked audit.
Command failures roll back their effects and retain one safe NO_EFFECT audit where
policy evaluation was possible; audit failure rolls back the whole command.
`command_receipt_id` and `end_receipt_id` identify immutable DomainEvents, whose
payload includes the exact policy decision ID. The outbox destination is local and
has no new dispatcher/provider activation in this candidate.

Replays first recheck current visibility and the trusted installation. They return
the original safe DTO from its exact immutable event/version, even after ending,
without re-emitting a source mutation, event, outbox row or association.
`source_observed_at` and `source_version` describe the creation-time observation,
not continuous monitoring or current freshness. The source version is native
Project `updated_at`; no protected display projection is cached.

## Preservation and verification

`0020_project_association.py` (additive storage, policy identity and SQL guards)
permits reversal only while no association or new-policy/audit/event/outbox
evidence exists. Once evidence exists it raises before removing guards or data;
rollback requires a preservation migration. Disabling the feature leaves all
history intact. No destructive rollback or source cascade is provided.

`tests/test_project_association_api.py` (real PostgreSQL command, concurrency,
revocation, replay, redaction and database-integrity contracts) covers the local
surface. Run with the documented isolated Docker test stack, with real migrations,
not `--nomigrations`. PostgreSQL row locks and triggers cannot be qualified with
SQLite or model-only tests. The disposable verification environment used Python
3.12.14, Django 5.2.15, PostgreSQL 17.11 and Redis 8.0.2; the documented Docker profile
uses PostgreSQL 15.7. Live installation qualification, visual acceptance, binding
repository integration and an operator-controlled pilot remain separate gates.

### Reproducible checks

From `apps/api/` (Django application root) in the isolated test stack:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest plane/curve/tests/test_project_association_api.py --migrations
python -m pytest plane/curve/tests --migrations \
  --ignore=plane/curve/tests/test_temporal_orchestration_workflows.py \
  --ignore=plane/curve/tests/test_prd_temporal.py \
  --ignore=plane/curve/tests/test_temporal_contracts.py
```

Local verification on 2026-10-03 passed all 57 association cases and 1491 tests
in the broader bounded command above. Django system checks and migration-drift
checks passed, as did Ruff lint/format, Python compilation and whitespace checks.
A fresh disposable database rebuild separately verified the migration and SQL
guards; the subsequent regression used that migrated database.

The three excluded suites require the separately qualified Temporal test-server
runtime; excluding them is not a full API or Temporal validation. Use `--create-db`
once when a disposable test database predates this migration's final guards.
Do not use that option against a live database. Missing collected static assets
produce existing test-environment warnings and do not qualify browser/UI behavior.
