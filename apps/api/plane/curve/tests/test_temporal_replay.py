# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os
from pathlib import Path
import subprocess
import sys

FIXTURE = Path(__file__).parent / "fixtures" / "temporal" / "curve-operation-v1.json"
SENTINEL = "CURVE_PROTECTED_SENTINEL_M0_S3"


def test_committed_temporal_history_replays_deterministically():
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "plane.settings.curve_worker"
    result = subprocess.run(
        [sys.executable, "-m", "plane.curve.temporal.replay", str(FIXTURE)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_committed_temporal_history_excludes_protected_sentinel():
    assert SENTINEL not in FIXTURE.read_text()
