# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Verify the single installed local implementation through its original read-only bind.

Only this project's disposable test database is used. No host service is activated.
The prospective Gate2 assembly remains reproducible at commit 8fc8e15.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REPOSITORY = Path(__file__).resolve().parents[3]
TESTS = "plane/curve/tests/manual_plan_v2/"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=[
            "all",
            "sql",
            "worker",
            "authority",
            "installed",
            "persistence",
            "migration",
            "regression",
            "scope",
            "gate2",
        ],
    )
    parser.add_argument("--fresh-db", action="store_true", help="Recreate only the disposable test database")
    args = parser.parse_args()
    targets = {
        "all": [TESTS, "plane/curve/tests/scope_editor_v2/", "plane/curve/tests/manual_gate2_v2/"],
        "gate2": ["plane/curve/tests/manual_gate2_v2/"],
        "scope": ["plane/curve/tests/scope_editor_v2/"],
        "sql": [TESTS + "test_shape_sql.py"],
        "worker": [TESTS + "test_linux_worker.py"],
        "authority": [TESTS + "test_native_authority.py"],
        "installed": [TESTS + "test_installed_guards.py"],
        "persistence": [TESTS + "test_manual_persistence.py"],
        "migration": [TESTS + "test_complete_migration.py"],
        "regression": [
            "plane/curve/tests/" + name
            for name in [
                "test_project_association_read_qualification.py",
                "test_scope_proposal_api.py",
                "test_scoped_prd_bridge.py",
                "test_scope_reopening_services.py",
                "test_scope_reopening_races.py",
            ]
        ],
    }[args.phase]
    proof = REPOSITORY / "apps/api/plane/curve/manual_plan_draft_reconstruction_qualification_v2.json"
    scope_proof = proof.with_name("scope_editor_read_reconstruction_qualification_v2.json")
    print(
        json.dumps(
            {
                "phase": args.phase,
                "application": "INSTALLED_LOCAL_SOURCE",
                "manual_proof_digest": "sha256:" + hashlib.sha256(proof.read_bytes()).hexdigest(),
                "scope_proof_digest": "sha256:" + hashlib.sha256(scope_proof.read_bytes()).hexdigest(),
                "gate2_proof_digest": "sha256:"
                + hashlib.sha256(
                    proof.with_name("manual_gate2_reconstruction_qualification_v2.json").read_bytes()
                ).hexdigest(),
                "fresh_test_database": args.fresh_db,
            }
        ),
        flush=True,
    )
    paths = ["/code", "/code/plane/curve", "/code/" + TESTS.rstrip("/"), "/code/" + TESTS + "host"]
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
        "env",
        "PYTHONPATH=" + ":".join(paths),
        "python",
        "-c",
        "import plane,pytest,sys; raise SystemExit(pytest.main(sys.argv[1:]))",
        "-c",
        "/code/pytest.ini",
        "-q",
        "--tb=short",
        "--maxfail=1",
        "-o",
        "addopts=--reuse-db --migrations",
        "-o",
        "cache_dir=/tmp/pytest-cache",
        *(["--create-db"] if args.fresh_db else []),
        *targets,
    ]
    raise SystemExit(subprocess.run(command, cwd=REPOSITORY, stdin=subprocess.DEVNULL).returncode)


if __name__ == "__main__":
    main()
