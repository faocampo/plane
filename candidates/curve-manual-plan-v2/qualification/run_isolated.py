"""Deliver bounded candidate test material over stdin to the existing test image.

Requires the original read-only API bind to work and never changes the host tree.
Ordinary phases use that baseline directly. Prospective phases assemble an exact,
reviewed application under container /tmp, enforcing its real qualification pins.
Both use disposable databases and leave the host runtime inactive.
"""

import argparse
import base64
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase", choices=["sql", "worker", "ddl", "authority", "installed", "persistence", "migration", "regression"]
    )
    parser.add_argument("--fresh-db", action="store_true", help="Recreate only this phase's disposable test database")
    args = parser.parse_args()
    proposal = json.loads((ROOT / "qualification/reviewed-integration.json").read_bytes())
    print(
        json.dumps(
            {
                "phase": args.phase,
                "reviewed_proposal_digest": proposal["proof_digest"],
                "prospective_application": args.phase in {"installed", "persistence", "migration", "regression"},
                "fresh_test_database": args.fresh_db,
            }
        ),
        flush=True,
    )
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(ROOT.rglob("*")):
            if (
                path.is_symlink()
                or not path.is_file()
                or "__pycache__" in path.parts
                or (path.suffix not in {".py", ".json"} and path.name != "promotion.patch")
            ):
                continue
            archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    payload = buffer.getvalue()
    assert len(payload) < 4 * 1024 * 1024
    target = {
        "sql": "postgres_tests/test_shape_sql.py",
        "worker": "qualification/test_linux_worker.py",
        "ddl": "postgres_tests/test_ddl_experiment.py",
        "authority": "postgres_tests/test_native_authority.py",
        "installed": "postgres_tests/test_installed_guards.py",
        "persistence": "postgres_tests/test_manual_persistence.py",
        "migration": "postgres_tests/test_complete_migration.py",
        "regression": "",
    }[args.phase]
    extra = ["-p", "plane.curve.tests.conftest"]
    if args.fresh_db:
        extra.append("--create-db")
    program = f"""
import base64,io,os,pathlib,shutil,subprocess,sys,tarfile,tempfile
import pytest
with tempfile.TemporaryDirectory(prefix="curve-candidate-tests-") as temporary:
    root=pathlib.Path(temporary)
    payload=base64.b64decode({base64.b64encode(payload).decode()!r})
    with tarfile.open(fileobj=io.BytesIO(payload),mode="r:gz") as archive:
        for member in archive.getmembers():
            path=pathlib.PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
        archive.extractall(root,filter="data")
    sys.path.insert(0,str(root/"overlay"))
    sys.path.insert(0,str(root/"tests"))
    sys.path.insert(0,str(root/"postgres_tests"))
    if {args.phase in {"installed", "persistence", "migration", "regression"}!r}:
        sys.path.insert(0,str(root/"qualification"))
        from stage_application import stage_application
        app=stage_application(root)
        extra={extra!r}
        targets=[str(root/{target!r})]
        if {args.phase == "regression"!r}:
            shutil.copy2(root/"postgres_tests/conftest.py",root/"qualification/manual_test_cleanup.py")
            extra=["-p","manual_test_cleanup"]+(["--create-db"] if {args.fresh_db!r} else [])
            targets=[str(app/"plane/curve/tests"/name) for name in [
                "test_project_association_read_qualification.py","test_scope_proposal_api.py",
                "test_scoped_prd_bridge.py","test_scope_reopening_services.py","test_scope_reopening_races.py"]]
        env=dict(os.environ, DJANGO_SETTINGS_MODULE="curve_manual_qualification_settings",
            PYTHONPATH=os.pathsep.join(map(str,[app,root/"qualification",root/"postgres_tests",root/"tests",root/"overlay"])))
        entry="import plane,pytest,sys; raise SystemExit(pytest.main(sys.argv[1:]))"
        raise SystemExit(subprocess.run([sys.executable,"-c",entry,"-c",str(app/"pytest.ini"),
            "-q","--tb=short","-o","addopts=--reuse-db --migrations","-o","cache_dir=/tmp/pytest-cache",
            *extra,*targets],cwd=app,env=env,stdin=subprocess.DEVNULL).returncode)
    paths=["/code",root/"postgres_tests",root/"tests",root/"overlay"]
    env=dict(os.environ, PYTHONPATH=os.pathsep.join(map(str,paths)))
    code=subprocess.run([sys.executable,"-m","pytest","-c","/code/pytest.ini","-q","--tb=short",
        "-o","addopts=--reuse-db --migrations","-o","cache_dir=/tmp/pytest-cache",
        *{extra!r},str(root/{target!r})],cwd="/code",env=env,stdin=subprocess.DEVNULL).returncode
    raise SystemExit(code)
"""
    command = [
        "docker",
        "compose",
        "-p",
        "curve-manual-pilot-20261006",
        "-f",
        "deployments/curve-local-pilot/compose.test.yml",
        "run",
        "--rm",
        "-T",
        "api-tests",
        "python",
        "-",
    ]
    raise SystemExit(subprocess.run(command, input=program.encode(), cwd=REPOSITORY).returncode)


if __name__ == "__main__":
    main()
