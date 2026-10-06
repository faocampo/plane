"""Bounded inert validation process; output is only a closed receipt."""

import base64
import json
import os
import stat
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

MAX_JOB_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_BYTES = 16384
_SLOTS = threading.BoundedSemaphore(2)


def _acquire_process_slot():
    """Two simultaneous children across API processes sharing this Linux /tmp."""
    import fcntl
    from .contracts import ManualPlanError, require

    root = f"/tmp/curve-manual-plan-v2-workers-{os.getuid()}"
    os.makedirs(root, mode=0o700, exist_ok=True)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "VALIDATION_UNAVAILABLE")
        for index in range(2):
            fd = os.open(str(index), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                info = os.fstat(fd)
                require(
                    stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1,
                    "VALIDATION_UNAVAILABLE",
                )
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                os.close(fd)
            except BaseException:
                os.close(fd)
                raise
    finally:
        os.close(directory)
    raise ManualPlanError("VALIDATION_UNAVAILABLE")


def validate_in_worker(captured):
    from .contracts import ManualPlanError, require, validate
    from .validation import canonical_json, metadata_digest, parse_strict_json

    # Linux limits are qualified separately. Do not silently downgrade on hosts
    # whose virtual-address-space limiter differs (including the current Mac).
    require(sys.platform == "linux", "VALIDATION_UNAVAILABLE")
    if not _SLOTS.acquire(blocking=False):
        raise ManualPlanError("VALIDATION_UNAVAILABLE")
    process = None
    slot = None
    try:
        slot = _acquire_process_slot()
        job = canonical_json(
            dict(
                definition=base64.b64encode(captured.definition).decode("ascii"),
                identity=captured.identity,
                facts=captured.facts,
                semantic_sources=captured.semantic_sources,
                materials={key: base64.b64encode(raw).decode("ascii") for key, raw in captured.materials.items()},
            )
        )
        require(len(job) <= MAX_JOB_BYTES, "VALIDATION_UNAVAILABLE")
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as result:
            source.write(job)
            source.seek(0)
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve())],
                stdin=source,
                stdout=result,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env={"PATH": os.defpath, "LANG": "C.UTF-8"},
            )
            try:
                status = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                raise ManualPlanError("VALIDATION_UNAVAILABLE") from None
            if status == 2:
                raise ManualPlanError("VALIDATION_FAILED")
            require(status == 0, "VALIDATION_UNAVAILABLE")
            result.seek(0)
            raw = result.read(MAX_RECEIPT_BYTES + 1)
        receipt = parse_strict_json(raw, max_bytes=MAX_RECEIPT_BYTES)
        validate("manual-plan-validation-receipt-v2", receipt)
        require(
            receipt["digest"] == metadata_digest(receipt)
            and receipt["input_identity_digest"] == captured.identity["digest"]
            and receipt["definition_digest"] == captured.identity["definition_ref"]["digest"],
            "VALIDATION_UNAVAILABLE",
        )
        return receipt
    except ManualPlanError:
        raise
    except Exception:
        raise ManualPlanError("VALIDATION_UNAVAILABLE") from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if slot is not None:
            os.close(slot)
        _SLOTS.release()


def _restrict_process():
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RECEIPT_BYTES, MAX_RECEIPT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _child():
    if sys.platform != "linux":
        return 3
    # Never write partial bytecode caches under the output-file size ceiling.
    # The worker imports trusted source only and needs no persistent cache.
    sys.dont_write_bytecode = True
    _restrict_process()
    # A fixed path derived from this trusted module, never a request/config path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from manual_plan_v2.validation import InvalidPlan, parse_strict_json, validate_definition, derive_semantic_facts

    try:
        job = parse_strict_json(sys.stdin.buffer.read(MAX_JOB_BYTES + 1), max_bytes=MAX_JOB_BYTES)
        if type(job) is not dict or set(job) != {"definition", "identity", "facts", "semantic_sources", "materials"}:
            return 2
        raw = base64.b64decode(job["definition"], validate=True)
        if type(job["materials"]) is not dict or len(job["materials"]) > 512:
            return 2
        materials = {key: base64.b64decode(value, validate=True) for key, value in job["materials"].items()}
        if sum(len(value) for value in materials.values()) > 16 * 1024 * 1024:
            return 2
        facts = derive_semantic_facts(job["identity"], job["semantic_sources"], materials, job["facts"])
        receipt = validate_definition(raw, job["identity"], facts)
        encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            return 3
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        return 0
    except InvalidPlan:
        return 2
    except Exception:
        return 3


if __name__ == "__main__":
    sys.exit(_child())
