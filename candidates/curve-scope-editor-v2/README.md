# Scope editor v2: read-only successor qualification

Status: one qualified reader moved into the restored Plane runtime with an
explicit default-off setting. The prospective checkpoint `90996fb` passed 23
PostgreSQL/API tests and 31 host tests. The combined installed-source suite passed **80 tests**. The **186-test historical
regression also passed** after this reader addition.

## Behavior and boundary

The [read service](../../apps/api/plane/curve/scope_editor_read_v2.py) (fresh human authority,
bounded complete lineage and final comparison) returns exactly eight metadata
fields. Intact absence differs from a saved empty selection. It checks every
revision's workspace/Product/Initiative identity, sequence, predecessor, saved
Initiative version, recording time and edition. Histories over 1,000 revisions
are rejected before broad integrity work. Native task bodies are never projected.

The separate default-off `CURVE_SCOPE_EDITOR_READ_V2_ENABLED` flag requires LOCAL,
workspace enablement, a configured installation, an active human with known
workspace role, a STANDALONE DRAFT Initiative, an active Product, and its current
creator or a workspace administrator. Native membership does not grant protected
source access. Current protected member reads and scope writes remain independent.

The [HTTP view](../../apps/api/plane/curve/scope_editor_read_views_v2.py) (session-only GET/HEAD)
returns a current Initiative ETag and `no-store`. Anonymous/token-only requests,
queries, unsupported methods and unavailable reads return the same fixed 404.
The endpoint never writes policy, audit, operation or domain records.

## Exact separate qualification

The [installed proof](../../apps/api/plane/curve/scope_editor_read_reconstruction_qualification_v2.json) (closed read-only
successor) follows the immutable manual proof and adds only two runtime modules
plus the explicit URL replacement. Models, all 24 migration bytes, physical
catalog, writer inventory and excluded authorities remain unchanged.
The [reviewed manifest](qualification/reviewed-integration.json) (historical prospective
source bytes and pins at `90996fb`) and [promotion patch](promotion.patch) (one import and one
route) define the complete delta. No observed deployment is used to fill a pin.

The historical `qualification/stage_application.py` (checked disposable
application), preserved at `90996fb`, verified predecessor/runtime/migration
bytes and the closed delta with the production loader. That assembly and the
candidate implementation have been removed after promotion. The shared test
runner now uses the one installed source through the original read-only bind.
No host workspace or provider has been activated.

The [contract snapshot](../../apps/api/plane/curve/scope_editor_read_v2_candidate/manifest-v2.json)
(canonical metadata/read policy pins) is unchanged from Curve. The reader verifies
the manifest and each covered contract before returning data.

## Reproduction

From the Plane repository root:

```sh
.curve-local/unit-venv/bin/python -m unittest discover \
  -s apps/api/plane/curve/tests/scope_editor_v2/host -v
python3 candidates/curve-scope-editor-v2/qualification/run_isolated.py
```

The [host suite](../../apps/api/plane/curve/tests/scope_editor_v2/host/test_scope_editor.py) (31 unit/DRF tests with doubles) does
not qualify persistence. The [runtime suite](../../apps/api/plane/curve/tests/scope_editor_v2/test_scope_reader.py)
(real sessions, permissions, complete history, read-only behavior and row races)
uses the [isolated profile](../../deployments/curve-local-pilot/README.md)
(existing image and synthetic disposable PostgreSQL). Database phases run
sequentially. See [verification](VERIFICATION.md) (exact evidence and limits).

The reader grants no plan approval, task reservation, automatic execution or
completion credit. Mounting the UI, protected-definition preparation and manual
Gate 2 persistence remain separate work.
