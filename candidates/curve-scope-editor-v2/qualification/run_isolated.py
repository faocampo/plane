"""Bounded prospective scope-reader tests; original source bind, synthetic DB only."""

import base64
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]


def main():
    spec = json.loads((ROOT / "qualification/reviewed-integration.json").read_bytes())
    print(json.dumps({"scope_proof": spec["proof_digest"], "application": "PROSPECTIVE_READ_SUCCESSOR"}), flush=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(ROOT.rglob("*")):
            if (
                path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and (path.suffix in {".py", ".json"} or path.name == "promotion.patch")
            ):
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    payload = buffer.getvalue()
    assert len(payload) < 4 * 1024 * 1024
    program = f"""
import base64,io,os,pathlib,subprocess,sys,tarfile,tempfile
with tempfile.TemporaryDirectory(prefix="curve-scope-qualification-") as temporary:
    root=pathlib.Path(temporary)
    payload=base64.b64decode({base64.b64encode(payload).decode()!r})
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            name=pathlib.PurePosixPath(member.name)
            assert member.isfile() and not name.is_absolute() and ".." not in name.parts
        archive.extractall(root,filter="data")
    sys.path.insert(0,str(root/"qualification"))
    from stage_application import stage_application
    app=stage_application(root)
    env=dict(os.environ, DJANGO_SETTINGS_MODULE="scope_qualification_settings",PYTHONPATH=str(app))
    entry="import plane,pytest,sys; raise SystemExit(pytest.main(sys.argv[1:]))"
    raise SystemExit(subprocess.run([sys.executable,"-c",entry,"-c",str(app/"pytest.ini"),
        "-q","--tb=short","--maxfail=1","-o","addopts=--reuse-db --migrations","-o","cache_dir=/tmp/pytest-cache",
        str(app/"plane/curve/tests/scope_editor_v2")],cwd=app,env=env,stdin=subprocess.DEVNULL).returncode)
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
