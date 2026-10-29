# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import pytest
from django.db import transaction

from plane.curve.tests.test_feature_editor_command_races import run
from plane.curve.tests.test_feature_editor_storage_races import wait_for_lock
from plane.curve.tests.test_feature_membership_lifetime import sql
from plane.db.models import User, WorkspaceMember

from plane.curve.tests.test_item_creation_facts import (
    prepared as prepared_fixture,
    resolve,
    scope as scope_fixture,
)

prepared = prepared_fixture
scope = scope_fixture

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("target", ["membership", "human"])
def test_observed_reviewer_liveness_is_locked_until_transaction_finishes(scope, prepared, target):
    observed = Queue()

    def revoke():
        observed.put(sql("SELECT pg_backend_pid()")[0][0])
        if target == "membership":
            return WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member).update(
                is_active=False
            )
        return User.objects.filter(id=scope.member.id).update(is_active=False)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            before = dict(resolve(scope, prepared).reviewers)["PRD_APPROVAL"]
            assert before.active_human and before.active_member
            blocker = sql("SELECT pg_backend_pid()")[0][0]
            future = pool.submit(run, revoke)
            wait_for_lock(blocker, observed.get(timeout=5))
            assert not future.done()
        assert future.result(timeout=30) == 1
    with transaction.atomic():
        after = dict(resolve(scope, prepared).reviewers)["PRD_APPROVAL"]
        if target == "membership":
            assert not after.active_member and after.active_human
        else:
            assert after.active_member and not after.active_human
