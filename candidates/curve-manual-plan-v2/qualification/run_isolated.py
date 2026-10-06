"""Deliver bounded candidate test material over stdin to the existing test image.

Requires the original read-only API bind to work. It neither changes that mount
nor copies the API tree, installs runtime code, fills proof pins or enables flags.
Only candidate files are extracted into a disposable container /tmp directory.
"""

import argparse
import base64
import io
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["sql", "worker", "ddl"])
    args = parser.parse_args()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(ROOT.rglob("*")):
            if (
                path.is_symlink()
                or not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix not in {".py", ".json"}
            ):
                continue
            archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    payload = buffer.getvalue()
    assert len(payload) < 4 * 1024 * 1024
    target = {
        "sql": "postgres_tests/test_shape_sql.py",
        "worker": "qualification/test_linux_worker.py",
        "ddl": "postgres_tests/test_ddl_experiment.py",
    }[args.phase]
    program = f"""
import base64,io,os,pathlib,sys,tarfile,tempfile
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
    code=pytest.main(["-c","/code/pytest.ini","-q","-s","--tb=short",
        "-o","addopts=--reuse-db --migrations","-o","cache_dir=/tmp/pytest-cache",str(root/{target!r})])
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
