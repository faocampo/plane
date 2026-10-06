"""Real Linux process/limits checks, independent of DB persistence qualification."""

from copy import deepcopy
import json
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
import time

import pytest

from plane.curve.manual_plan_v2 import validator_worker as worker
from plane.curve.manual_plan_v2.contracts import ManualPlanError
from semantic_fixture import semantic_case

pytestmark = pytest.mark.unit
OVERLAY = str(Path(worker.__file__).resolve().parent.parent)
IMPORT = f"import sys;sys.path.insert(0,{OVERLAY!r});from manual_plan_v2 import validator_worker as w;"


def captured():
    raw, identity, facts, sources, materials = semantic_case()
    return SimpleNamespace(
        definition=raw, identity=identity, facts=facts, semantic_sources=sources, materials=materials
    )


def test_real_worker_accepts_bound_semantics_and_rejects_edited_facts():
    value = captured()
    result = worker.validate_in_worker(value)
    assert result["result"] == "VALID"
    assert result["input_identity_digest"] == value.identity["digest"]
    changed = deepcopy(value)
    changed.facts["required_check_ids"] = []
    with pytest.raises(ManualPlanError) as error:
        worker.validate_in_worker(changed)
    assert error.value.code == "MANUAL_PLAN_DRAFT_VALIDATION_FAILED"


def test_limits_are_applied_in_actual_isolated_python_process():
    code = (
        IMPORT + "import resource,json;w._restrict_process();"
        "print(json.dumps({name:resource.getrlimit(getattr(resource,name)) for name in "
        "['RLIMIT_CPU','RLIMIT_AS','RLIMIT_NOFILE','RLIMIT_FSIZE','RLIMIT_CORE']}))"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True, text=True, timeout=5)
    assert json.loads(result.stdout) == dict(
        RLIMIT_CPU=[15, 15],
        RLIMIT_AS=[536870912, 536870912],
        RLIMIT_NOFILE=[32, 32],
        RLIMIT_FSIZE=[16384, 16384],
        RLIMIT_CORE=[0, 0],
    )


def test_memory_and_descriptor_limits_are_enforced():
    code = (
        IMPORT
        + """
import errno,os
w._restrict_process()
try: bytearray(600*1024*1024)
except MemoryError: print("memory-limited",flush=True)
else: raise AssertionError("allocation was not limited")
fds=[]
try:
    for _ in range(100): fds.append(os.open("/dev/null",os.O_RDONLY))
except OSError as error:
    assert error.errno==errno.EMFILE
    print("descriptors-limited",flush=True)
else: raise AssertionError("descriptors were not limited")
"""
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True, text=True, timeout=5)
    assert result.stdout.splitlines() == ["memory-limited", "descriptors-limited"]


def test_cpu_limit_terminates_inert_busy_child():
    code = IMPORT + "w._restrict_process();exec('while True: pass')"
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, timeout=25)
    assert result.returncode in {-signal.SIGKILL, -signal.SIGXCPU}
    assert time.monotonic() - started < 25


def test_cross_process_ceiling_and_interruption_releases_the_slots():
    children = []
    try:
        for _ in range(2):
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    IMPORT + "fd=w._acquire_process_slot();print('ready',flush=True);sys.stdin.read()",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            children.append(process)
            assert process.stdout.readline().strip() == "ready"
        with pytest.raises(ManualPlanError) as error:
            worker.validate_in_worker(captured())
        assert error.value.code == "MANUAL_PLAN_DRAFT_VALIDATION_UNAVAILABLE"
        children[0].kill()
        children[0].wait(timeout=5)
        assert worker.validate_in_worker(captured())["result"] == "VALID"
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


def test_fixed_child_parser_rejects_unknown_keys_and_oversized_input():
    for data in (b'{"execute":"never"}', b" " * (worker.MAX_JOB_BYTES + 1)):
        result = subprocess.run([sys.executable, "-I", worker.__file__], input=data, capture_output=True, timeout=10)
        assert result.returncode == 2
        assert result.stdout == b"" and result.stderr == b""
