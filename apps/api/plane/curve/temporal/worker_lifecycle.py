# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio
from dataclasses import dataclass
from typing import Protocol


class WorkerLifecycle(Protocol):
    async def shutdown(self) -> None: ...


@dataclass(frozen=True)
class _CleanupResult:
    worker_result: object
    relay_result: object
    shutdown_result: object


async def _complete_cleanup(
    *,
    worker: WorkerLifecycle,
    worker_task: asyncio.Task[None],
    relay_task: asyncio.Task[None],
    stop_task: asyncio.Task[bool],
) -> _CleanupResult:
    shutdown_result: object = None
    try:
        if not worker_task.done():
            shutdown_task = asyncio.create_task(
                worker.shutdown(),
                name="curve-temporal-shutdown",
            )
            await asyncio.wait(
                {worker_task, shutdown_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if worker_task.done() and not shutdown_task.done():
                shutdown_task.cancel()
            shutdown_result = (
                await asyncio.gather(shutdown_task, return_exceptions=True)
            )[0]
            if _non_cancellation_failure(shutdown_result) and not worker_task.done():
                worker_task.cancel()

        worker_result, relay_result = await asyncio.gather(
            worker_task,
            relay_task,
            return_exceptions=True,
        )
        return _CleanupResult(
            worker_result=worker_result,
            relay_result=relay_result,
            shutdown_result=shutdown_result,
        )
    finally:
        if not stop_task.done():
            stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)


def _non_cancellation_failure(result: object) -> BaseException | None:
    if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
        return result
    return None


async def supervise_worker_lifecycle(
    *,
    worker: WorkerLifecycle,
    worker_task: asyncio.Task[None],
    relay_task: asyncio.Task[None],
    stop_event: asyncio.Event,
) -> None:
    """Settle the Curve worker and relay without masking their original failures."""

    stop_task = asyncio.create_task(stop_event.wait(), name="curve-temporal-stop")
    completed: set[asyncio.Task[object]] = set()
    supervisor_cancelled = False

    try:
        completed, _ = await asyncio.wait(
            {worker_task, relay_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        supervisor_cancelled = True

    stop_requested = stop_event.is_set()
    unexpected_completion = not stop_requested and bool(completed & {worker_task, relay_task})

    stop_event.set()
    if not relay_task.done():
        relay_task.cancel()

    cleanup_task = asyncio.create_task(
        _complete_cleanup(
            worker=worker,
            worker_task=worker_task,
            relay_task=relay_task,
            stop_task=stop_task,
        ),
        name="curve-temporal-cleanup",
    )
    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            supervisor_cancelled = True

    cleanup = cleanup_task.result()
    for result in (
        cleanup.worker_result,
        cleanup.relay_result,
        cleanup.shutdown_result,
    ):
        if failure := _non_cancellation_failure(result):
            raise failure

    if supervisor_cancelled:
        raise asyncio.CancelledError
    if unexpected_completion:
        raise RuntimeError("Curve Temporal worker task exited unexpectedly")
