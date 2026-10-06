# Scope editor v2 implementation candidate

Status: source and host unit/HTTP preparation, 2026-10-06. Not installed, routed,
database-qualified or available to users. This checkpoint advances the minimal
read service while PostgreSQL testing is blocked by Docker's source-mount denial.

## Implemented behavior

[Read service](overlay/scope_editor_read_v2.py) (current human authority, bounded
history, current-member metadata integrity and final comparison) provides the
eight-field discovery contract. It distinguishes intact absence from a saved
empty selection. Every revision participates in lineage verification, including
workspace/Product/Initiative identity, sequence, predecessor, saved Initiative
version, time and edition. Valid version gaps and equal recording times remain
accepted. The first query reads at most 1,001 revisions; histories over 1,000 are
denied before broad integrity work.

The separate default-off `CURVE_SCOPE_EDITOR_READ_V2_ENABLED` flag requires LOCAL,
workspace enablement, a configured local installation, fresh active human
membership with a known role, STANDALONE DRAFT Initiative, active Product, and the
current creator or workspace administrator. Native task visibility is not a grant
and is not needed to discover replacement metadata. Existing protected member
reads and save authorization remain independent.

[HTTP view](overlay/scope_editor_read_views_v2.py) (session authentication and fixed
denial) serves GET/HEAD with a typed current Initiative ETag and `no-store`.
Queries, anonymous requests, token-only requests and unsupported operations have
the same fixed 404 payload. Error details are not serialized. Successful discovery
does not write a policy decision, audit, operation or any domain row.

## Integration boundary

The recovered runtime recursively pins all Curve Python source. Adding these
files directly to the installed app would invalidate its historical qualification.
They therefore remain in this reviewable candidate directory. No route, model,
migration, historical proof or existing runtime module was changed.

The implementation deliberately calls the not-yet-existing trusted
`require_scope_editor_read_v2_qualification` entry point. It has no fallback to
the old proof, permissive flag or injected callback. Installing these files alone
cannot activate the endpoint. The following work remains mandatory:

1. Complete and qualify the persistent manual-draft v2 predecessor on disposable
   PostgreSQL, including its SQL guards, physical catalog and immutable seals.
2. Review this read-only successor, register these two modules and its explicit
   route, and freeze the exact reviewed source delta. Models, migrations, catalog,
   writer inventory and exclusions must remain those of the draft predecessor.
3. Run real database/API permission, complete-lineage, zero-write, corruption,
   concurrent-update and source-closure tests before enabling any workspace.

Intended route after qualification:

```python
path(
    "workspaces/<str:slug>/curve/initiatives/<uuid:initiative_id>/scope-editor/v2/preconditions/",
    CurveScopeEditorPreconditionsV2Endpoint.as_view(),
    name="curve-scope-editor-preconditions-v2",
)
```

[Contract snapshot](overlay/scope_editor_read_v2_candidate/manifest-v2.json)
(exact recovered candidate byte pins) and all four covered files were copied
unchanged from the Curve contract. The reader pins the manifest digest itself.
No runtime qualification digest is generated here.

## Executed checks and limitations

[Unit tests](tests/test_scope_editor.py) (metadata adversaries, authorization query
spies, simulated authority changes and actual DRF dispatch) run without a database:

```sh
.curve-local/unit-venv/bin/python -m unittest discover \
  -s candidates/curve-scope-editor-v2/tests -v
.curve-local/unit-venv/bin/ruff check --config apps/api/pyproject.toml \
  candidates/curve-scope-editor-v2
.curve-local/unit-venv/bin/ruff format --check --config apps/api/pyproject.toml \
  candidates/curve-scope-editor-v2
```

[Unit dependencies](requirements-unit.txt) (pinned Django/DRF/schema/lint versions)
can be installed into a repository-local virtual environment. These host checks
do not establish PostgreSQL locking, SQL integrity, authenticated browser flows
or the full application's runtime behavior. The application test container has
not started; no new database migration or integration test has passed.

See [verification record](VERIFICATION.md) (actual results and remaining gates)
and [isolated test profile](../../deployments/curve-local-pilot/README.md)
(Docker access blocker and approved test boundary).
