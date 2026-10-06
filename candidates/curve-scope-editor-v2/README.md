# Scope editor v2: read-only successor qualification

Status: the manual-draft predecessor is integrated at Plane `7682c5a`, with its
feature disabled. This reader passed **23 real PostgreSQL/API tests** in a disposable proposed
application. Source promotion and its installed regression checks follow. Docker source access is resolved.

## Behavior and boundary

The [read service](overlay/scope_editor_read_v2.py) (fresh human authority,
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

The [HTTP view](overlay/scope_editor_read_views_v2.py) (session-only GET/HEAD)
returns a current Initiative ETag and `no-store`. Anonymous/token-only requests,
queries, unsupported methods and unavailable reads return the same fixed 404.
The endpoint never writes policy, audit, operation or domain records.

## Exact separate qualification

The [proposed proof](qualification/proposed-scope-successor.json) (closed read-only
successor) follows the immutable manual proof and adds only two runtime modules
plus the explicit URL replacement. Models, all 24 migration bytes, physical
catalog, writer inventory and excluded authorities remain unchanged.
The [reviewed manifest](qualification/reviewed-integration.json) (exact prospective
source bytes and pins) and [promotion patch](promotion.patch) (one import and one
route) define the complete delta. No observed deployment is used to fill a pin.

The [assembly helper](qualification/stage_application.py) (checked disposable
application) verifies predecessor/runtime/migration bytes, applies only the
reviewed delta, and uses the production qualification loader. It requires the
original read-only source bind to work. It never activates a host workspace or
changes Docker access settings.

The [contract snapshot](overlay/scope_editor_read_v2_candidate/manifest-v2.json)
(canonical metadata/read policy pins) is unchanged from Curve. The reader verifies
the manifest and each covered contract before returning data.

## Reproduction

From the Plane repository root:

```sh
.curve-local/unit-venv/bin/python -m unittest discover \
  -s candidates/curve-scope-editor-v2/tests -v
python3 candidates/curve-scope-editor-v2/qualification/run_isolated.py
```

The [host suite](tests/test_scope_editor.py) (31 unit/DRF tests with doubles) does
not qualify persistence. The [runtime suite](postgres_tests/test_scope_reader.py)
(real sessions, permissions, complete history, read-only behavior and row races)
uses the [isolated profile](../../deployments/curve-local-pilot/README.md)
(existing image and synthetic disposable PostgreSQL). Database phases run
sequentially. See [verification](VERIFICATION.md) (exact evidence and limits).

The reader grants no plan approval, task reservation, automatic execution or
completion credit. Mounting the UI, protected-definition preparation and manual
Gate 2 persistence remain separate work.
