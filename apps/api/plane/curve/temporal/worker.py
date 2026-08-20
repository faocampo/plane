# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
import concurrent.futures
import logging
import os
import signal


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.curve_worker")

from plane.curve.temporal.environment import validate_worker_environment  # noqa: E402


validate_worker_environment()

import django  # noqa: E402


django.setup()

from temporalio.client import Client  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from plane.curve.config import validate_curve_policy_configuration  # noqa: E402
from plane.curve.temporal.activities import (  # noqa: E402
    mark_operation_cancelled,
    mark_operation_running,
    mark_operation_succeeded,
)
from plane.curve.temporal.relay import run_relay_loop  # noqa: E402
from plane.curve.temporal.workflows import CurveOperationWorkflowV1  # noqa: E402


logger = logging.getLogger(__name__)


async def run_worker() -> None:
    validate_curve_policy_configuration()
    address = os.environ["TEMPORAL_ADDRESS"]
    namespace = os.environ["TEMPORAL_NAMESPACE"]
    task_queue = os.environ["TEMPORAL_TASK_QUEUE"]
    identity = os.environ["TEMPORAL_WORKER_IDENTITY"]
    client = await Client.connect(address, namespace=namespace)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop_event.set)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="curve-activity") as executor:
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CurveOperationWorkflowV1],
            activities=[
                mark_operation_running,
                mark_operation_succeeded,
                mark_operation_cancelled,
            ],
            activity_executor=executor,
            identity=identity,
            max_concurrent_activities=8,
            max_concurrent_workflow_tasks=16,
        )
        worker_task = asyncio.create_task(worker.run(), name="curve-temporal-worker")
        relay_task = asyncio.create_task(
            run_relay_loop(client=client, worker_id=identity, stop_event=stop_event),
            name="curve-temporal-relay",
        )
        stop_task = asyncio.create_task(stop_event.wait(), name="curve-temporal-stop")
        completed, _ = await asyncio.wait(
            {worker_task, relay_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        unexpected = completed - {stop_task}
        stop_event.set()
        relay_task.cancel()
        await worker.shutdown()
        results = await asyncio.gather(worker_task, relay_task, return_exceptions=True)
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        if unexpected:
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result
            raise RuntimeError("Curve Temporal worker task exited unexpectedly")


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Curve Temporal worker interrupted")


if __name__ == "__main__":
    main()
