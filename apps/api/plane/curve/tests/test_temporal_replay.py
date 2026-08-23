# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os
from pathlib import Path
import subprocess
import sys

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "temporal"
FIXTURES = tuple(sorted(FIXTURE_DIRECTORY.glob("*.json")))
EXPECTED_FIXTURE_NAMES = {
    "curve-initiative-continued-v1.json",
    "curve-initiative-parent-v1.json",
    "curve-operation-v1.json",
    "curve-slice-attempt-v1.json",
}
SENTINELS = ("CURVE_PROTECTED_SENTINEL_M0_S3", "CURVE_PROTECTED_SENTINEL_M0_S6A")


def test_committed_temporal_histories_replay_deterministically():
    assert {path.name for path in FIXTURES} == EXPECTED_FIXTURE_NAMES
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "plane.settings.curve_worker"
    result = subprocess.run(
        [sys.executable, "-m", "plane.curve.temporal.replay", *(str(path) for path in FIXTURES)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_committed_temporal_histories_exclude_protected_sentinels():
    assert FIXTURES
    for fixture in FIXTURES:
        fixture_text = fixture.read_text()
        for sentinel in SENTINELS:
            assert sentinel not in fixture_text
