# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from pathlib import Path

import pytest
from django.db import transaction
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIClient

from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    IdempotencyRecord,
    OutboxEvent,
    PolicyDecision,
    Product,
    ProductState,
)
from plane.curve.product_guards import assert_product_accepts_new_initiative, override_product_initiative_guard
from plane.curve.views import CurveProductAPIView
from plane.db.models import User, Workspace, WorkspaceMember
import plane.curve.product_services as product_services


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def _curve_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha", "beta"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-product-api-test"


def _user(email):
    return User.objects.create(email=email, username=email)


def _workspace(*, slug, owner, role=20):
    workspace = Workspace.objects.create(name=slug.title(), slug=slug, owner=owner)
    WorkspaceMember.objects.create(
        workspace=workspace,
        member=owner,
        role=role,
        is_active=True,
    )
    return workspace


def _add_member(workspace, *, email, role=15, active=True):
    user = _user(email)
    WorkspaceMember.objects.create(
        workspace=workspace,
        member=user,
        role=role,
        is_active=active,
    )
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture(scope="module")
def product_schema_contracts():
    schema_directory = Path(__file__).parents[1] / "contracts" / "schemas"
    schemas = {path.name: json.loads(path.read_text()) for path in schema_directory.glob("*.schema.json")}
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas.values())
    return {
        name: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for name, schema in schemas.items()
    }


def _create(client, *, slug="alpha", key="mobile-platform", idem="product-create-key-0001"):
    return client.post(
        f"/api/v1/workspaces/{slug}/curve/products/",
        {
            "key": key,
            "name": "Mobile Platform",
            "description": "Synthetic INTERNAL test Product",
            "timezone": "America/Argentina/Buenos_Aires",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem,
    )


def _product_url(product_id, suffix=""):
    return f"/api/v1/workspaces/alpha/curve/products/{product_id}/{suffix}"


def test_admin_create_is_atomic_and_replays_without_duplicate_product_or_event(product_schema_contracts):
    owner = _user("product-admin@example.com")
    workspace = _workspace(slug="alpha", owner=owner)
    client = _client(owner)

    created = _create(client)
    replay = _create(client)

    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    assert created["ETag"] == f'"curve-product:{created.json()["id"]}:v1"'
    assert created["Location"].endswith(f"{created.json()['id']}/")
    assert created.json()["workspace_id"] == str(workspace.id)
    assert created.json()["owner"] == {"actor_type": "HUMAN", "actor_id": str(owner.id)}
    assert Product.objects.filter(workspace_id=workspace.id).count() == 1
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_type="PRODUCT").count() == 1
    assert OutboxEvent.objects.filter(workspace_id=workspace.id, destination="CURVE_PRODUCT_LOCAL_V1").count() == 1
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 1
    assert PolicyDecision.objects.filter(workspace_id=workspace.id, policy_key="CURVE_PRODUCT_POLICY").count() == 2
    assert AuditEvent.objects.filter(workspace_id=workspace.id, target_type="PRODUCT").count() == 2
    product_schema_contracts["product.schema.json"].validate(created.json())
    product_event = DomainEvent.objects.get(workspace_id=workspace.id, aggregate_type="PRODUCT")
    product_schema_contracts["product-event-v1.schema.json"].validate(product_event.payload)


def test_create_requires_admin_and_rejects_invalid_timezone_without_product_effects():
    admin = _user("workspace-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    member = _add_member(workspace, email="regular-member@example.com")

    denied = _create(_client(member), idem="member-create-key-0001")
    invalid = _client(admin).post(
        "/api/v1/workspaces/alpha/curve/products/",
        {"key": "valid-key", "name": "Valid", "timezone": "UTC+03:00"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="invalid-timezone-key-001",
    )

    assert denied.status_code == 403
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["field"] == "timezone"
    assert Product.objects.filter(workspace_id=workspace.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_type="PRODUCT").count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace.id, destination="CURVE_PRODUCT_LOCAL_V1").count() == 0


def test_metadata_update_is_owner_authorized_versioned_and_timezone_is_prospective():
    admin = _user("metadata-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    product_id = _create(_client(admin), idem="metadata-create-key-001").json()["id"]
    client = _client(admin)
    url = _product_url(product_id)

    updated = client.patch(
        url,
        {"name": "Mobile Runtime", "timezone": "UTC"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="metadata-update-key-001",
    )
    replay = client.patch(
        url,
        {"name": "Mobile Runtime", "timezone": "UTC"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="metadata-update-key-001",
    )
    stale = client.patch(
        url,
        {"name": "Stale Name"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="metadata-stale-key-0001",
    )

    assert updated.status_code == replay.status_code == 200
    assert updated.json()["version"] == replay.json()["version"] == 2
    assert updated["ETag"] == f'"curve-product:{product_id}:v2"'
    assert stale.status_code == 412
    events = list(DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_id=product_id).order_by("sequence"))
    assert [event.sequence for event in events] == [1, 2]
    assert events[1].payload["previous_timezone"] == "America/Argentina/Buenos_Aires"
    assert events[1].payload["current_timezone"] == "UTC"
    assert events[0].payload["current_timezone"] == "America/Argentina/Buenos_Aires"


def test_owner_reassignment_requires_active_workspace_member_and_grants_metadata_authority():
    admin = _user("owner-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    next_owner = _add_member(workspace, email="next-owner@example.com")
    inactive = _add_member(workspace, email="inactive-owner@example.com", active=False)
    admin_client = _client(admin)
    product_id = _create(admin_client, idem="owner-create-key-00001").json()["id"]
    owner_url = _product_url(product_id, "owner/")

    rejected = admin_client.post(
        owner_url,
        {"owner_user_id": str(inactive.id)},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="inactive-owner-key-0001",
    )
    reassigned = admin_client.post(
        owner_url,
        {"owner_user_id": str(next_owner.id)},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="active-owner-key-000001",
    )
    owner_update = _client(next_owner).patch(
        _product_url(product_id),
        {"description": "Owned by the active developer"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v2"',
        HTTP_IDEMPOTENCY_KEY="owner-metadata-key-0001",
    )

    assert rejected.status_code == 409
    assert reassigned.status_code == 200
    assert reassigned.json()["owner"]["actor_id"] == str(next_owner.id)
    assert owner_update.status_code == 200
    assert owner_update.json()["version"] == 3


def test_archival_guard_blocks_non_terminal_then_archive_and_restore_preserve_history():
    admin = _user("lifecycle-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    client = _client(admin)
    product_id = _create(client, idem="lifecycle-create-key-01").json()["id"]
    archive_url = _product_url(product_id, "archive/")

    with override_product_initiative_guard(lambda **_: ["FAILED"]):
        blocked = client.post(
            archive_url,
            {},
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
            HTTP_IDEMPOTENCY_KEY="blocked-archive-key-001",
        )
    with override_product_initiative_guard(lambda **_: ["CANCELLED", "READY_FOR_REPOSITORY_REVIEW"]):
        archived = client.post(
            archive_url,
            {},
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
            HTTP_IDEMPOTENCY_KEY="allowed-archive-key-001",
        )
    historical = client.get(_product_url(product_id))
    restored = client.post(
        _product_url(product_id, "restore/"),
        {},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v2"',
        HTTP_IDEMPOTENCY_KEY="restore-product-key-0001",
    )

    assert blocked.status_code == 409
    assert archived.status_code == historical.status_code == restored.status_code == 200
    assert archived.json()["state"] == historical.json()["state"] == ProductState.ARCHIVED
    assert archived.json()["archived_at"] is not None
    assert restored.json()["state"] == ProductState.ACTIVE
    assert restored.json()["archived_at"] is None
    with transaction.atomic():
        assert (
            str(
                assert_product_accepts_new_initiative(
                    workspace_id=workspace.id,
                    product_id=product_id,
                ).id
            )
            == restored.json()["id"]
        )
    assert Product.objects.get(id=product_id).key == "mobile-platform"
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_id=product_id).count() == 3


def test_listing_defaults_active_filters_archived_and_cross_workspace_id_is_not_disclosed():
    alpha_admin = _user("alpha-product-admin@example.com")
    beta_admin = _user("beta-product-admin@example.com")
    _workspace(slug="alpha", owner=alpha_admin)
    beta = _workspace(slug="beta", owner=beta_admin)
    alpha_client = _client(alpha_admin)
    active_id = _create(alpha_client, key="active", idem="active-product-key-0001").json()["id"]
    archived_id = _create(alpha_client, key="archived", idem="archived-product-key-01").json()["id"]
    alpha_client.post(
        _product_url(archived_id, "archive/"),
        {},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{archived_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="archive-list-key-00001",
    )
    beta_id = _create(_client(beta_admin), slug="beta", key="beta-product", idem="beta-product-key-000001").json()["id"]

    active = alpha_client.get("/api/v1/workspaces/alpha/curve/products/")
    archived = alpha_client.get("/api/v1/workspaces/alpha/curve/products/?state=ARCHIVED")
    hidden = alpha_client.get(f"/api/v1/workspaces/beta/curve/products/{beta_id}/")

    assert [item["id"] for item in active.json()["results"]] == [active_id]
    assert [item["id"] for item in archived.json()["results"]] == [archived_id]
    assert hidden.status_code == 403
    assert beta_id not in json.dumps(hidden.json())
    assert Product.objects.filter(workspace_id=beta.id).count() == 1


@pytest.mark.parametrize(
    "invalid_key",
    ["UPPERCASE", "has_underscore", "-leading", "", "a" * 51],
)
def test_product_create_rejects_every_invalid_key_shape(invalid_key):
    admin = _user(f"invalid-{len(invalid_key)}-{abs(hash(invalid_key))}@example.com")
    workspace = _workspace(slug="alpha", owner=admin)

    response = _create(
        _client(admin),
        key=invalid_key,
        idem=f"invalid-product-key-{abs(hash(invalid_key))}",
    )

    assert response.status_code == 422
    assert Product.objects.filter(workspace_id=workspace.id).count() == 0


def test_metadata_rejects_identity_and_lifecycle_fields_without_history_change():
    admin = _user("immutable-fields-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    client = _client(admin)
    product_id = _create(client, idem="immutable-create-key-001").json()["id"]

    response = client.patch(
        _product_url(product_id),
        {"key": "changed", "state": "ARCHIVED"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="immutable-update-key-01",
    )

    assert response.status_code == 422
    assert Product.objects.get(workspace_id=workspace.id, id=product_id).version == 1
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_id=product_id).count() == 1


def test_non_owner_member_cannot_update_product_metadata():
    admin = _user("non-owner-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    member = _add_member(workspace, email="non-owner-member@example.com")
    product_id = _create(_client(admin), idem="non-owner-create-key-01").json()["id"]

    response = _client(member).patch(
        _product_url(product_id),
        {"name": "Unauthorized"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="non-owner-update-key-01",
    )

    assert response.status_code == 403
    assert Product.objects.get(id=product_id).version == 1
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_id=product_id).count() == 1


def test_archive_fails_closed_when_initiative_guard_is_unavailable():
    admin = _user("guard-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    client = _client(admin)
    product_id = _create(client, idem="guard-create-key-00001").json()["id"]

    with override_product_initiative_guard(None):
        response = client.post(
            _product_url(product_id, "archive/"),
            {},
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
            HTTP_IDEMPOTENCY_KEY="guard-archive-key-0001",
        )

    assert response.status_code == 409
    assert response.json()["type"].endswith("product-initiative-guard-unavailable")
    assert Product.objects.get(id=product_id).state == ProductState.ACTIVE
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_id=product_id).count() == 1


def test_reused_idempotency_key_with_another_request_digest_has_no_second_effect():
    admin = _user("idempotency-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    client = _client(admin)

    created = _create(client, key="first", idem="same-product-create-key")
    conflict = _create(client, key="second", idem="same-product-create-key")

    assert created.status_code == 201
    assert conflict.status_code == 409
    assert Product.objects.filter(workspace_id=workspace.id).count() == 1
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_type="PRODUCT").count() == 1


def test_cross_workspace_product_mutation_is_indistinguishable_from_absent():
    alpha_admin = _user("cross-alpha-admin@example.com")
    beta_admin = _user("cross-beta-admin@example.com")
    alpha = _workspace(slug="alpha", owner=alpha_admin)
    beta = _workspace(slug="beta", owner=beta_admin)
    WorkspaceMember.objects.create(workspace=beta, member=alpha_admin, role=20, is_active=True)
    product_id = _create(_client(alpha_admin), idem="cross-create-key-00001").json()["id"]
    client = _client(alpha_admin)

    cross = client.patch(
        f"/api/v1/workspaces/beta/curve/products/{product_id}/",
        {"name": "Cross workspace"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="cross-update-key-00001",
    )
    absent_id = "00000000-0000-4000-8000-000000000099"
    absent = client.patch(
        f"/api/v1/workspaces/beta/curve/products/{absent_id}/",
        {"name": "Absent"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{absent_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="absent-update-key-0001",
    )

    assert cross.status_code == absent.status_code == 404
    assert cross.json()["type"] == absent.json()["type"]
    assert product_id not in json.dumps(cross.json())
    assert Product.objects.get(workspace_id=alpha.id, id=product_id).version == 1


def test_database_failure_after_product_write_rolls_back_every_success_effect(monkeypatch):
    admin = _user("rollback-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)

    def fail_event_append(**_kwargs):
        raise RuntimeError("synthetic event append failure")

    monkeypatch.setattr(product_services, "_append_product_event", fail_event_append)
    response = _create(_client(admin), idem="rollback-create-key-001")

    assert response.status_code == 500
    assert Product.objects.filter(workspace_id=workspace.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_type="PRODUCT").count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace.id, destination="CURVE_PRODUCT_LOCAL_V1").count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 0
    assert AuditEvent.objects.filter(workspace_id=workspace.id, outcome="SUCCEEDED").count() == 0


def test_product_api_has_session_only_human_entry_and_no_delete_route():
    admin = _user("retirement-admin@example.com")
    _workspace(slug="alpha", owner=admin)
    client = _client(admin)
    product_id = _create(client, idem="retirement-create-key-01").json()["id"]

    response = client.delete(_product_url(product_id))

    assert CurveProductAPIView.authentication_classes == [SessionAuthentication]
    assert response.status_code == 405
