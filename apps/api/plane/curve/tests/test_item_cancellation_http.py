# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, IntegrityError
import pytest

from plane.curve.item_cancellation_services import cancel_item_creation
from plane.curve.item_cancellation_results import cancellation_identity
from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision
from plane.curve.services import IdempotencyConflict
from plane.curve.tests.test_feature_http import session
from plane.curve.tests.test_item_creation_commands import (
    scope as scope_fixture,
    prepared as prepared_fixture,
    material as material_fixture,
    command,
    counts,
)
from plane.db.models import WorkspaceMember

scope = scope_fixture
prepared = prepared_fixture
material = material_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def cancellation_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ITEM_CANCELLATION_ENABLED = True


def endpoint(scope, prepared):
    return (
        f"/api/v1/workspaces/{scope.workspace.slug}/curve/products/{scope.product.id}/"
        f"roadmaps/{prepared[0].id}/item-creation-receipts/cancel/"
    )


def cancel(scope, prepared, key):
    return cancel_item_creation(
        request=SimpleNamespace(user=scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        roadmap_id=prepared[0].id,
        command_key=key,
    )


def post(client, token, scope, prepared, key, data=None):
    return client.post(
        endpoint(scope, prepared),
        {} if data is None else data,
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
        HTTP_X_CSRFTOKEN=token,
    )


def test_cancel_first_prevents_delayed_creation_and_repeats_without_effects(scope, prepared, material, settings):
    key = str(uuid4())
    before = counts(scope)
    client, token = session(scope, settings)
    response = post(client, token, scope, prepared, key)
    assert response.status_code == 200, response.data
    assert response.data == {"state": "CANCELLED"}
    assert response["Cache-Control"] == "no-store"
    after = counts(scope)
    assert after[:3] == before[:3]
    for _ in range(2):
        assert post(client, token, scope, prepared, key).data == {"state": "CANCELLED"}
        with pytest.raises(IdempotencyConflict):
            command(scope, prepared, material, key=key)
    assert counts(scope) == after
    assert (
        DomainEvent.objects.filter(workspace_id=scope.workspace.id, event_type="curve.item_creation.cancelled").count()
        == 1
    )


def test_creation_first_returns_original_pair_without_cancelling_it(scope, prepared, material, settings):
    key = str(uuid4())
    created = command(scope, prepared, material, key=key)
    before = counts(scope)
    client, token = session(scope, settings)
    for _ in range(2):
        response = post(client, token, scope, prepared, key)
        assert response.status_code == 200, response.data
        assert response.data == {"state": "COMPLETED", "resource_ref": created.resource_ref}
    assert counts(scope) == before
    assert not DomainEvent.objects.filter(
        workspace_id=scope.workspace.id, event_type="curve.item_creation.cancelled"
    ).exists()


def test_session_csrf_closed_body_canonical_key_and_default_off(scope, prepared, settings):
    client, token = session(scope, settings)
    key = str(uuid4())
    assert post(client, "", scope, prepared, key).status_code == 403
    assert post(client, token, scope, prepared, "invalid").status_code == 422
    assert post(client, token, scope, prepared, key, {"new_key": key}).status_code == 422
    assert client.get(endpoint(scope, prepared)).status_code == 405
    settings.CURVE_ITEM_CANCELLATION_ENABLED = False
    assert post(client, token, scope, prepared, key).status_code == 404
    settings.CURVE_ITEM_CANCELLATION_ENABLED = True
    client.logout()
    assert post(client, token, scope, prepared, key).status_code in {401, 403}


def test_current_access_required_but_old_owner_can_settle_own_attempt(scope, prepared, settings):
    key = str(uuid4())
    client, token = session(scope, settings)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    assert post(client, token, scope, prepared, key).status_code == 403
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=True)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE curve_roadmap SET owner_user_id=%s WHERE id=%s", [scope.admin.id, prepared[0].id])
    response = post(client, token, scope, prepared, key)
    assert response.status_code == 200, response.data
    assert response.data == {"state": "CANCELLED"}


@pytest.mark.parametrize("state", ["IN_PROGRESS", "RECONCILIATION_REQUIRED"])
def test_existing_unfinished_request_identity_is_never_rewritten(scope, prepared, state):
    from django.utils import timezone
    from datetime import timedelta

    key = str(uuid4())
    identity = cancellation_identity(
        workspace_id=scope.workspace.id,
        product_id=scope.product.id,
        roadmap_id=prepared[0].id,
        actor_id=scope.owner.id,
        command_key=key,
    )
    identity["request_digest"] = "sha256:" + "1" * 64
    record = IdempotencyRecord.objects.create(
        workspace_id=scope.workspace.id, **identity, state=state, expires_at=timezone.now() + timedelta(days=1)
    )
    assert cancel(scope, prepared, key) == {"state": "UNRESOLVED"}
    record.refresh_from_db()
    assert record.state == state and record.request_digest == identity["request_digest"]
    assert record.response_resource_ref is None


def test_failed_physical_commit_rolls_back_marker_event_outbox_and_audit(scope, prepared):
    models = [IdempotencyRecord, DomainEvent, OutboxEvent, PolicyDecision, AuditEvent]
    before = [model.objects.count() for model in models]
    with patch.object(connection, "commit", side_effect=IntegrityError("synthetic commit failure")):
        with pytest.raises(IntegrityError):
            cancel(scope, prepared, str(uuid4()))
    assert [model.objects.count() for model in models] == before


@pytest.mark.parametrize("winner", ["creation", "cancellation"])
def test_cancellation_and_creation_share_lock_until_commit(scope, prepared, material, monkeypatch, winner):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from plane.curve import item_creation_services, item_cancellation_services
    from plane.curve.tests.test_feature_editor_command_races import run
    from plane.curve.tests.test_feature_editor_storage_races import wait_for_lock
    from plane.curve.tests.test_feature_membership_lifetime import sql

    key = str(uuid4())
    first_pid, second_pid = Queue(), Queue()
    release = Event()
    module = item_creation_services if winner == "creation" else item_cancellation_services
    hook = "_append_item_event" if winner == "creation" else "_append_audit_event"
    original = getattr(module, hook)

    def hold_first(*args, **kwargs):
        original(*args, **kwargs)
        first_pid.put(sql("SELECT pg_backend_pid()")[0][0])
        assert release.wait(timeout=30)

    monkeypatch.setattr(module, hook, hold_first)

    def create_call():
        return command(scope, prepared, material, key=key)

    def cancel_call():
        return cancel(scope, prepared, key)

    first_call, second_call = (create_call, cancel_call) if winner == "creation" else (cancel_call, create_call)

    def competing():
        second_pid.put(sql("SELECT pg_backend_pid()")[0][0])
        return second_call()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, first_call)
        blocker = first_pid.get(timeout=15)
        second = pool.submit(run, competing)
        try:
            wait_for_lock(blocker, second_pid.get(timeout=15))
            assert not second.done()
        finally:
            release.set()
        result = first.result(timeout=30)
        if winner == "creation":
            assert second.result(timeout=30) == {"state": "COMPLETED", "resource_ref": result.resource_ref}
        else:
            assert result == {"state": "CANCELLED"}
            with pytest.raises(IdempotencyConflict):
                second.result(timeout=30)


def test_outbox_failure_rolls_back_cancellation_and_allows_original_create(scope, prepared, material, monkeypatch):
    key = str(uuid4())
    before = counts(scope)
    with monkeypatch.context() as patcher:

        def fail(*args, **kwargs):
            raise IntegrityError("synthetic outbox failure")

        patcher.setattr(OutboxEvent.objects, "create", fail)
        with pytest.raises(IntegrityError):
            cancel(scope, prepared, key)
    assert counts(scope) == before
    assert command(scope, prepared, material, key=key).response_status == 201


def test_other_actor_cancellation_cannot_change_original_receipt(scope, prepared, material, settings):
    key = str(uuid4())
    created = command(scope, prepared, material, key=key)
    client, token = session(scope, settings)
    client.force_login(scope.member)
    response = post(client, token, scope, prepared, key)
    assert response.status_code == 200, response.data
    assert response.data == {"state": "CANCELLED"}
    assert command(scope, prepared, material, key=key).resource_ref == created.resource_ref
