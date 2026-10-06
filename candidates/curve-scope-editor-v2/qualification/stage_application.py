"""Exercise a closed, reviewed read-only successor under disposable container /tmp."""

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
    spec = json.loads((root / "qualification/reviewed-integration.json").read_bytes())
    assert spec["status"] == "PROSPECTIVE_QUALIFICATION_ONLY"
    for name, expected in spec["source_files"].items():
        path = root / name
        assert path.is_relative_to(root) and not path.is_symlink() and digest(path.read_bytes()) == expected, name
    baseline = Path("/code/plane/curve")
    manual = (baseline / "manual_plan_draft_reconstruction_qualification_v2.json").read_bytes()
    assert digest(manual) == spec["manual_proof_digest"]
    previous = json.loads(manual)["qualification"]
    for name, expected in previous["runtime_sources"].items():
        assert digest((baseline / name).read_bytes()) == expected, name
    for name, expected in previous["migration_digests"].items():
        assert digest((baseline / "migrations" / name).read_bytes()) == expected, name
    loader = (baseline / "scope_reopening_qualification.py").read_bytes()
    assert digest(loader) == spec["baseline_loader_digest"]
    proposal = (root / "qualification/proposed-scope-successor.json").read_bytes()
    assert digest(proposal) == spec["proof_digest"]
    following = json.loads(proposal)["qualification"]
    assert all(previous[key] == following[key] for key in previous if key != "runtime_sources")
    assert set(following["runtime_sources"]) - set(previous["runtime_sources"]) == {
        "scope_editor_read_v2.py",
        "scope_editor_read_views_v2.py",
    }
    assert {
        key
        for key in previous["runtime_sources"]
        if previous["runtime_sources"][key] != following["runtime_sources"][key]
    } == {"urls.py"}
    # Original read-only mount works; this proposal assembly is not an access workaround.
    source = Path("/code")
    assert not any(path.is_symlink() for path in source.rglob("*"))
    stage = root / "application"
    app = stage / "apps/api"
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
    assert digest((target / "urls.py").read_bytes()) == spec["prospective_url_digest"]
    shutil.copytree(root / "overlay", target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    loader = loader.replace(
        b"SCOPE_EDITOR_SUCCESSOR_DIGEST = None",
        ("SCOPE_EDITOR_SUCCESSOR_DIGEST = " + repr(spec["proof_digest"])).encode(),
    )
    assert digest(loader) == spec["prospective_loader_digest"]
    (target / "scope_reopening_qualification.py").write_bytes(loader)
    (target / "scope_editor_read_reconstruction_qualification_v2.json").write_bytes(proposal)
    shutil.copytree(root / "postgres_tests", target / "tests/scope_editor_v2")
    for name, expected in following["runtime_sources"].items():
        assert digest((target / name).read_bytes()) == expected, name
    (app / "scope_qualification_settings.py").write_text(
        "from plane.settings.test import *\n"
        "DATABASES['default'].setdefault('TEST', {})['NAME'] = 'test_curve_scope_candidate'\n"
    )
    return app
