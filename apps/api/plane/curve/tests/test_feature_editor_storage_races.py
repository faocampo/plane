# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real PostgreSQL lock waits for duplicate grants and membership-loss races."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier
from time import monotonic, sleep

import pytest
from django.db import DatabaseError, connections, transaction

from plane.curve.tests.test_feature_editor_grant_storage import scope as grant_scope, grant, revoke, rows
from plane.curve.tests.test_feature_membership_lifetime import membership as membership_fixture, sql, generation
from plane.db.models import WorkspaceMember

scope = grant_scope
membership = membership_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def run_connection(callback):
    connections.close_all()
    try:
        with transaction.atomic():
            sql("SET LOCAL lock_timeout='10s'")
            return "accepted", callback()
    except DatabaseError as error:
        return "rejected", str(error)
    finally:
        connections.close_all()


def wait_for_lock(blocker, waiter):
    deadline = monotonic() + 8
    while monotonic() < deadline:
        if sql("SELECT %s = ANY(pg_blocking_pids(%s))", [blocker, waiter])[0][0]:
            return
        sleep(0.01)
    pytest.fail("The contender never reached the expected PostgreSQL row lock")


def test_concurrent_duplicate_grants_commit_one_record(scope):
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        return grant(scope)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run_connection, attempt) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in pending]
    assert sorted(result[0] for result in outcomes) == ["accepted", "rejected"]
    assert "curve_feature_editor_active_uq" in next(value for status, value in outcomes if status == "rejected")
    assert len(rows()) == 1


@pytest.mark.parametrize("restore", [False, True])
def test_waiting_grant_rechecks_membership_and_generation_after_lock(scope, restore):
    pid = Queue()

    def attempt():
        pid.put(sql("SELECT pg_backend_pid()")[0][0])
        return grant(scope, membership_generation=0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            WorkspaceMember.objects.select_for_update().get(id=scope.membership.id)
            blocker = sql("SELECT pg_backend_pid()")[0][0]
            future = pool.submit(run_connection, attempt)
            waiter = pid.get(timeout=5)
            wait_for_lock(blocker, waiter)
            WorkspaceMember.objects.filter(id=scope.membership.id).update(is_active=False)
            if restore:
                WorkspaceMember.objects.filter(id=scope.membership.id).update(is_active=True)
        status, reason = future.result(timeout=15)
    assert status == "rejected"
    assert ("MEMBERSHIP_STALE" if restore else "MEMBERSHIP_UNAVAILABLE") in reason
    assert generation(scope.membership) == 1
    assert rows() == []


def test_concurrent_revocation_retains_exactly_one_final_transition(scope):
    grant_id = grant(scope)
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=10)
        revoke(scope, grant_id)
        return grant_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run_connection, attempt) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in pending]
    assert sorted(result[0] for result in outcomes) == ["accepted", "rejected"]
    assert "GRANT_IMMUTABLE" in next(value for status, value in outcomes if status == "rejected")
    assert len(rows()) == 1 and rows()[0][2] is not None
