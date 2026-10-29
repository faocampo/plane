# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from uuid import uuid4
from django.db import connection
import json

import pytest

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
def recovery_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ITEM_RECOVERY_ENABLED = True


def endpoint(scope, prepared):
    return (
        f"/api/v1/workspaces/{scope.workspace.slug}/curve/products/{scope.product.id}/"
        f"roadmaps/{prepared[0].id}/item-creation-receipts/"
    )


def test_receipt_recovers_exact_pair_without_reexecuting_creation(scope, prepared, material, settings):
    key = str(uuid4())
    created = command(scope, prepared, material, key=key)
    client, _ = session(scope, settings)
    before = counts(scope)
    for _ in range(2):
        response = client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key)
        assert response.status_code == 200, response.data
        assert response.data == {"state": "COMPLETED", "resource_ref": created.resource_ref}
        assert response["Cache-Control"] == "no-store"
    assert counts(scope) == before
    raw = json.dumps(response.data)
    assert material.reference["object_id"] not in raw
    assert material.reference["digest"] not in raw


def test_missing_or_other_actors_receipt_stays_unresolved(scope, prepared, material, settings):
    key = str(uuid4())
    command(scope, prepared, material, key=key)
    client, _ = session(scope, settings)
    assert client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=str(uuid4())).data == {"state": "UNRESOLVED"}
    client.force_login(scope.member)
    response = client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key)
    assert response.status_code == 200, response.data
    assert response.data == {"state": "UNRESOLVED"}


def test_current_membership_rechecked_for_receipt(scope, prepared, material, settings):
    key = str(uuid4())
    command(scope, prepared, material, key=key)
    client, _ = session(scope, settings)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    assert client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key).status_code == 403
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=True)
    response = client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key)
    assert response.status_code == 200, response.data
    assert response.data["state"] == "COMPLETED"


@pytest.mark.parametrize("key", [None, "malformed", "99000000-0000-4000-8000-00000000000A"])
def test_receipt_identifier_must_be_canonical_header(scope, prepared, settings, key):
    client, _ = session(scope, settings)
    headers = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
    assert client.get(endpoint(scope, prepared), **headers).status_code == 422


def test_default_off_and_query_rejected(scope, prepared, settings):
    client, _ = session(scope, settings)
    key = str(uuid4())
    assert client.get(endpoint(scope, prepared) + "?key=" + key, HTTP_IDEMPOTENCY_KEY=key).status_code == 422
    settings.CURVE_ITEM_RECOVERY_ENABLED = False
    assert client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key).status_code == 404


def test_receipt_requires_session_and_cannot_create(scope, prepared, settings):
    client, _ = session(scope, settings)
    assert client.post(endpoint(scope, prepared), {}, format="json").status_code in {403, 405}
    client.logout()
    assert client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=str(uuid4())).status_code in {401, 403}


def test_changed_owner_can_still_read_own_receipt_with_current_membership(scope, prepared, material, settings):
    key = str(uuid4())
    created = command(scope, prepared, material, key=key)
    # Synthetic state transition: the public manager deliberately rejects direct writes.
    with connection.cursor() as cursor:
        cursor.execute("UPDATE curve_roadmap SET owner_user_id=%s WHERE id=%s", [scope.admin.id, prepared[0].id])
    client, _ = session(scope, settings)
    response = client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key)
    assert response.status_code == 200, response.data
    assert response.data["resource_ref"] == created.resource_ref


@pytest.mark.parametrize("resource", ["item", "feature", "milestone", "roadmap"])
def test_current_tombstone_prevents_receipt_projection(scope, prepared, material, settings, resource):
    from django.utils import timezone
    from plane.curve.models import RoadmapItem, Feature, Milestone, Roadmap

    key = str(uuid4())
    created = command(scope, prepared, material, key=key)
    item = RoadmapItem.objects.get(id=created.resource_ref["resource_id"])
    model, identity = {
        "item": (RoadmapItem, item.id),
        "feature": (Feature, item.feature_id),
        "milestone": (Milestone, item.milestone_id),
        "roadmap": (Roadmap, item.roadmap_id),
    }[resource]
    # Model choice comes from the closed mapping above; values remain bound.
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(model._meta.db_table)} "
            "SET tombstoned_at=%s, tombstoned_by=%s::jsonb, tombstone_reason=%s WHERE id=%s",
            [
                timezone.now(),
                json.dumps({"actor_type": "HUMAN", "actor_id": str(scope.owner.id)}),
                "Synthetic deletion",
                identity,
            ],
        )
    client, _ = session(scope, settings)
    response = client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key)
    assert response.status_code == 404, response.data
    assert "resource_ref" not in response.data


def test_corrupt_retained_response_is_not_recovered(scope, prepared, material, settings, monkeypatch):
    from plane.curve import item_recovery_services as recovery

    key = str(uuid4())
    command(scope, prepared, material, key=key)
    actual = recovery._retained_pair

    def corrupt(facts, record):
        record.response_digest = "sha256:" + "0" * 64
        return actual(facts, record)

    monkeypatch.setattr(recovery, "_retained_pair", corrupt)
    client, _ = session(scope, settings)
    assert client.get(endpoint(scope, prepared), HTTP_IDEMPOTENCY_KEY=key).status_code == 404


def test_failed_audit_commit_does_not_publish_receipt(scope, prepared, material, settings):
    from types import SimpleNamespace
    from unittest.mock import patch
    from django.db import connection, IntegrityError
    from plane.curve.item_recovery_services import read_item_creation_receipt
    from plane.curve.models import PolicyDecision, AuditEvent

    key = str(uuid4())
    command(scope, prepared, material, key=key)
    before = (PolicyDecision.objects.count(), AuditEvent.objects.count())
    with patch.object(connection, "commit", side_effect=IntegrityError("synthetic commit failure")):
        with pytest.raises(IntegrityError):
            read_item_creation_receipt(
                request=SimpleNamespace(user=scope.owner, headers={}),
                workspace_slug=scope.workspace.slug,
                product_id=scope.product.id,
                roadmap_id=prepared[0].id,
                command_key=key,
            )
    assert (PolicyDecision.objects.count(), AuditEvent.objects.count()) == before
