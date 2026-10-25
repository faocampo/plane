# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Product edition conformance at supported API and association boundaries."""

import pytest
from django.db import connection
from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, Product
from plane.curve.tests.test_product_api import _add_member, _client, _create, _product_url, _user, _workspace
from plane.db.models import WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def settings_profile(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha", "beta"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "product-format-test"


@pytest.fixture
def product_context():
    owner = _user("format-owner@example.invalid")
    workspace = _workspace(slug="alpha", owner=owner)
    client = _client(owner)
    response = _create(client)
    assert response.status_code == 201
    return workspace, owner, client, response.json()["id"]


def set_edition(product_id, edition):
    # Deliberate malformed fixture in a disposable test database only.
    with connection.cursor() as cursor:
        cursor.execute("UPDATE curve_product SET schema_version = %s WHERE id = %s", [edition, product_id])
        assert cursor.rowcount == 1


def authoritative_snapshot(product_id):
    return {
        "product": Product.objects.values().get(id=product_id),
        "products": list(Product.objects.order_by("id").values()),
        "events": list(DomainEvent.objects.order_by("id").values()),
        "outbox": list(OutboxEvent.objects.order_by("id").values()),
        "idempotency": list(IdempotencyRecord.objects.order_by("id").values()),
    }


def assert_unavailable(response):
    assert response.status_code == 503
    data = response.json()
    assert data["type"] == "https://curve.example.invalid/problems/curve-product-format-unavailable"
    assert set(data) == {"type", "title", "status", "correlation_id"}
    assert data["title"] == "The Product is temporarily unavailable"


@pytest.mark.parametrize("edition", ["2.0", "invalid", ""])
@pytest.mark.parametrize("detail", [True, False])
def test_reads_reject_unsupported_editions_without_changing_records(product_context, edition, detail):
    _, _, client, product_id = product_context
    set_edition(product_id, edition)
    before = authoritative_snapshot(product_id)
    url = _product_url(product_id) if detail else "/api/v1/workspaces/alpha/curve/products/"
    assert_unavailable(client.get(url))
    assert authoritative_snapshot(product_id) == before
    set_edition(product_id, "1.0")
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("action", ["metadata", "owner", "archive", "restore"])
def test_commands_preserve_all_authoritative_state_and_record_no_effect(product_context, action):
    workspace, _, client, product_id = product_context
    next_owner = _add_member(workspace, email="format-next-owner@example.invalid")
    if action == "restore":
        archived = client.post(
            _product_url(product_id, "archive/"),
            {},
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
            HTTP_IDEMPOTENCY_KEY="format-prepare-archive",
        )
        assert archived.status_code == 200
    version = Product.objects.get(id=product_id).version
    set_edition(product_id, "2.0")
    before = authoritative_snapshot(product_id)
    audits = AuditEvent.objects.count()
    payload = (
        {"name": "Changed"}
        if action == "metadata"
        else {"owner_user_id": str(next_owner.id)}
        if action == "owner"
        else {}
    )
    url = _product_url(product_id, "" if action == "metadata" else action + "/")
    call = client.patch if action == "metadata" else client.post
    response = call(
        url,
        payload,
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v{version}"',
        HTTP_IDEMPOTENCY_KEY="format-command-" + action,
    )
    assert_unavailable(response)
    assert authoritative_snapshot(product_id) == before
    assert AuditEvent.objects.count() == audits + 1
    assert AuditEvent.objects.order_by("-occurred_at").first().outcome == "NO_EFFECT"


def test_creation_replay_preserves_original_receipt(product_context):
    _, _, client, product_id = product_context
    set_edition(product_id, "2.0")
    before = authoritative_snapshot(product_id)
    assert_unavailable(_create(client))
    assert authoritative_snapshot(product_id) == before


@pytest.mark.parametrize("detail", [True, False])
def test_revoked_membership_takes_precedence_over_format_error(product_context, detail):
    workspace, owner, client, product_id = product_context
    set_edition(product_id, "2.0")
    WorkspaceMember.objects.filter(workspace=workspace, member=owner).update(is_active=False)
    response = client.get(_product_url(product_id) if detail else "/api/v1/workspaces/alpha/curve/products/")
    assert response.status_code in (403, 404)
    assert "product-format-unavailable" not in response.content.decode()


@pytest.mark.parametrize("field", ["schema_version", "created_at", "updated_at"])
@pytest.mark.parametrize("create", [True, False])
def test_callers_cannot_override_application_fields(product_context, field, create):
    _, _, client, product_id = product_context
    before = authoritative_snapshot(product_id)
    payload = {"key": "another", "name": "Another", "timezone": "UTC"} if create else {"name": "Changed"}
    payload[field] = "2.0" if field == "schema_version" else "2000-01-01T00:00:00Z"
    if create:
        response = client.post(
            "/api/v1/workspaces/alpha/curve/products/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="format-override-create-" + field,
        )
    else:
        response = client.patch(
            _product_url(product_id),
            payload,
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
            HTTP_IDEMPOTENCY_KEY="format-override-update-" + field,
        )
    assert response.status_code == 422
    assert authoritative_snapshot(product_id) == before


def test_mutation_replay_refuses_unsupported_current_edition(product_context):
    _, _, client, product_id = product_context
    headers = {"HTTP_IF_MATCH": f'"curve-product:{product_id}:v1"', "HTTP_IDEMPOTENCY_KEY": "format-replay-metadata"}
    assert client.patch(_product_url(product_id), {"name": "Changed"}, format="json", **headers).status_code == 200
    set_edition(product_id, "2.0")
    before = authoritative_snapshot(product_id)
    assert_unavailable(client.patch(_product_url(product_id), {"name": "Changed"}, format="json", **headers))
    assert authoritative_snapshot(product_id) == before


def test_aggregate_version_orders_changes_when_application_clock_moves_backward(product_context, monkeypatch):
    from datetime import timedelta

    _, _, client, product_id = product_context
    before = Product.objects.get(id=product_id)
    earlier = before.created_at - timedelta(days=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: earlier)
    response = client.patch(
        _product_url(product_id),
        {"name": "Changed"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="format-clock-rollback",
    )
    assert response.status_code == 200
    after = Product.objects.get(id=product_id)
    assert after.created_at == before.created_at
    assert after.updated_at == earlier < before.updated_at
    assert after.version == before.version + 1
    assert after.schema_version == "1.0"


@pytest.mark.parametrize("action", ["create", "create_replay", "refinement", "resume"])
def test_initiative_associations_reject_unsupported_product_without_effects(product_context, action):
    from plane.curve.models import GateAssignment, Initiative
    from plane.curve.tests import test_initiative_api as helpers

    workspace, owner, client, product_id = product_context
    technical = _add_member(workspace, email="format-technical@example.invalid")
    payload = helpers._payload(Product.objects.get(id=product_id), (owner, technical))
    initiative = None
    if action != "create":
        created = helpers._create(client, payload)
        assert created.status_code == 201
        initiative = Initiative.objects.get(id=created.json()["id"])
    if action == "resume":
        accepted = helpers._mutate(client, initiative, "accept-refinement/", {}, idem="format-align-key-0001")
        assert accepted.status_code == 200, accepted.json()
        initiative.refresh_from_db()
        assert (
            helpers._mutate(
                client, initiative, "pause/", {"reason": "Synthetic pause"}, idem="format-pause-key-0001"
            ).status_code
            == 200
        )
        initiative.refresh_from_db()
    set_edition(product_id, "2.0")
    before = authoritative_snapshot(product_id)
    initiatives = list(Initiative.objects.order_by("id").values())
    assignments = list(GateAssignment.objects.order_by("id").values())
    audits = AuditEvent.objects.count()
    if action in ("create", "create_replay"):
        response = helpers._create(client, payload)
    elif action == "refinement":
        response = helpers._mutate(client, initiative, "accept-refinement/", {}, idem="format-refine-denied")
    else:
        response = helpers._mutate(
            client, initiative, "resume/", {"reason": "Synthetic resume"}, idem="format-resume-denied"
        )
    assert_unavailable(response)
    assert authoritative_snapshot(product_id) == before
    assert list(Initiative.objects.order_by("id").values()) == initiatives
    assert list(GateAssignment.objects.order_by("id").values()) == assignments
    assert AuditEvent.objects.count() == audits + 1
    assert AuditEvent.objects.order_by("-occurred_at").first().outcome == "NO_EFFECT"
