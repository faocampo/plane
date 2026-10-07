#!/usr/bin/env python3
"""Bounded synthetic pilot backup and an isolated PostgreSQL restore exercise.

No production restore, existing-target overwrite, provider access or image pull.
Artifacts contain database data and must stay in the operator's private storage.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid

FORMAT = "curve.synthetic-pilot-backup/v1"
LIMIT = 128 * 1024 * 1024
UUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}")


class RecoveryError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RecoveryError(message)


def run(argv, *, data=None, output=None, timeout=45):
    result = subprocess.run(
        argv,
        input=data,
        stdout=output or subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    require(
        result.returncode == 0,
        f"{argv[0]} operation failed (exit {result.returncode}); no success recorded",
    )
    return result.stdout


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def private_file(path, data):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def inspect_container(name, project, service):
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", name),
        "Invalid container name",
    )
    info = json.loads(run(["docker", "inspect", name]))[0]
    labels = info["Config"].get("Labels") or {}
    require(info["State"]["Running"], "Source container is not running")
    require(
        labels.get("com.docker.compose.project") == project
        and labels.get("com.docker.compose.service") == service,
        "Source Compose identity mismatch",
    )
    return info


@contextmanager
def held(argv, script=None, expected=None):
    """Hold a bounded lock process; release it even if capture fails."""
    process = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        if script:
            process.stdin.write(script.encode())
            process.stdin.flush()
        require(
            select.select([process.stdout], [], [], 12)[0], "Lock acquisition timed out"
        )
        token = process.stdout.readline().decode().strip()
        require(
            token and (expected is None or token == expected), "Lock was not acquired"
        )
        yield process, token
        require(process.poll() is None, "Lock expired; discard this capture")
    finally:
        if process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        process.stdout.close()


CATALOG_LOCK = r"""
import fcntl, os, signal, sys
from plane.curve.manual_plan_v2.synthetic import SyntheticManualPlanResolverV2
signal.alarm(60)
with SyntheticManualPlanResolverV2(sys.argv[1]) as resolver:
 fd=os.open('catalog.lock', os.O_RDONLY|os.O_NOFOLLOW, dir_fd=resolver.root_fd)
 try:
  fcntl.flock(fd, fcntl.LOCK_SH|fcntl.LOCK_NB)
  print('LOCKED', flush=True)
  sys.stdin.readline()
 finally:
  os.close(fd)
"""

CATALOG_EXPORT = r"""
import hashlib, io, json, sys, tarfile
from plane.curve.manual_plan_v2.synthetic import SyntheticManualPlanResolverV2
with SyntheticManualPlanResolverV2(sys.argv[1]) as resolver:
 raw,_=resolver._read('catalog.json',1048576)
 catalog=resolver._decode_catalog(raw)
 files={'catalog.json':raw}
 total=len(raw)
 for name,entry in catalog['objects'].items():
  ref=entry['object_ref']
  body,_=resolver._read(name,33554432)
  assert ref['object_id']==name and ref['size_bytes']==len(body)
  assert ref['digest']=='sha256:'+hashlib.sha256(body).hexdigest()
  total+=len(body)
  assert total<=128*1024*1024
  files[name]=body
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
  for name,body in sorted(files.items()):
   info=tarfile.TarInfo(name);info.size=len(body);info.mode=0o600
   archive.addfile(info,io.BytesIO(body))
"""

LOCK_SQL = r"""BEGIN;
SET LOCAL lock_timeout = '4s';
SET LOCAL idle_in_transaction_session_timeout = '60s';
SELECT format('LOCK TABLE %I.%I IN SHARE MODE;', schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SELECT pg_export_snapshot();
"""

FINGERPRINT_SQL = r"""
SET timezone = 'UTC';
SELECT format('SELECT %L; SELECT row_to_json(t)::text FROM %I.%I t ORDER BY row_to_json(t)::text COLLATE "C";',
 '@TABLE:'||tablename,schemaname,tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
"""


def psql(container, user, database):
    return [
        "docker",
        "exec",
        "-i",
        container,
        "psql",
        "-X",
        "-qAt",
        "--set",
        "ON_ERROR_STOP=1",
        "-U",
        user,
        "-d",
        database,
    ]


def fingerprints(container, user, database, snapshot=None):
    prefix = ""
    if snapshot:
        require(
            re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+", snapshot),
            "Invalid exported snapshot",
        )
        prefix = f"BEGIN ISOLATION LEVEL REPEATABLE READ; SET TRANSACTION SNAPSHOT '{snapshot}';\n"
    raw = run(psql(container, user, database), data=(prefix + FINGERPRINT_SQL).encode())
    result, current, digest, count = {}, None, None, 0
    for line in raw.splitlines(keepends=True):
        if line.startswith(b"@TABLE:"):
            if current is not None:
                result[current] = {
                    "rows": count,
                    "sha256": "sha256:" + digest.hexdigest(),
                }
            current, digest, count = line.decode().strip()[7:], hashlib.sha256(), 0
        else:
            require(
                current is not None and line.startswith(b"{"),
                "Unexpected database fingerprint output",
            )
            digest.update(line)
            count += 1
    if current is not None:
        result[current] = {"rows": count, "sha256": "sha256:" + digest.hexdigest()}
    require(result, "Empty database inventory")
    return result


def schema_fingerprint(container, user, database):
    raw = run(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            user,
            "-d",
            database,
            "--schema-only",
            "--no-owner",
            "--no-privileges",
        ]
    )
    # Newer pg_dump clients add a random psql restrict token. It is not DDL.
    lines = [
        line
        for line in raw.splitlines(keepends=True)
        if not line.startswith((b"\\restrict ", b"\\unrestrict "))
    ]
    return sha(b"".join(lines))


def verify_source(path, expected):
    source = Path(path).resolve()
    head = run(["git", "-C", str(source), "rev-parse", "HEAD"]).decode().strip()
    require(head == expected, "Source commit mismatch")
    require(
        not run(
            ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"]
        ),
        "Source has tracked modifications",
    )
    return source


def catalog_members(path):
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size <= LIMIT + 1048576,
        "Invalid protected archive",
    )
    members, total = {}, 0
    with tarfile.open(path, "r:") as archive:
        for item in archive:
            require(
                item.isfile()
                and (item.name == "catalog.json" or UUID.fullmatch(item.name)),
                "Protected archive contains an unsafe member",
            )
            require(
                item.name not in members and len(members) <= 512,
                "Duplicate or excessive archive entries",
            )
            total += item.size
            require(
                0 <= item.size <= 33554432 and total <= LIMIT,
                "Protected archive exceeds bound",
            )
            members[item.name] = archive.extractfile(item).read()
    require("catalog.json" in members, "Protected catalog is missing")
    catalog = json.loads(members["catalog.json"])
    require(
        catalog.get("schema_version")
        == "curve.synthetic-manual-plan-catalog/v2-candidate",
        "Unsupported catalog edition",
    )
    require(
        set(members) == {"catalog.json", *catalog["objects"]},
        "Catalog inventory mismatch",
    )
    for name, item in catalog["objects"].items():
        ref, body = item["object_ref"], members[name]
        require(
            ref["object_id"] == name
            and ref["size_bytes"] == len(body)
            and ref["digest"] == sha(body),
            "Protected object integrity failed",
        )
    return members


def verify(backup):
    backup = Path(backup)
    manifest_path = backup / "manifest.json"
    require(
        manifest_path.is_file()
        and not manifest_path.is_symlink()
        and manifest_path.stat().st_size <= 1048576,
        "Invalid backup manifest",
    )
    manifest = json.loads(manifest_path.read_text())
    require(
        manifest.get("format") == FORMAT and manifest.get("synthetic_only") is True,
        "Unsupported backup profile",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")),
        "Missing source identity",
    )
    require(
        re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.get("schema_sha256", "")),
        "Missing schema identity",
    )
    require(
        isinstance(manifest.get("tables"), dict) and manifest["tables"],
        "Missing table inventory",
    )
    require(
        all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.get(key, ""))
            for key in ("api_image_id", "postgres_image_id")
        ),
        "Missing immutable image identity",
    )
    require(
        set(manifest["files"]) == {"database.dump", "protected.tar"},
        "Unexpected backup inventory",
    )
    for name, expected in manifest["files"].items():
        path = backup / name
        require(
            path.is_file() and not path.is_symlink(), "Missing or unsafe backup file"
        )
        require(
            path.stat().st_size == expected["bytes"]
            and file_sha(path) == expected["sha256"],
            "Backup checksum mismatch",
        )
    members = catalog_members(backup / "protected.tar")
    require(
        sha(members["catalog.json"]) == manifest["catalog_sha256"],
        "Catalog identity mismatch",
    )
    return manifest, members


def capture(args):
    require(args.synthetic_local, "Only explicit synthetic local capture is supported")
    source = verify_source(args.source, args.source_commit)
    head = args.source_commit
    for value in (args.user, args.database):
        require(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value),
            "Invalid database identity",
        )
    require(
        args.root.startswith("/") and ".." not in Path(args.root).parts,
        "Invalid protected root",
    )
    db_info = inspect_container(args.db_container, args.project, "db")
    api_info = inspect_container(args.api_container, args.project, "api")
    require(
        any(
            m.get("Destination") == "/code"
            and m.get("Type") == "bind"
            and Path(m["Source"]).resolve() == source / "apps/api"
            and not m.get("RW")
            for m in api_info.get("Mounts", [])
        ),
        "API does not mount the declared source read-only",
    )
    db, api = db_info["Id"], api_info["Id"]
    destination = Path(args.output).absolute()
    require(not destination.exists(), "Backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".capture-", dir=destination.parent))
    started = time.monotonic()
    try:
        with held(
            [
                "docker",
                "exec",
                "-i",
                api,
                "python",
                "-u",
                "-c",
                CATALOG_LOCK,
                args.root,
            ],
            expected="LOCKED",
        ) as (catalog_lock, _):
            with held(psql(db, args.user, args.database), LOCK_SQL) as (
                db_lock,
                snapshot,
            ):
                require(
                    re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+", snapshot),
                    "Invalid snapshot",
                )
                for name, argv in (
                    (
                        "database.dump",
                        [
                            "docker",
                            "exec",
                            db,
                            "pg_dump",
                            "-U",
                            args.user,
                            "-d",
                            args.database,
                            "--format=custom",
                            "--no-owner",
                            "--no-privileges",
                            f"--snapshot={snapshot}",
                        ],
                    ),
                    (
                        "protected.tar",
                        [
                            "docker",
                            "exec",
                            api,
                            "python",
                            "-c",
                            CATALOG_EXPORT,
                            args.root,
                        ],
                    ),
                ):
                    with (temp / name).open("xb") as stream:
                        os.chmod(temp / name, 0o600)
                        run(argv, output=stream)
                inventory = fingerprints(db, args.user, args.database, snapshot)
                schema = schema_fingerprint(db, args.user, args.database)
                version = (
                    run(
                        psql(db, args.user, args.database)
                        + ["-c", "SHOW server_version_num;"]
                    )
                    .decode()
                    .strip()
                )
                require(
                    db_lock.poll() is None and catalog_lock.poll() is None,
                    "Capture lock expired",
                )
        members = catalog_members(temp / "protected.tar")
        manifest = {
            "format": FORMAT,
            "synthetic_only": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_commit": head,
            "postgres_version_num": version,
            "tables": inventory,
            "schema_sha256": schema,
            "api_image_id": api_info["Image"],
            "postgres_image_id": db_info["Image"],
            "catalog_sha256": sha(members["catalog.json"]),
            "protected_object_count": len(members) - 1,
            "capture_seconds": round(time.monotonic() - started, 3),
            "files": {
                name: {
                    "bytes": (temp / name).stat().st_size,
                    "sha256": file_sha(temp / name),
                }
                for name in ("database.dump", "protected.tar")
            },
        }
        private_file(
            temp / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode()
        )
        verify(temp)
        require(not destination.exists(), "Destination appeared during capture")
        temp.rename(destination)
        return {
            "result": "CAPTURE_VERIFIED",
            "backup": str(destination),
            "source_commit": head,
            "tables": len(inventory),
            "objects": len(members) - 1,
            "capture_seconds": manifest["capture_seconds"],
        }
    finally:
        if temp.exists():
            shutil.rmtree(temp)


MIGRATE = r"""
from pathlib import Path
Path('/tmp/recovery_settings.py').write_text("from plane.settings.common import *\nCACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}}\nCELERY_BROKER_URL='memory://'\nCELERY_RESULT_BACKEND='cache+memory://'\n")
import plane
import django
django.setup()
from django.core.management import call_command
call_command('migrate',interactive=False,verbosity=0)
"""


def cleanup_owned(name, token):
    found = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "io.curve.synthetic-recovery"}}',
            name,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if found.returncode == 0 and found.stdout.decode().strip() == token:
        run(["docker", "rm", "-f", name])


def read_profile(args):
    values = [
        getattr(args, key, None)
        for key in ("operator_settings", "access_file", "target_file")
    ]
    require(
        not any(values) or all(values),
        "Restored API verification requires all three private profile inputs",
    )
    if not all(values):
        return None
    result = []
    for value in values:
        path = Path(value).absolute()
        require(
            path.is_file() and not path.is_symlink(), "Invalid private profile input"
        )
        result.append(path)
    require(result[1].stat().st_mode & 0o077 == 0, "Credential file must be owner-only")
    return result


def check_restored_api(args, source, manifest, name, profile):
    api_name = name + "-api-read"
    argv = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--pull=never",
        "--name",
        api_name,
        "--label",
        f"io.curve.synthetic-recovery={name}",
        "--network",
        f"container:{name}",
        "--read-only",
        "--memory",
        "1g",
        "--cpus",
        "1",
        "--workdir",
        "/code",
        "--mount",
        f"type=bind,src={source / 'apps/api'},dst=/code,readonly",
        "--mount",
        f"type=bind,src={Path(__file__).with_name('http_probe.py').resolve()},dst=/probe.py,readonly",
        "--tmpfs",
        "/tmp:rw",
        "--tmpfs",
        "/demo-data:rw",
        "--tmpfs",
        "/code/plane/logs:rw",
        "--tmpfs",
        "/code/plane/static-assets/collected-static:rw",
        "-e",
        "DATABASE_URL=postgresql://curve_recovery@127.0.0.1:5432/curve_recovery",
        "-e",
        "REDIS_URL=redis://127.0.0.1:1/0",
        "-e",
        "DJANGO_SETTINGS_MODULE=recovery_probe_settings",
        "-e",
        "PYTHONPATH=/inputs:/tmp:/code",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "SECRET_KEY=synthetic-local-recovery-only",
    ]
    for path, filename in zip(
        profile, ("recovery_operator_settings.py", "access.json", "target.json")
    ):
        argv.extend(
            ["--mount", f"type=bind,src={path},dst=/inputs/{filename},readonly"]
        )
    argv.extend(
        [
            "--entrypoint",
            "python",
            manifest["api_image_id"],
            "/probe.py",
            manifest["catalog_sha256"],
        ]
    )
    if getattr(args, "pilot_controls", False):
        argv.append("--pilot-controls")
    try:
        with (Path(args.backup) / "protected.tar").open("rb") as stream:
            process = subprocess.run(
                argv,
                stdin=stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        require(
            process.returncode == 0,
            "Restored API read failed; no runtime acceptance recorded",
        )
        result = json.loads(process.stdout)
        require(
            result.get("result") == "RESTORED_HTTP_READ_PASSED",
            "Restored API result missing",
        )
        return result
    finally:
        cleanup_owned(api_name, name)


def exercise(args):
    manifest, members = verify(args.backup)
    profile = read_profile(args)
    require(
        not getattr(args, "pilot_controls", False) or profile is not None,
        "Pilot controls require the complete private HTTP profile",
    )
    source = verify_source(args.source, manifest["source_commit"])
    require(
        manifest["postgres_version_num"] == "150007",
        "Exercise supports the verified PostgreSQL 15.7 image only",
    )
    name = "curve-recovery-check-" + uuid.uuid4().hex[:12]
    started = time.monotonic()
    migration_name = name + "-migrate"
    with tempfile.TemporaryDirectory(prefix="curve-recovery-objects-") as extracted:
        try:
            run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--pull=never",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--read-only",
                    "--label",
                    f"io.curve.synthetic-recovery={name}",
                    "--memory",
                    "512m",
                    "--cpus",
                    "1",
                    "--tmpfs",
                    "/var/lib/postgresql/data:rw",
                    "--tmpfs",
                    "/var/run/postgresql:rw",
                    "--tmpfs",
                    "/tmp:rw",
                    "-e",
                    "POSTGRES_USER=curve_recovery",
                    "-e",
                    "POSTGRES_DB=curve_recovery",
                    "-e",
                    "POSTGRES_HOST_AUTH_METHOD=trust",
                    manifest["postgres_image_id"],
                ]
            )
            for _ in range(30):
                ready = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "sh",
                        "-c",
                        'test "$(cat /proc/1/comm)" = postgres && pg_isready -U curve_recovery -d curve_recovery',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if ready.returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise RecoveryError("Isolated PostgreSQL did not become ready")
            # Native migration DDL preserves the qualified catalog expression form.
            # Replaying deparsed pg_dump DDL can rewrite array casts in constraints.
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--name",
                    migration_name,
                    "--label",
                    f"io.curve.synthetic-recovery={name}",
                    "--network",
                    f"container:{name}",
                    "--read-only",
                    "--memory",
                    "1g",
                    "--cpus",
                    "1",
                    "--workdir",
                    "/code",
                    "--mount",
                    f"type=bind,src={source / 'apps/api'},dst=/code,readonly",
                    "--tmpfs",
                    "/tmp:rw",
                    "--tmpfs",
                    "/code/plane/logs:rw",
                    "--tmpfs",
                    "/code/plane/static-assets/collected-static:rw",
                    "-e",
                    "DATABASE_URL=postgresql://curve_recovery@127.0.0.1:5432/curve_recovery",
                    "-e",
                    "REDIS_URL=redis://127.0.0.1:1/0",
                    "-e",
                    "DJANGO_SETTINGS_MODULE=recovery_settings",
                    "-e",
                    "PYTHONPATH=/tmp:/code",
                    "-e",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "-e",
                    "SECRET_KEY=synthetic-local-recovery-only",
                    "--entrypoint",
                    "python",
                    manifest["api_image_id"],
                    "-c",
                    MIGRATE,
                ],
                timeout=180,
            )
            require(
                schema_fingerprint(name, "curve_recovery", "curve_recovery")
                == manifest["schema_sha256"],
                "Migration-built schema does not match the captured schema",
            )
            # Offline restoration in this newly created target only. Session-local
            # replication mode permits replacing bootstrap rows protected by the
            # native immutable triggers; it never changes source or trigger DDL.
            truncate = "SET session_replication_role=replica;\nSELECT 'TRUNCATE TABLE ' || string_agg(format('%I.%I',schemaname,tablename), ', ' ORDER BY tablename) || ' CASCADE;' FROM pg_tables WHERE schemaname='public'\n\\gexec\nSET session_replication_role=origin;\n"
            run(psql(name, "curve_recovery", "curve_recovery"), data=truncate.encode())
            with (Path(args.backup) / "database.dump").open("rb") as stream:
                restored = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        name,
                        "pg_restore",
                        "--exit-on-error",
                        "--no-owner",
                        "--no-privileges",
                        "--data-only",
                        "--disable-triggers",
                        "-U",
                        "curve_recovery",
                        "-d",
                        "curve_recovery",
                    ],
                    stdin=stream,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
                require(restored.returncode == 0, "Isolated database restore failed")
            require(
                fingerprints(name, "curve_recovery", "curve_recovery")
                == manifest["tables"],
                "Restored database does not match the captured snapshot",
            )
            require(
                schema_fingerprint(name, "curve_recovery", "curve_recovery")
                == manifest["schema_sha256"],
                "Restored schema does not match the captured schema",
            )
            run(
                psql(name, "curve_recovery", "curve_recovery")
                + ["-c", "SELECT curve_scope_reopening_verify_coverage();"]
            )
            for filename, raw in members.items():
                private_file(Path(extracted) / filename, raw)
            require(
                all(
                    (Path(extracted) / key).read_bytes() == value
                    for key, value in members.items()
                ),
                "Protected restore did not preserve bytes",
            )
            result = {
                "result": "RESTORE_EXERCISE_PASSED",
                "source_commit": manifest["source_commit"],
                "tables_verified": len(manifest["tables"]),
                "objects_verified": len(members) - 1,
                "schema_verified": True,
                "native_catalog_seal_verified": True,
                "restore_seconds": round(time.monotonic() - started, 3),
                "scope": "Schema DDL, full public-schema row fingerprints and protected bytes; no production activation or RPO/RTO certification",
            }
            if profile:
                result["restored_api"] = check_restored_api(
                    args, source, manifest, name, profile
                )
                result["exercise_seconds"] = round(time.monotonic() - started, 3)
            return result
        finally:
            # Labels bind cleanup to this run, including a failed container start.
            cleanup_owned(migration_name, name)
            cleanup_owned(name, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    for flag in (
        "source",
        "source-commit",
        "project",
        "db-container",
        "api-container",
        "user",
        "database",
        "root",
        "output",
    ):
        capture_parser.add_argument("--" + flag, required=True)
    capture_parser.add_argument("--synthetic-local", action="store_true")
    commands.add_parser("verify").add_argument("backup")
    restore_parser = commands.add_parser("exercise")
    restore_parser.add_argument("backup")
    restore_parser.add_argument("--source", required=True)
    for flag in ("operator-settings", "access-file", "target-file"):
        restore_parser.add_argument("--" + flag)
    restore_parser.add_argument("--pilot-controls", action="store_true")
    args = parser.parse_args()
    if args.command == "capture":
        result = capture(args)
    elif args.command == "exercise":
        result = exercise(args)
    else:
        manifest, members = verify(args.backup)
        result = {
            "result": "BACKUP_VERIFIED",
            "source_commit": manifest["source_commit"],
            "objects": len(members) - 1,
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (
        RecoveryError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as error:
        raise SystemExit(f"Recovery blocked: {error}") from None
