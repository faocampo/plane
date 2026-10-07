# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Run disjoint native suites or the separately configured host-only doubles."""

from pathlib import Path
import sys
import subprocess


ROOT = Path(__file__).resolve().parent
GROUPS = ("core", "manual-planning", "scope-regression", "host-doubles")
MANUAL_DIRECTORIES = frozenset({"manual_plan_v2", "scope_editor_v2", "manual_gate2_v2"})
SCOPE_FILES = frozenset(
    {
        "test_project_association_read_qualification.py",
        "test_scope_proposal_api.py",
        "test_scoped_prd_bridge.py",
        "test_scope_reopening_services.py",
        "test_scope_reopening_races.py",
    }
)


def partition(root=ROOT):
    """Every discovered test file gets exactly one group; new files default to core."""
    result = {group: [] for group in GROUPS}
    for path in sorted(root.rglob("test_*.py")):
        relative = path.relative_to(root)
        if "host" in relative.parts:
            group = "host-doubles"
        elif relative.parts[0] in MANUAL_DIRECTORIES:
            group = "manual-planning"
        elif relative.as_posix() in SCOPE_FILES:
            group = "scope-regression"
        else:
            group = "core"
        result[group].append(path)
    if any(not paths for paths in result.values()):
        raise ValueError("Every Curve CI partition must contain test files")
    return result


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in GROUPS:
        raise SystemExit("Choose exactly one known Curve CI group")
    paths = partition()[sys.argv[1]]
    if sys.argv[1] == "host-doubles":
        # Their bootstrap configures empty Django apps and requires the complete
        # checkout layout. Keep each host directory in a fresh Python process.
        results = [
            subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", str(directory), "-p", "test_*.py"])
            for directory in sorted({path.parent for path in paths})
        ]
        raise SystemExit(1 if any(results) else 0)
    # A direct script starts with the tests directory on sys.path, which shadows
    # the identically named runtime manual_plan_v2 package. Prefer runtime code.
    sys.path.insert(0, str(ROOT.parent))
    # Initialize Plane's Celery/Django environment before pytest plugin loading.
    import plane  # noqa: F401
    import pytest

    raise SystemExit(pytest.main(["-c", str(ROOT.parents[2] / "pytest.ini"), *(str(path) for path in paths), "-q"]))


if __name__ == "__main__":
    main()
