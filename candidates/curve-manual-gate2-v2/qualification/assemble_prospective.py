"""Assemble reviewed prospective source for tests; this does not authorize promotion.

Run from repository root using a Python environment with Ruff.
The exact reviewed catalog and unchanged predecessor bytes are mandatory.
"""

from pathlib import Path
import json, hashlib, shutil, ast, re, sys, subprocess

root = Path("candidates/curve-manual-gate2-v2")
api = Path("apps/api/plane/curve")
stage = Path(".curve-local/gate2-api")
sha = lambda b: "sha256:" + hashlib.sha256(b).hexdigest()
pre = (api / "scope_editor_read_reconstruction_qualification_v2.json").read_bytes()
assert sha(pre) == "sha256:c2e37caa561e943bf4f2883c62d8ed889c74a55809fa1f5ffc93aed5d4ce093e"
base = json.loads(pre)["qualification"]
for name, value in base["runtime_sources"].items():
    assert sha((api / name).read_bytes()) == value, name
for name, value in base["migration_digests"].items():
    assert sha((api / "migrations" / name).read_bytes()) == value, name
shutil.copytree(
    Path("apps/api"),
    stage,
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("__pycache__", ".ruff_cache", ".pytest_cache", ".env"),
)
target = stage / "plane/curve"
shutil.copytree(
    root / "overlay/manual_gate2_v2",
    target / "manual_gate2_v2",
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns("__pycache__"),
)
models = (api / "models.py").read_text()
condition = """                    | models.Q(
                        policy_key="CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2",
                        policy_version=2,
                        policy_manifest_digest="POLICY_DIGEST_LITERAL",
                    )
""".replace("POLICY_DIGEST_LITERAL", sha((root / "overlay/manual_gate2_v2/contract_snapshot/policy.json").read_bytes()))
needle = '                ),\n                name="curve_policy_identity_ck",'
assert models.count(needle) == 1
models = (
    models.replace(needle, condition + needle)
    + "\nfrom .manual_gate2_v2.models import (ManualGate2ControlV2, ManualGate2RecordV2, ManualTaskClaimV2, ManualTaskClaimHistoryV2)  # noqa: F401,E402\n"
)
(target / "models.py").write_text(models)
urls = (
    (api / "urls.py")
    .read_text()
    .replace(
        "from django.urls import path\n",
        "from django.urls import path\nfrom plane.curve.manual_gate2_v2.views import Gate2CommandEndpoint, Gate2StatusEndpoint, Gate2MaterialEndpoint\n",
    )
    .replace(
        "urlpatterns = [\n",
        """urlpatterns = [
    path("workspaces/<str:slug>/curve/initiatives/<uuid:initiative_id>/manual-gate2/v2/materials/<uuid:object_id>/", Gate2MaterialEndpoint.as_view(), name="curve-manual-gate2-material-v2"),
    path("workspaces/<str:slug>/curve/initiatives/<uuid:initiative_id>/manual-gate2/v2/commands/", Gate2CommandEndpoint.as_view(), name="curve-manual-gate2-command-v2"),
    path("workspaces/<str:slug>/curve/initiatives/<uuid:initiative_id>/manual-gate2/v2/status/", Gate2StatusEndpoint.as_view(), name="curve-manual-gate2-status-v2"),
    path("workspaces/<str:slug>/curve/initiatives/<uuid:initiative_id>/manual-gate2/v2/preparation/", Gate2StatusEndpoint.as_view(preparation=True), name="curve-manual-plan-preparation-v2"),
""",
    )
)
(target / "urls.py").write_text(urls)
subprocess.run(
    [
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--line-length",
        "120",
        str(target / "models.py"),
        str(target / "urls.py"),
    ],
    check=True,
)
loader = (api / "scope_reopening_qualification.py").read_text()
added = sorted("manual_gate2_v2/" + p.name for p in (root / "overlay/manual_gate2_v2").glob("*.py"))
addedmodels = json.loads((root / "qualification/added-models.json").read_text())
loader = loader.replace(
    "_MANUAL_EDITION =",
    'GATE2_SUCCESSOR_DIGEST = None\nGATE2_SUCCESSOR_PATH = Path(__file__).parent / "manual_gate2_reconstruction_qualification_v2.json"\n_GATE2_ADDED_MODULES = frozenset('
    + repr(added)
    + ")\n_GATE2_ADDED_MODELS = "
    + repr(addedmodels)
    + "\n\n_MANUAL_EDITION =",
    1,
)
func = """def validate_gate2_successor(predecessor, successor):
    if (type(successor) is not dict or set(successor) != {"schema_version", "predecessor_digest", "writer_edition", "qualification"}
        or successor["schema_version"] != "curve.manual-gate2-reconstruction-qualification/v2-candidate"
        or successor["predecessor_digest"] != SCOPE_EDITOR_SUCCESSOR_DIGEST
        or successor["writer_edition"] != "MANUAL_GATE2_RECONSTRUCTION_V2"):
        raise ValueError("Wrong manual Gate 2 successor")
    q = successor["qualification"]
    if (type(q) is not dict or set(q) != set(predecessor)
        or q["schema_version"] != predecessor["schema_version"]
        or q["model_edition"] != "CURVE_MANUAL_GATE2_RECONSTRUCTION_V2"
        or q["runtime_writer_inventory"] != predecessor["runtime_writer_inventory"] + ["MANUAL_GATE2_RECONSTRUCTION_V2"]
        or predecessor["excluded_writers"] != ["PLAN_APPROVAL", "CONTROLLING_WORK_BINDING", "EXECUTION", "COMPLETION_CREDIT"]
        or q["excluded_writers"] != ["EXECUTION", "COMPLETION_CREDIT"]
        or q["models"] != sorted(predecessor["models"] + _GATE2_ADDED_MODELS, key=lambda row:row["model_name"])):
        raise ValueError("Wrong manual Gate 2 storage/writer delta")
    old, new = predecessor["migration_digests"], q["migration_digests"]
    if not _hashes(new) or set(new)-set(old) != {"0025_manual_gate2_reconstruction.py"} or any(new.get(k)!=v for k,v in old.items()):
        raise ValueError("Historical migration changed")
    _validate_source_delta(predecessor["runtime_sources"],q["runtime_sources"],_GATE2_ADDED_MODULES,frozenset({"models.py","urls.py"}))
    if type(q["physical_catalog_digest"]) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}",q["physical_catalog_digest"]) is None or q["physical_catalog_digest"] == predecessor["physical_catalog_digest"]:
        raise ValueError("Reviewed Gate 2 catalog required")
    return q


def require_manual_gate2_v2_qualification():
    require_scope_editor_read_v2_qualification()
    if not GATE2_SUCCESSOR_PATH.exists() or GATE2_SUCCESSOR_DIGEST is None:
        raise PrdCommandError("MANUAL_GATE2_EDITION_UNAVAILABLE",503)


"""
loader = loader.replace("def _read_pinned_successor(", func + "def _read_pinned_successor(", 1)
needle = "    return qualified\n\n\ndef require_manual_plan_v2_qualification()"
assert loader.count(needle) == 1
loader = loader.replace(
    needle,
    """    if GATE2_SUCCESSOR_PATH.exists():
        qualified = validate_gate2_successor(qualified, _read_pinned_successor(GATE2_SUCCESSOR_PATH, GATE2_SUCCESSOR_DIGEST))
        from .manual_gate2_v2.contracts import validate_manifest
        validate_manifest()
    return qualified


def require_manual_plan_v2_qualification()""",
)
migration = (root / "overlay/migrations/0025_manual_gate2_reconstruction.py").read_text()
pin = root / "qualification/reviewed-catalog.json"
if pin.exists():
    expected = json.loads(pin.read_text())
    assert expected["migration_unpinned_digest"] == sha(migration.encode()), (
        "SQL authoring changed; review catalog again"
    )
    migration = migration.replace(
        "CURRENT_CATALOG_DIGEST = None", "CURRENT_CATALOG_DIGEST = " + repr(expected["physical_catalog_digest"])
    )
    q = json.loads(json.dumps(base))
    q.update(
        model_edition="CURVE_MANUAL_GATE2_RECONSTRUCTION_V2",
        models=sorted(base["models"] + addedmodels, key=lambda r: r["model_name"]),
        excluded_writers=["EXECUTION", "COMPLETION_CREDIT"],
        runtime_writer_inventory=base["runtime_writer_inventory"] + ["MANUAL_GATE2_RECONSTRUCTION_V2"],
        physical_catalog_digest=expected["physical_catalog_digest"],
    )
    q["migration_digests"]["0025_manual_gate2_reconstruction.py"] = sha(migration.encode())
    q["runtime_sources"].update({name: sha((target / name).read_bytes()) for name in ["models.py", "urls.py", *added]})
    proof = dict(
        schema_version="curve.manual-gate2-reconstruction-qualification/v2-candidate",
        predecessor_digest=sha(pre),
        writer_edition="MANUAL_GATE2_RECONSTRUCTION_V2",
        qualification=q,
    )
    raw = (json.dumps(proof, sort_keys=True, indent=2) + "\n").encode()
    (target / "manual_gate2_reconstruction_qualification_v2.json").write_bytes(raw)
    loader = loader.replace("GATE2_SUCCESSOR_DIGEST = None", "GATE2_SUCCESSOR_DIGEST = " + repr(sha(raw)))
    (root / "qualification/proposed-successor.json").write_bytes(raw)
loader = loader.replace(
    'catalog_sql = import_module("plane.curve.migrations.0023_scope_reopening").CATALOG_SQL',
    'catalog_sql = import_module("plane.curve.migrations." + ("0025_manual_gate2_reconstruction" if GATE2_SUCCESSOR_PATH.exists() else "0023_scope_reopening")).CATALOG_SQL',
)
(root / "overlay/trusted_root").mkdir(exist_ok=True)
(root / "overlay/trusted_root/scope_reopening_qualification.py").write_text(loader)
(target / "scope_reopening_qualification.py").write_text(loader)
subprocess.run(
    [sys.executable, "-m", "ruff", "format", "--line-length", "120", str(target / "scope_reopening_qualification.py")],
    check=True,
)
(root / "overlay/trusted_root/scope_reopening_qualification.py").write_bytes(
    (target / "scope_reopening_qualification.py").read_bytes()
)
(target / "migrations/0025_manual_gate2_reconstruction.py").write_text(migration)
# Test teardown protection is only changed around Django's own TRUNCATE transaction.
f = target / "tests/conftest.py"
s = f.read_text()
s += """

@pytest.fixture(scope="session", autouse=True)
def manual_gate2_test_teardown(manual_draft_test_teardown):
    from django.db.backends.postgresql.operations import DatabaseOperations
    original = DatabaseOperations.sql_flush
    guards = [("curve_manual_gate2_control_v2","curve_mg2c_no_truncate"),("curve_manual_gate2_record_v2","curve_mg2r_no_truncate"),("curve_manual_task_claim_v2","curve_mtc2_no_truncate"),("curve_manual_task_claim_history_v2","curve_mtch2_no_truncate")]
    def sql_flush(operations, style, tables, *, reset_sequences=False, allow_cascade=False):
        statements=original(operations,style,tables,reset_sequences=reset_sequences,allow_cascade=allow_cascade)
        if "curve_manual_gate2_record_v2" not in tables: return statements
        assert "curve_manual_gate2_v2_coverage" not in tables
        result=[]
        for statement in statements:
            if statement.lstrip().upper().startswith("TRUNCATE "):
                for table,name in guards:
                    result.append(f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='{table}'::regclass AND tgname='{name}' AND tgenabled='O') THEN RAISE EXCEPTION 'Gate2 guard missing before fixture cleanup'; END IF; END $$;")
                    result.append(f"ALTER TABLE {table} DISABLE TRIGGER {name};")
                result.append(statement)
                for table,name in guards:
                    result.append(f"ALTER TABLE {table} ENABLE TRIGGER {name};")
                    result.append(f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='{table}'::regclass AND tgname='{name}' AND tgenabled='O') THEN RAISE EXCEPTION 'Gate2 guard missing after fixture cleanup'; END IF; END $$;")
            else: result.append(statement)
        return result
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseOperations,"sql_flush",sql_flush)
        yield
"""
f.write_text(s)
shutil.copytree(root / "tests", target / "tests/manual_gate2_v2", dirs_exist_ok=True)
(stage / "gate2_qualification").mkdir(exist_ok=True)
for f in (root / "qualification").glob("*.py"):
    shutil.copy2(f, stage / "gate2_qualification" / f.name)
print("prospective source prepared; installed source unchanged; pinned=", pin.exists())
