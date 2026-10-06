# Isolated local Curve test profile

Status: prepared; first database run blocked before application startup.

[Compose test profile](compose.test.yml) (disposable PostgreSQL/Valkey and the
existing local test image) has an internal Docker network, no published ports,
synthetic test credentials, read-only source mount and ephemeral database storage.
It uses its own Compose project; no existing installation or other project is
started, stopped or reconfigured.

The test image must already exist locally and include the recovered dependencies.
The verified local image has Python 3.12.5, Django 5.2.15, pytest 9.0.3,
psycopg 3.3.4, DRF 3.17.1, jsonschema 4.26.0 and referencing 0.37.0.
`pull_policy: never` prevents an accidental external image pull. A separately
verified compatible image may be selected with `CURVE_TEST_IMAGE`.

## Baseline command

Run from the Plane repository root:

```sh
docker compose -p curve-manual-pilot-20261006 \
  -f deployments/curve-local-pilot/compose.test.yml run --rm api-tests \
  pytest -q --tb=short -o 'addopts=--reuse-db --migrations' \
  -o cache_dir=/tmp/pytest-cache \
  plane/curve/tests/test_project_association_read_qualification.py \
  plane/curve/tests/test_scope_proposal_api.py \
  plane/curve/tests/test_scoped_prd_bridge.py \
  plane/curve/tests/test_scope_reopening_services.py \
  plane/curve/tests/test_scope_reopening_races.py
```

## Observed blocker and cleanup

On 2026-10-06, PostgreSQL and Valkey reached healthy state, but Docker Desktop
denied the bind mount of the restored API source under the operator's Documents
directory: `operation not permitted`. The application container did not start;
no migrations or database/API tests ran. This is an OS/filesharing access blocker,
not a test pass and not an automated approval-review rejection.

Required operator action: allow Docker Desktop to read the restored API directory
through the applicable macOS Files and Folders/Documents permission and Docker
Desktop file-sharing settings. Do not relocate the source or change permissions
automatically to bypass the denial. Retry this exact isolated baseline only after
that access is authorized.

Cleanup is scoped to this project:

```sh
docker compose -p curve-manual-pilot-20261006 \
  -f deployments/curve-local-pilot/compose.test.yml down --volumes
```

No production provider, private account, shared service, agent execution, model
call, publication, merge or deployment is authorized by this test profile.
