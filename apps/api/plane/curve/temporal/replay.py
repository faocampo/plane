# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import argparse
import asyncio
import json
from pathlib import Path

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from plane.curve.temporal.workflows import CurveOperationWorkflowV1


async def replay_fixture(path: Path) -> None:
    fixture = json.loads(path.read_text())
    if fixture.get("schema_version") != "curve-temporal-history-fixture/v1":
        raise ValueError("unsupported Curve Temporal history fixture")
    history = WorkflowHistory.from_json(fixture["workflow_id"], fixture["history"])
    await Replayer(workflows=[CurveOperationWorkflowV1]).replay_workflow(history)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", nargs="+")
    args = parser.parse_args()
    for fixture in args.fixtures:
        asyncio.run(replay_fixture(Path(fixture)))


if __name__ == "__main__":
    main()
