# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier

import pytest
from django.db import connections, transaction

from plane.curve.feature_editor_services import FeatureEditorCommandError
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.services import OptimisticConcurrencyError, ReplayResourceUnavailable
from plane.curve.tests.test_feature_editor_commands import command, counts, row
from plane.curve.tests.test_feature_editor_storage_races import wait_for_lock
from plane.curve.tests.test_feature_membership_lifetime import sql
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def run(callback):
    connections.close_all()
    try:
        sql("SET statement_timeout='20s'")
        return callback()
    finally:
        connections.close_all()


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_grants_have_one_effect(scope, same_key):
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait(timeout=10)
        try:
            return command(scope, key="synthetic-race" if same_key else f"synthetic-race-{index}")
        except FeatureEditorCommandError as error:
            assert error.code == "FEATURE_EDITOR_ALREADY_GRANTED"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run, lambda index=index: attempt(index)) for index in range(2)]
        results = [future.result(timeout=30) for future in pending]
    assert counts(scope) == [1, 1, 1, 1]
    if same_key:
        assert results[0].resource_ref == results[1].resource_ref
        assert sorted(result.replayed for result in results) == [False, True]
    else:
        assert sum(result is None for result in results) == 1


def test_concurrent_revoke_has_one_transition(scope):
    granted = command(scope)
    barrier = Barrier(2)

    def attempt(index):
        barrier.wait(timeout=10)
        try:
            command(scope, grant_id=granted.resource_ref["resource_id"], version=1, key=f"synthetic-revoke-{index}")
            return "accepted"
        except OptimisticConcurrencyError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run, lambda index=index: attempt(index)) for index in range(2)]
        assert sorted(future.result(timeout=30) for future in pending) == ["accepted", "stale"]
    assert row(scope, granted)["version"] == 2
    assert counts(scope) == [1, 2, 2, 2]


@pytest.mark.parametrize("restore", [False, True])
def test_waiting_replay_rechecks_target_lifetime(scope, restore):
    command(scope)
    pid = Queue()

    def attempt():
        pid.put(sql("SELECT pg_backend_pid()")[0][0])
        with pytest.raises(ReplayResourceUnavailable if restore else CurvePolicyDenied):
            command(scope)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            membership = WorkspaceMember.objects.select_for_update().get(workspace=scope.workspace, member=scope.member)
            blocker = sql("SELECT pg_backend_pid()")[0][0]
            future = pool.submit(run, attempt)
            waiter = pid.get(timeout=5)
            wait_for_lock(blocker, waiter)
            WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
            if restore:
                WorkspaceMember.objects.filter(id=membership.id).update(is_active=True)
        future.result(timeout=30)
    assert counts(scope) == [1, 1, 1, 1]
