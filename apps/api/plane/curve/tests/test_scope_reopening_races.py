# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Both serialization orders for reopening versus previously accepted Gate 1 work."""
# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import uuid

import pytest
from django.db import close_old_connections, connection, transaction

from plane.curve.models import DocumentCheckpoint, PrdReviewDecision
from plane.curve.prd_commands import PrdCommandError
from plane.curve.prd_completion import PrdCompletionUnavailable
from plane.curve.scope_reopening_models import ScopeReopening
from plane.curve.tests.test_scope_reopening_services import (  # noqa: F401
    DENIED,
    accept,
    adopt,
    bridge,
    complete,
    configuration,
    context,
    reopen,
    reopening,
    replacement,
    review_command,
    submission,
    submit,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def worker(call):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout='8s'")
        return call()
    finally:
        close_old_connections()


def pending(bridge, action):
    if action == "submit":
        command = submission(bridge)
    else:
        subject, _, _ = submit(bridge)
        command = review_command(bridge, subject)
    return accept(bridge, command).operation


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_reopening_commit_first_prevents_accepted_operation_domain_effect(reopening, action):
    operation = pending(reopening, action)
    attempted, finished = Event(), Event()
    before = (DocumentCheckpoint.objects.count(), PrdReviewDecision.objects.count())

    def apply():
        attempted.set()
        try:
            return complete(reopening, operation)
        except (PrdCommandError, PrdCompletionUnavailable):
            return None
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            result = reopen(reopening)
            task = pool.submit(worker, apply)
            assert attempted.wait(timeout=5)
            assert not finished.wait(timeout=0.15)
        outcome = task.result(timeout=25)
    if outcome is not None:
        assert outcome["status"] in {"FAILED", "CANCELLED"} and not outcome["effect_applied"]
    assert (DocumentCheckpoint.objects.count(), PrdReviewDecision.objects.count()) == before
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == "ALIGNING"
    assert reopening.initiative.pending_scope_reopening_id == uuid.UUID(result.data["id"])
    assert ScopeReopening.objects.count() == 1


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_operation_commit_first_rejects_stale_reopening_then_allows_fresh_retry(reopening, action):
    operation = pending(reopening, action)
    version, payload = reopening.initiative.version, replacement(reopening)
    attempted, finished = Event(), Event()
    tasks = []

    def stale_reopening():
        attempted.set()
        try:
            with pytest.raises(DENIED):
                reopen(reopening, version=version, payload=payload)
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:

        def final_fence(*_):
            tasks.append(pool.submit(worker, stale_reopening))
            assert attempted.wait(timeout=5)
            assert not finished.wait(timeout=0.15)
            return True

        reopening.runtime.local_hook = final_fence
        outcome = complete(reopening, operation)
        reopening.runtime.local_hook = None
        assert outcome["status"] == "SUCCEEDED" and outcome["effect_applied"]
        tasks[0].result(timeout=25)
    assert not ScopeReopening.objects.exists()
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == ("PRD_REVIEW" if action == "submit" else "PLANNING")
    result = reopen(reopening, key="fresh-reopen-after-completion")
    assert result.response_status == 201
    assert result.data["previous_initiative_version"] > version
    assert result.data["approval_invalidated"] is (action == "approve")
