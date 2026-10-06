"""Assemble the explicitly reviewed prospective app only in container /tmp.

This does not approve a successor or alter the host checkout. Source hashes come
from the reviewed proposal, never from a live schema or arbitrary installed tree.
The same production qualification loader runs in the disposable application.
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def stage_application(root):
    root = Path(root).resolve()
    assert root.is_relative_to(Path("/tmp"))
    spec = json.loads((root / "qualification/reviewed-integration.json").read_text())
    assert spec["status"] == "PROSPECTIVE_QUALIFICATION_ONLY"
    for name, expected in spec["source_files"].items():
        path = root / name
        assert path.is_relative_to(root) and not path.is_symlink() and digest(path.read_bytes()) == expected, name
    baseline = Path("/code/plane/curve")
    for name, expected in (
        ("scope_reopening_qualification.json", spec["baseline_proof_digest"]),
        ("project_association_read_qualification.json", spec["read_successor_digest"]),
    ):
        assert digest((baseline / name).read_bytes()) == expected
    previous = json.loads((baseline / "project_association_read_qualification.json").read_bytes())["qualification"]
    for name, expected in previous["runtime_sources"].items():
        assert digest((baseline / name).read_bytes()) == expected, name
    for name, expected in previous["migration_digests"].items():
        assert digest((baseline / "migrations" / name).read_bytes()) == expected, name
    stage = root / "prospective-application"
    app = stage / "apps/api"
    source = Path("/code")
    # Original source access has already succeeded. This isolated test assembly
    # exercises proposed code; it is not an alternate source-mount access path.
    for path in source.rglob("*"):
        assert not path.is_symlink(), "Linked API sources are not accepted for this qualification"
    shutil.copytree(
        source,
        app,
        ignore=shutil.ignore_patterns(
            ".env",
            ".git",
            "__pycache__",
            ".pytest_cache",
            "*.log",
            "logs",
            "collected-static",
        ),
    )
    (app / "plane/logs").mkdir(exist_ok=True)
    (app / "plane/static-assets/collected-static").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "apply", "--check", str(root / "promotion.patch")], cwd=stage, check=True)
    subprocess.run(["git", "apply", str(root / "promotion.patch")], cwd=stage, check=True)
    target = app / "plane/curve"
    for name, expected in spec["replaced_sources"].items():
        assert digest((target / name).read_bytes()) == expected, name
    shutil.copytree(root / "overlay/manual_plan_v2", target / "manual_plan_v2")
    migration = (root / "overlay/migrations/0024_manual_draft_reconstruction.py").read_bytes()
    assert migration.count(b"CURRENT_CATALOG_DIGEST = None") == 1
    migration = migration.replace(
        b"CURRENT_CATALOG_DIGEST = None",
        ("CURRENT_CATALOG_DIGEST = " + repr(spec["reviewed_physical_catalog_digest"])).encode(),
    )
    assert digest(migration) == spec["prospective_migration_digest"]
    (target / "migrations/0024_manual_draft_reconstruction.py").write_bytes(migration)
    proof = (root / "qualification/proposed-manual-successor.json").read_bytes()
    assert digest(proof) == spec["proof_digest"]
    (target / "manual_plan_draft_reconstruction_qualification_v2.json").write_bytes(proof)
    loader = (root / "overlay/trusted_root/scope_reopening_qualification.py").read_bytes()
    assert loader.count(b"MANUAL_SUCCESSOR_DIGEST = None") == 1
    loader = loader.replace(
        b"MANUAL_SUCCESSOR_DIGEST = None", ("MANUAL_SUCCESSOR_DIGEST = " + repr(spec["proof_digest"])).encode()
    )
    assert digest(loader) == spec["prospective_loader_digest"]
    (target / "scope_reopening_qualification.py").write_bytes(loader)
    (app / "curve_manual_qualification_settings.py").write_text(
        "from plane.settings.test import *\n"
        "DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_curve_manual_candidate'\n"
    )
    return app
