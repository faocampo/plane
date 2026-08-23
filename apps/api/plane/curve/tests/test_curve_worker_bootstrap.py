# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os
import subprocess
import sys

from plane.curve.temporal.registry import CURVE_WORKFLOW_TYPE_NAMES_V1


def test_curve_worker_registers_operation_parent_and_child_workflows():
    assert CURVE_WORKFLOW_TYPE_NAMES_V1 == (
        "CurveOperationWorkflowV1",
        "CurveInitiativeOrchestrationWorkflowV1",
        "CurveSliceAttemptWorkflowV1",
    )


def test_curve_worker_bootstrap_does_not_import_celery():
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "plane.settings.curve_worker"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import sys; import plane; assert plane.celery_app is None; assert 'plane.celery' not in sys.modules"),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
