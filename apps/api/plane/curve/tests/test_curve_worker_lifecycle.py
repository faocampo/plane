# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import asyncio

import pytest

from plane.curve.temporal.worker_lifecycle import supervise_worker_lifecycle


class FakeWorker:
    def __init__(
        self,
        worker_result: asyncio.Future[None],
        shutdown_error: BaseException | None = None,
        *,
        shutdown_started: asyncio.Event | None = None,
        shutdown_release: asyncio.Future[None] | None = None,
    ):
        self.worker_result = worker_result
        self.shutdown_error = shutdown_error
        self.shutdown_started = shutdown_started
        self.shutdown_release = shutdown_release
        self.shutdown_calls = 0
        self.shutdown_task: asyncio.Task[None] | None = None
        self.shutdown_cancelled = False

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.shutdown_task = asyncio.current_task()
        if self.shutdown_started is not None:
            self.shutdown_started.set()
        try:
            if self.shutdown_release is not None:
                await self.shutdown_release
            if self.shutdown_error is not None:
                raise self.shutdown_error
            if not self.worker_result.done():
                self.worker_result.set_result(None)
        except asyncio.CancelledError:
            self.shutdown_cancelled = True
            raise


async def _await_future(result: asyncio.Future[None]) -> None:
    await result


def _assert_all_tasks_settled(
    worker_task: asyncio.Task[None],
    relay_task: asyncio.Task[None],
    worker: FakeWorker,
) -> None:
    assert worker_task.done()
    assert relay_task.done()
    if worker.shutdown_task is not None:
        assert worker.shutdown_task.done()
    names = {task.get_name() for task in asyncio.all_tasks() if not task.done()}
    assert "curve-temporal-stop" not in names
    assert "curve-temporal-cleanup" not in names
    assert "curve-temporal-shutdown" not in names


def test_stop_request_settles_worker_and_relay_without_traceback():
    async def scenario():
        stop_event = asyncio.Event()
        stop_event.set()
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        await supervise_worker_lifecycle(
            worker=worker,
            worker_task=worker_task,
            relay_task=relay_task,
            stop_event=stop_event,
        )

        assert worker.shutdown_calls == 1
        assert worker_task.done()
        assert relay_task.cancelled()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_simultaneous_stop_and_worker_completion_is_graceful():
    async def scenario():
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        worker_result.set_result(None)
        relay_result: asyncio.Future[None] = loop.create_future()
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        await supervise_worker_lifecycle(
            worker=worker,
            worker_task=worker_task,
            relay_task=relay_task,
            stop_event=stop_event,
        )

        assert worker.shutdown_calls == 0
        assert relay_task.cancelled()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_simultaneous_stop_and_relay_completion_is_graceful():
    async def scenario():
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        relay_result.set_result(None)
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        await supervise_worker_lifecycle(
            worker=worker,
            worker_task=worker_task,
            relay_task=relay_task,
            stop_event=stop_event,
        )

        assert worker.shutdown_calls == 1
        assert worker_task.done()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_worker_failure_is_propagated_by_identity():
    async def scenario():
        error = ValueError("worker failed")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        worker_result.set_exception(error)
        relay_result: asyncio.Future[None] = loop.create_future()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(ValueError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            )

        assert captured.value is error
        assert worker.shutdown_calls == 0
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_relay_failure_is_propagated_by_identity():
    async def scenario():
        error = LookupError("relay failed")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        relay_result.set_exception(error)
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(LookupError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            )

        assert captured.value is error
        assert worker.shutdown_calls == 1
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_simultaneous_stop_and_worker_failure_preserves_failure():
    async def scenario():
        error = RuntimeError("worker failed during stop")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        worker_result.set_exception(error)
        relay_result: asyncio.Future[None] = loop.create_future()
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(RuntimeError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=stop_event,
            )

        assert captured.value is error
        assert worker.shutdown_calls == 0
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


@pytest.mark.parametrize("completed_task", ["worker", "relay"])
def test_normal_completion_without_stop_fails_closed(completed_task):
    async def scenario():
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        selected = worker_result if completed_task == "worker" else relay_result
        selected.set_result(None)
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(RuntimeError, match="Curve Temporal worker task exited unexpectedly"):
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            )

        expected_shutdown_calls = 0 if completed_task == "worker" else 1
        assert worker.shutdown_calls == expected_shutdown_calls
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_cleanup_calls_shutdown_once_and_leaves_no_task_orphaned():
    async def scenario():
        stop_event = asyncio.Event()
        stop_event.set()
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        await supervise_worker_lifecycle(
            worker=worker,
            worker_task=worker_task,
            relay_task=relay_task,
            stop_event=stop_event,
        )

        assert worker.shutdown_calls == 1
        assert worker_task.done()
        assert relay_task.done()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_simultaneous_stop_and_relay_failure_preserves_failure():
    async def scenario():
        error = RuntimeError("relay failed during stop")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        relay_result.set_exception(error)
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(RuntimeError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=stop_event,
            )

        assert captured.value is error
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_worker_failure_wins_when_worker_and_relay_fail_together():
    async def scenario():
        worker_error = ValueError("worker wins")
        relay_error = LookupError("relay loses")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        worker_result.set_exception(worker_error)
        relay_result.set_exception(relay_error)
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(ValueError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            )

        assert captured.value is worker_error
        assert relay_task.exception() is relay_error
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_shutdown_failure_cancels_and_settles_active_worker():
    async def scenario():
        shutdown_error = OSError("shutdown failed")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(worker_result, shutdown_error)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(OSError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=stop_event,
            )

        assert captured.value is shutdown_error
        assert worker.shutdown_calls == 1
        assert worker_task.cancelled()
        assert relay_task.cancelled()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_relay_failure_has_precedence_over_shutdown_failure():
    async def scenario():
        relay_error = LookupError("relay failure wins")
        shutdown_error = OSError("shutdown failure loses")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        relay_result.set_exception(relay_error)
        worker = FakeWorker(worker_result, shutdown_error)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")

        with pytest.raises(LookupError) as captured:
            await supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            )

        assert captured.value is relay_error
        assert worker.shutdown_calls == 1
        assert worker_task.cancelled()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_supervisor_cancellation_completes_cleanup_then_reraises():
    async def scenario():
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")
        supervisor = asyncio.create_task(
            supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            ),
            name="test-supervisor",
        )
        await asyncio.sleep(0)
        supervisor.cancel()

        with pytest.raises(asyncio.CancelledError):
            await supervisor

        assert worker.shutdown_calls == 1
        assert worker_task.done()
        assert relay_task.cancelled()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_worker_failure_has_precedence_over_supervisor_cancellation():
    async def scenario():
        error = RuntimeError("worker failure wins")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")
        supervisor = asyncio.create_task(
            supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            ),
            name="test-supervisor",
        )
        await asyncio.sleep(0)
        worker_result.set_exception(error)
        supervisor.cancel()

        with pytest.raises(RuntimeError) as captured:
            await supervisor

        assert captured.value is error
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_pre_start_worker_failure_cancels_pending_shutdown_and_preserves_failure():
    async def scenario():
        error = RuntimeError("worker failed before startup completed")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        shutdown_started = asyncio.Event()
        shutdown_release: asyncio.Future[None] = loop.create_future()
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(
            worker_result,
            shutdown_started=shutdown_started,
            shutdown_release=shutdown_release,
        )
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")
        supervisor = asyncio.create_task(
            supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=stop_event,
            ),
            name="test-supervisor",
        )

        await shutdown_started.wait()
        worker_result.set_exception(error)

        with pytest.raises(RuntimeError) as captured:
            await asyncio.wait_for(supervisor, timeout=1)

        assert captured.value is error
        assert worker.shutdown_calls == 1
        assert worker.shutdown_cancelled
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_relay_failure_has_precedence_over_supervisor_cancellation():
    async def scenario():
        error = LookupError("relay failure wins")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        worker = FakeWorker(worker_result)
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")
        supervisor = asyncio.create_task(
            supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=asyncio.Event(),
            ),
            name="test-supervisor",
        )
        await asyncio.sleep(0)
        relay_result.set_exception(error)
        supervisor.cancel()

        with pytest.raises(LookupError) as captured:
            await supervisor

        assert captured.value is error
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())


def test_shutdown_failure_has_precedence_over_supervisor_cancellation():
    async def scenario():
        error = OSError("shutdown failure wins")
        loop = asyncio.get_running_loop()
        worker_result: asyncio.Future[None] = loop.create_future()
        relay_result: asyncio.Future[None] = loop.create_future()
        shutdown_started = asyncio.Event()
        shutdown_release: asyncio.Future[None] = loop.create_future()
        stop_event = asyncio.Event()
        stop_event.set()
        worker = FakeWorker(
            worker_result,
            error,
            shutdown_started=shutdown_started,
            shutdown_release=shutdown_release,
        )
        worker_task = asyncio.create_task(_await_future(worker_result), name="test-worker")
        relay_task = asyncio.create_task(_await_future(relay_result), name="test-relay")
        supervisor = asyncio.create_task(
            supervise_worker_lifecycle(
                worker=worker,
                worker_task=worker_task,
                relay_task=relay_task,
                stop_event=stop_event,
            ),
            name="test-supervisor",
        )

        await shutdown_started.wait()
        supervisor.cancel()
        shutdown_release.set_result(None)

        with pytest.raises(OSError) as captured:
            await supervisor

        assert captured.value is error
        assert worker_task.cancelled()
        _assert_all_tasks_settled(worker_task, relay_task, worker)

    asyncio.run(scenario())
