# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real PostgreSQL lock ordering, duplicate workers, and native-revocation races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from plane.db.models import Issue, ProjectMember
from plane.curve.models import PrdReviewDecision, DocumentCheckpoint
from plane.curve.policy_services import request_operation_cancellation
from plane.curve.prd_commands import PrdCommandError
from plane.curve.prd_completion import PrdCompletionUnavailable
from plane.curve.scoped_prd_completion import complete_scoped_prd_operation
from plane.curve.scoped_prd_models import ScopedPrdSubject, ScopedPrdDecision, ScopedPrdAcceptedCommand
from plane.curve.tests.test_scoped_prd_bridge import (  # noqa: F401
    bridge as bridge_fixture,
    context,
    configuration,
    submission,
    accept,
    complete,
    submit,
    review_command,
)
from plane.curve.tests.test_project_association_api import end

bridge = bridge_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def worker(call):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '8s'")
        return call()
    finally:
        close_old_connections()


def cancel(bridge, operation):
    operation.refresh_from_db()
    return request_operation_cancellation(
        request=bridge.request,
        workspace_slug=bridge.workspace.slug,
        operation_id=operation.id,
        expected_version=operation.aggregate_version,
        raw_idempotency_key="cancel-scoped",
        canonical_request=b"{}",
    )


def test_duplicate_completion_workers_apply_one_effect(bridge):
    operation = accept(bridge, submission(bridge)).operation
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=10)
        return complete(bridge, operation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, run) for _ in range(2)]
        results = [future.result(timeout=25) for future in futures]
    assert [result["status"] for result in results] == ["SUCCEEDED", "SUCCEEDED"]
    assert sorted(result["effect_applied"] for result in results) == [False, True]
    assert DocumentCheckpoint.objects.count() == ScopedPrdSubject.objects.count() == 1


def test_competing_review_operations_cannot_approve_twice(bridge):
    subject, _, _ = submit(bridge)
    operations = [accept(bridge, review_command(bridge, subject)).operation for _ in range(2)]
    barrier = Barrier(2)

    def run(operation):
        barrier.wait(timeout=10)
        return complete(bridge, operation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, lambda op=op: run(op)) for op in operations]
        results = [future.result(timeout=25) for future in futures]
    assert sorted(result["status"] for result in results) == ["FAILED", "SUCCEEDED"]
    assert PrdReviewDecision.objects.count() == ScopedPrdDecision.objects.count() == 1


@pytest.mark.parametrize("native_change", ["metadata", "reviewer_membership"])
def test_native_write_waits_for_final_source_fence_then_revokes_replay(bridge, native_change):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject)).operation
    attempted, completed = Event(), Event()
    tasks = []
    with ThreadPoolExecutor(max_workers=1) as pool:

        def change():
            attempted.set()
            if native_change == "metadata":
                Issue.objects.filter(id=bridge.issue.id).update(updated_at=timezone.now())
            else:
                ProjectMember.objects.filter(project=bridge.project, member=bridge.reviewers[1]).update(is_active=False)
            completed.set()

        def at_final(*_):
            tasks.append(pool.submit(worker, change))
            assert attempted.wait(timeout=5)
            # Native row remains locked until this Curve command commits.
            assert not completed.wait(timeout=0.15)
            return True

        bridge.runtime.local_hook = at_final
        result = complete(bridge, operation)
        assert result["status"] == "SUCCEEDED"
        tasks[0].result(timeout=15)
    bridge.runtime.local_hook = None
    assert completed.is_set()
    with pytest.raises((PrdCommandError, PrdCompletionUnavailable)):
        complete(bridge, operation)
    assert ScopedPrdSubject.objects.get(id=subject.id).digest == subject.digest
    assert ScopedPrdDecision.objects.count() == 1


def test_cancel_between_prepare_and_final_commit_is_no_effect(bridge):
    operation = accept(bridge, submission(bridge)).operation
    bridge.runtime.hook = lambda *_: cancel(bridge, operation)
    result = complete(bridge, operation)
    assert result["status"] == "CANCELLED" and not result["effect_applied"]
    assert not DocumentCheckpoint.objects.exists() and not ScopedPrdSubject.objects.exists()


def test_restart_after_running_and_lost_prepare_uses_durable_command(bridge):
    operation = accept(bridge, submission(bridge)).operation
    from plane.curve.scoped_prd_completion import _transition

    with transaction.atomic():
        operation = _transition(bridge.runtime, operation, "QUEUED")
        operation = _transition(bridge.runtime, operation, "RUNNING")
    command_id, digest = operation.id, ScopedPrdAcceptedCommand.objects.get(operation_id=operation.id).request_digest
    result = complete_scoped_prd_operation(workspace_id=bridge.workspace.id, operation_id=command_id)
    assert result["status"] == "SUCCEEDED" and result["effect_applied"]
    operation.refresh_from_db()
    assert ScopedPrdAcceptedCommand.objects.get(operation_id=operation.id).request_digest == digest


def test_fallback_and_normal_completion_share_workspace_first_fence(bridge):
    _, _, operation = submit(bridge)
    barrier = Barrier(2)

    def replay():
        barrier.wait(timeout=10)
        return complete(bridge, operation)

    def denied_guard():
        barrier.wait(timeout=10)
        try:
            complete_scoped_prd_operation(
                workspace_id=bridge.workspace.id, operation_id=operation.id, execution_guard=lambda: False
            )
        except PrdCompletionUnavailable:
            return "denied"
        raise AssertionError("A failed execution guard cannot return a past success")

    with ThreadPoolExecutor(max_workers=2) as pool:
        normal, fallback = pool.submit(worker, replay), pool.submit(worker, denied_guard)
        assert normal.result(timeout=20)["status"] == "SUCCEEDED"
        assert fallback.result(timeout=20) == "denied"
    assert ScopedPrdSubject.objects.count() == 1


def test_association_end_remains_unavailable_during_scoped_submission(bridge):
    operation = accept(bridge, submission(bridge)).operation
    bridge.runtime.hook = lambda *_: assert_end_unavailable(bridge)
    assert complete(bridge, operation)["status"] == "SUCCEEDED"
    bridge.association.refresh_from_db()
    assert bridge.association.state == "ACTIVE" and bridge.association.version == 1


def assert_end_unavailable(bridge):
    response = end(bridge, bridge.association.id)
    assert response.status_code == 503
