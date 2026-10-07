#!/usr/bin/env python3
"""Qualify persistent storage in a disposable synthetic installation only.

No host ports, external network, source mutation, live migration or data retention
decision. Named volumes survive container loss during the exercise and are removed
afterwards. An owner-only journal supports cleanup after operator interruption.
"""

import argparse
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys

import recovery as r

LABEL = "io.curve.synthetic-recovery"
FORMAT = "curve.synthetic-persistence-journal/v1"
NAME = re.compile(r"curve-recovery-check-[0-9a-f]{12}")

STORE_SCRIPT = r"""
import json, os, sys
from pathlib import Path
from probe import restore_objects, verify_existing_objects
mode, digest = sys.argv[1:3]
root=Path('/demo-data/protected')
if mode == 'initialize':
 restore_objects(sys.stdin.buffer, digest)
elif mode == 'verify':
 print(json.dumps({'objects': verify_existing_objects(digest)}))
elif mode == 'check_pgdata':
 assert Path('/pgdata/PG_VERSION').read_text().strip() == '15'
elif mode == 'permissions':
 os.chmod(root/'catalog.json', int(sys.argv[3], 8))
elif mode == 'flip':
 import uuid
 name=str(uuid.UUID(sys.argv[3]))
 path=root/name
 raw=path.read_bytes()
 assert raw
 path.write_bytes(bytes([raw[0]^1])+raw[1:])
else:
 raise RuntimeError('Unknown store operation')
"""


def inventory(kind):
    command = ["docker", kind, "ls", "--format", "{{.Name}}"]
    if kind == "container":
        command = ["docker", "ps", "-a", "--format", "{{.Names}}"]
    return set(r.run(command).decode().splitlines())


def owned(kind, name, token, absent_ok=False):
    r.require(NAME.fullmatch(token), "Invalid qualification owner")
    r.require(
        name in {token, token + "-migrate", token + "-api-read", token + "-store", token + "-db", token + "-objects"},
        "Resource outside qualification boundary",
    )
    if name not in inventory(kind):
        r.require(absent_ok, "Owned resource is missing; refusing implicit reinitialization")
        return False
    info = json.loads(r.run(["docker", kind, "inspect", name]))[0]
    labels = info.get("Labels") if kind == "volume" else info["Config"].get("Labels")
    r.require((labels or {}).get(LABEL) == token, "Resource ownership label mismatch")
    return info


def read_journal(path):
    path = Path(path)
    r.require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_uid == os.getuid()
        and path.stat().st_mode & 0o077 == 0
        and path.stat().st_size <= 1048576,
        "Journal must be an owner-only regular file",
    )
    state = json.loads(path.read_text())
    r.require(state.get("format") == FORMAT and NAME.fullmatch(state.get("owner", "")), "Invalid persistence journal")
    token = state["owner"]
    r.require(state.get("volumes") == [token + "-db", token + "-objects"], "Journal names unexpected volumes")
    containers = {token, token + "-migrate", token + "-api-read", token + "-store"}
    r.require(
        isinstance(state.get("managed_volumes"), list)
        and set(state["managed_volumes"]) <= set(state["volumes"])
        and isinstance(state.get("managed_containers"), list)
        and set(state["managed_containers"]) <= containers,
        "Journal ownership claims are invalid",
    )
    return state


def cleanup(state):
    """Refuse unrelated resources; attempt all owned cleanup and report failures."""
    token, failures = state["owner"], []
    for kind, names in (
        ("container", state["managed_containers"]),
        ("volume", state["managed_volumes"]),
    ):
        for name in names:
            try:
                if owned(kind, name, token, absent_ok=True):
                    r.run(
                        ["docker", "container", "rm", "-f", name]
                        if kind == "container"
                        else ["docker", "volume", "rm", name]
                    )
            except (r.RecoveryError, subprocess.TimeoutExpired):
                failures.append(name)
    r.require(not failures, "Owned cleanup incomplete; consult the private journal before retrying")
    r.require(not set(state["managed_volumes"]) & inventory("volume"), "Volume cleanup not verified")


class Lifecycle:
    def __init__(self, args):
        self.args = args
        self.path = Path(args.journal).absolute()
        r.require(
            self.path.parent.is_dir()
            and self.path.parent.stat().st_uid == os.getuid()
            and not self.path.parent.is_symlink()
            and self.path.parent.stat().st_mode & 0o077 == 0,
            "Journal parent must be an owner-only directory",
        )
        r.require(not self.path.exists() and not self.path.is_symlink(), "Journal destination must be new")
        self.state = None
        self.container_names_reserved = False
        self.stage = "INPUT_VALIDATION"

    def write(self, stage):
        self.stage = stage
        if self.state is None:
            return
        self.state["stage"] = stage
        temp = self.path.with_name(self.path.name + ".next")
        r.private_file(temp, (json.dumps(self.state, indent=2) + "\n").encode())
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        temp.replace(self.path)
        fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def prepare(self, name, manifest):
        self.name, self.manifest = name, manifest
        self.state = {
            "format": FORMAT,
            "owner": name,
            "volumes": [name + "-db", name + "-objects"],
            "stage": "PREPARING",
            "events": [],
            "managed_volumes": [],
            "managed_containers": [],
        }
        self.write("PREPARING")
        containers = [name + "-api-read", name + "-store", name + "-migrate", name]
        r.require(not set(containers) & inventory("container"), "Refusing to adopt an existing container")
        self.state["managed_containers"] = containers
        self.container_names_reserved = True
        self.write("PREPARING")
        for volume in self.state["volumes"]:
            r.require(volume not in inventory("volume"), "Refusing to adopt an existing volume")
            self.state["managed_volumes"].append(volume)
            self.write("PREPARING")
            r.run(["docker", "volume", "create", "--label", f"{LABEL}={name}", volume])
            owned("volume", volume, name)
        self.write("RESTORING_NEW_TARGET")
        return self.storage()

    def storage(self):
        for volume in self.state["volumes"]:
            owned("volume", volume, self.name)
        return ["--mount", f"type=volume,src={self.name}-db,dst=/var/lib/postgresql/data"]

    def event(self, value):
        self.state["events"].append(value)
        self.write(self.stage)

    def store(self, mode, *extra, read_only=True, expect_failure=False):
        self.storage()
        helper = self.name + "-store"
        argv = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--pull=never",
            "--name",
            helper,
            "--label",
            f"{LABEL}={self.name}",
            "--network",
            "none",
            "--read-only",
            "--memory",
            "256m",
            "--cpus",
            "1",
            "--pids-limit",
            "64",
            "--log-driver",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--workdir",
            "/",
            "--mount",
            f"type=volume,src={self.name}-objects,dst=/demo-data" + (",readonly" if read_only else ""),
            "--mount",
            f"type=volume,src={self.name}-db,dst=/pgdata,readonly",
            "--mount",
            f"type=bind,src={Path(__file__).with_name('http_probe.py').resolve()},dst=/probe.py,readonly",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        if mode == "check_pgdata":
            argv.extend(
                [
                    "--user",
                    "postgres",
                    "--entrypoint",
                    "sh",
                    self.manifest["postgres_image_id"],
                    "-c",
                    'test "$(cat /pgdata/PG_VERSION)" = 15',
                ]
            )
        else:
            argv.extend(
                [
                    "--entrypoint",
                    "python",
                    self.manifest["api_image_id"],
                    "-c",
                    STORE_SCRIPT,
                    mode,
                    self.manifest["catalog_sha256"],
                    *extra,
                ]
            )
        try:
            with (Path(self.args.backup) / "protected.tar").open("rb") as archive:
                result = subprocess.run(
                    argv,
                    stdin=archive if mode == "initialize" else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
            r.require(
                (result.returncode != 0) if expect_failure else (result.returncode == 0),
                "Persistent store did not satisfy the expected readiness boundary",
            )
            return result.stdout
        finally:
            r.cleanup_owned(helper, self.name)

    def verify_database(self, expected):
        info = owned("container", self.name, self.name)
        r.require(
            info["HostConfig"]["NetworkMode"] == "none"
            and not info["HostConfig"].get("PortBindings")
            and info["HostConfig"]["ReadonlyRootfs"],
            "Database isolation changed",
        )
        r.require(
            any(
                m.get("Name") == self.name + "-db" and m["Destination"] == "/var/lib/postgresql/data"
                for m in info["Mounts"]
            ),
            "Database does not use its owned persistent volume",
        )
        r.require(
            r.fingerprints(self.name, "curve_recovery", "curve_recovery") == expected,
            "Database changed across lifecycle boundary",
        )
        r.require(
            r.schema_fingerprint(self.name, "curve_recovery", "curve_recovery") == self.manifest["schema_sha256"],
            "Persistent schema changed",
        )
        r.run(
            r.psql(self.name, "curve_recovery", "curve_recovery")
            + ["-c", "SELECT curve_scope_reopening_verify_coverage();"]
        )
        durability = r.run(
            r.psql(self.name, "curve_recovery", "curve_recovery")
            + ["-c", "SHOW fsync; SHOW full_page_writes; SHOW synchronous_commit;"]
        )
        r.require(durability.split() == [b"on", b"on", b"on"], "PostgreSQL durability settings are not enabled")

    def api(self, args, source, manifest, name, profile):
        self.store("verify")
        args._protected_volume = self.name + "-objects"
        return r.check_restored_api(args, source, manifest, name, profile)

    def qualify(self, args, source, manifest, members, name, profile):
        r.require(
            profile is not None and not getattr(args, "pilot_controls", False),
            "Persistence requires the read-only HTTP profile",
        )
        self.write("INITIALIZING_PROTECTED_STORE")
        self.store("initialize", read_only=True, expect_failure=True)
        self.event("read_only_storage_refuses_initialization")
        self.store("initialize", read_only=False)
        self.store("initialize", read_only=False, expect_failure=True)
        self.store("verify")
        self.event("existing_protected_store_cannot_be_overwritten")
        self.verify_database(manifest["tables"])
        first = self.api(args, source, manifest, name, profile)
        checkpoint = r.fingerprints(name, "curve_recovery", "curve_recovery")
        r.require(checkpoint != manifest["tables"], "Expected authenticated writes were not observed")
        self.event("session_login_and_protected_read_on_persistent_stores")

        self.write("GRACEFUL_STOP_RESUME")
        owned("container", name, name)
        r.run(["docker", "stop", "--time", "20", name])
        self.store("check_pgdata")
        r.run(["docker", "start", name])
        r.wait_database(name)
        self.verify_database(checkpoint)
        self.api(args, source, manifest, name, profile)
        self.event("graceful_resume_preserves_all_rows_schema_objects_and_access")

        self.write("CRASH_AND_CONTAINER_REPLACEMENT")
        checkpoint = r.fingerprints(name, "curve_recovery", "curve_recovery")
        pending = subprocess.Popen(
            r.psql(name, "curve_recovery", "curve_recovery"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            pending.stdin.write(
                b"BEGIN; UPDATE users SET first_name='uncommitted-persistence-probe' "
                b"WHERE id=(SELECT id FROM users ORDER BY id LIMIT 1); SELECT 'TRANSACTION_OPEN';\n"
            )
            pending.stdin.flush()
            r.require(
                select.select([pending.stdout], [], [], 12)[0]
                and pending.stdout.readline().strip() == b"TRANSACTION_OPEN",
                "Crash transaction did not open",
            )
            owned("container", name, name)
            r.run(["docker", "kill", "--signal", "KILL", name])
            pending.wait(timeout=10)
        finally:
            if pending.poll() is None:
                pending.terminate()
                pending.wait(timeout=5)
            pending.stdin.close()
            pending.stdout.close()
        r.cleanup_owned(name, name)
        self.store("check_pgdata")
        r.run(r.database_argv(name, manifest, self.storage()))
        r.wait_database(name)
        self.verify_database(checkpoint)
        self.api(args, source, manifest, name, profile)
        self.event("container_replacement_preserves_committed_rows_and_rolls_back_open_transaction")

        self.write("STORAGE_FAULTS")
        try:
            self.store("permissions", "644", read_only=False)
            self.store("verify", expect_failure=True)
        finally:
            self.store("permissions", "600", read_only=False)
        self.event("unsafe_catalog_permissions_fence_readiness")
        object_name = next(key for key in members if key != "catalog.json" and members[key])
        flipped = False
        try:
            self.store("flip", object_name, read_only=False)
            flipped = True
            self.store("verify", expect_failure=True)
        finally:
            if flipped:
                self.store("flip", object_name, read_only=False)
        self.event("corrupt_persistent_body_fences_readiness")
        self.store("verify")
        self.api(args, source, manifest, name, profile)
        self.event("exact_storage_repair_restores_authenticated_read")
        self.write("QUALIFIED_CLEANUP_PENDING")
        return {
            "result": "SYNTHETIC_PERSISTENCE_QUALIFIED",
            "cases": list(self.state["events"]),
            "tables_per_boundary": len(manifest["tables"]),
            "objects_per_boundary": len(members) - 1,
            "durability_settings_verified": True,
            "protected_api_mount_read_only": True,
            "initial_http": first,
            "live_demo_modified": False,
            "operational_acceptance": False,
            "scope": (
                "Container stop, PostgreSQL crash and replacement only; "
                "no host power-loss, real identity, retention or production certification"
            ),
        }


def qualify(args):
    r.require(args.synthetic_local, "Explicit synthetic qualification scope is required")
    r.require(r.read_profile(args) is not None, "Complete private HTTP profile is required")
    lifecycle = Lifecycle(args)
    args._lifecycle = lifecycle
    try:
        result = r.exercise(args)
        lifecycle.state["outcome"] = "QUALIFIED"
    except BaseException:
        if lifecycle.state is not None:
            lifecycle.state["outcome"] = "FAILED"
            lifecycle.state["failure_stage"] = lifecycle.stage
        raise
    finally:
        if lifecycle.state is not None:
            try:
                cleanup(lifecycle.state)
                lifecycle.write("CLEANED")
            except BaseException:
                lifecycle.write("CLEANUP_REQUIRED")
                raise
    result["persistence"]["owned_resources_removed"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exercise = commands.add_parser("exercise")
    exercise.add_argument("backup")
    exercise.add_argument("--synthetic-local", action="store_true")
    for flag in ("source", "journal", "operator-settings", "access-file", "target-file"):
        exercise.add_argument("--" + flag, required=True)
    rollback = commands.add_parser("cleanup")
    rollback.add_argument("--journal", required=True)
    args = parser.parse_args()

    def interrupt(*_):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupt)
    try:
        if args.command == "cleanup":
            cleanup(read_journal(args.journal))
            result = {"result": "OWNED_SYNTHETIC_RESOURCES_REMOVED"}
        else:
            result = qualify(args)
        print(json.dumps(result, indent=2))
    except (r.RecoveryError, OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        print(
            json.dumps(
                {
                    "result": "PERSISTENCE_OPERATION_FAILED",
                    "category": type(error).__name__,
                    "message": str(error)
                    if isinstance(error, r.RecoveryError)
                    else "Operation interrupted or unavailable; inspect the private journal",
                    "operational_acceptance": False,
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
