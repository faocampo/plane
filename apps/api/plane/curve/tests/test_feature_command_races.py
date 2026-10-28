# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier

import pytest
from django.db import transaction

from plane.curve.models import Feature
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.services import OptimisticConcurrencyError
from plane.curve.tests.test_feature_commands import command, counts
from plane.curve.tests.test_feature_editor_commands import command as editor_command
from plane.curve.tests.test_feature_editor_command_races import run
from plane.curve.tests.test_feature_editor_storage_races import wait_for_lock
from plane.curve.tests.test_feature_membership_lifetime import sql
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import Workspace, WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_concurrent_create_retry_has_one_committed_effect(scope):
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        return command(scope)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run, attempt) for _ in range(2)]
        results = [future.result(timeout=30) for future in pending]
    assert results[0].resource_ref == results[1].resource_ref
    assert sorted(result.replayed for result in results) == [False, True]
    assert counts(scope) == [1, 1, 1, 1]


def test_concurrent_updates_preserve_one_version_winner(scope):
    created = command(scope)
    identity = created.resource_ref["resource_id"]
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait(timeout=10)
        try:
            command(scope, feature=identity, version=1, key=f"synthetic-race-{index}", name=f"Candidate {index}")
            return "accepted", index
        except OptimisticConcurrencyError:
            return "stale", index

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run, lambda index=index: attempt(index)) for index in range(2)]
        results = [future.result(timeout=30) for future in pending]
    assert sorted(status for status, _ in results) == ["accepted", "stale"]
    winner = next(index for status, index in results if status == "accepted")
    row = Feature.objects.get(id=identity)
    assert row.version == 2 and row.name == f"Candidate {winner}"
    assert counts(scope) == [1, 2, 2, 2]


@pytest.mark.parametrize("restore", [False, True])
def test_waiting_update_rechecks_membership_after_committed_loss(scope, restore):
    editor_command(scope)
    created = command(scope, user=scope.member)
    pid = Queue()
    before = counts(scope)

    def attempt():
        pid.put(sql("SELECT pg_backend_pid()")[0][0])
        with pytest.raises(CurvePolicyDenied):
            command(
                scope,
                user=scope.member,
                feature=created.resource_ref["resource_id"],
                version=1,
                key="synthetic-waiting-update",
                name="Must not commit",
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            WorkspaceMember.objects.select_for_update().get(workspace=scope.workspace, member=scope.member)
            blocker = sql("SELECT pg_backend_pid()")[0][0]
            future = pool.submit(run, attempt)
            wait_for_lock(blocker, pid.get(timeout=5))
            members = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
            members.update(is_active=False)
            if restore:
                members.update(is_active=True)
        future.result(timeout=30)
    assert counts(scope) == before
    assert Feature.objects.get(id=created.resource_ref["resource_id"]).version == 1


def test_waiting_retry_rechecks_editor_revocation(scope):
    grant = editor_command(scope)
    command(scope, user=scope.member)
    pid = Queue()

    def attempt():
        pid.put(sql("SELECT pg_backend_pid()")[0][0])
        with pytest.raises(CurvePolicyDenied):
            command(scope, user=scope.member)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Workspace.objects.select_for_update(no_key=True).get(id=scope.workspace.id)
            editor_command(scope, grant_id=grant.resource_ref["resource_id"], version=1, key="synthetic-revoke")
            before = counts(scope)
            blocker = sql("SELECT pg_backend_pid()")[0][0]
            future = pool.submit(run, attempt)
            wait_for_lock(blocker, pid.get(timeout=5))
        future.result(timeout=30)
    assert counts(scope) == before
