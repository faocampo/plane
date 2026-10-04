# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real-DB read-only discovery, current authority, redaction and race fences."""
# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from types import SimpleNamespace
import json
import uuid

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIClient

from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    IdempotencyRecord,
    OutboxEvent,
    PolicyDecision,
    Product,
    ProjectAssociation,
)
from plane.curve.project_association_read import POLICY_EDITION, SCHEMA_VERSION, read_project_association_preconditions
from plane.curve.project_association_read_views import CurveProjectAssociationPreconditionsEndpoint
from plane.curve.tests.test_project_association_api import (  # noqa: F401
    INSTALLATION,
    client,
    configuration,
    context,
    create,
    end,
)
from plane.db.models import Project, ProjectMember, Workspace, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
FIELDS = {
    "schema_version",
    "policy_edition",
    "workspace_id",
    "product_id",
    "product_version",
    "provider_installation_id",
    "source_project_id",
    "availability",
    "association_id",
    "observed_at",
}


def read(context, **kwargs):
    return read_project_association_preconditions(
        request=kwargs.get("request", SimpleNamespace(user=context.user)),
        workspace_slug=kwargs.get("slug", context.workspace.slug),
        product_id=kwargs.get("product_id", context.product.id),
        source_project_id=kwargs.get("project_id", str(context.project.id)),
    )


def http_read(context, *, client_=None, product_id=None, slug=None, query=None):
    return (client_ or client(context.user)).get(
        f"/api/v1/workspaces/{slug or context.workspace.slug}/curve/products/"
        f"{product_id or context.product.id}/project-association-preconditions/"
        + (query if query is not None else f"?source_project_id={context.project.id}"),
        HTTP_X_ROLE="ADMIN",
        HTTP_X_PROJECT_ACCESS="ALLOW",
    )


def counts():
    return {
        m._meta.db_table: m.objects.count()
        for m in (AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision, ProjectAssociation)
    }


def test_exact_available_read_has_server_pins_and_zero_side_effects(context):
    before = counts()
    native = Project.objects.filter(id=context.project.id).values().get()
    response = http_read(context)
    assert response.status_code == 200, response.data
    assert set(response.data) == FIELDS
    assert response.data == {
        "schema_version": SCHEMA_VERSION,
        "policy_edition": POLICY_EDITION,
        "workspace_id": str(context.workspace.id),
        "product_id": str(context.product.id),
        "product_version": 1,
        "provider_installation_id": str(INSTALLATION),
        "source_project_id": str(context.project.id),
        "availability": "AVAILABLE",
        "association_id": None,
        "observed_at": response.data["observed_at"],
    }
    assert response["ETag"] == f'"curve-product:{context.product.id}:v1"'
    assert response["Cache-Control"] == "no-store"
    assert counts() == before
    assert Project.objects.filter(id=context.project.id).values().get() == native
    assert context.project.name not in response.content.decode()
    assert context.user.email not in response.content.decode()
    assert CurveProjectAssociationPreconditionsEndpoint.authentication_classes == [SessionAuthentication]


def test_exact_selected_association_is_exposed_but_other_product_and_association_are_redacted(context):
    created = create(context).json()
    before = counts()
    selected = http_read(context)
    assert selected.status_code == 200 and selected.data["association_id"] == created["id"]
    assert selected.data["availability"] == "ASSOCIATED_WITH_SELECTED_PRODUCT"
    other = Product.objects.create(
        workspace_id=context.workspace.id,
        key="other",
        name="Hidden Product",
        timezone="UTC",
        owner_user_id=context.user.id,
        created_by={},
        updated_by={},
    )
    response = http_read(context, product_id=other.id)
    assert response.status_code == 200
    assert response.data["availability"] == "ASSOCIATED_ELSEWHERE" and response.data["association_id"] is None
    serialized = json.dumps(response.data)
    assert str(context.product.id) not in serialized and created["id"] not in serialized
    assert counts() == before


def test_ended_association_is_available_without_returning_history(context, monkeypatch):
    import plane.curve.project_association_services as services

    monkeypatch.setattr(services, "assert_association_can_end", lambda **_: None)
    created = create(context).json()
    assert end(context, created["id"]).status_code == 200
    before = counts()
    result = http_read(context)
    assert result.status_code == 200 and result.data["availability"] == "AVAILABLE"
    assert result.data["association_id"] is None and counts() == before


@pytest.mark.parametrize("role", [5, 15, 20])
def test_read_requires_current_membership_not_command_admin_role(context, role):
    WorkspaceMember.objects.filter(id=context.membership.id).update(role=role)
    assert http_read(context).status_code == 200
    if role != 20:
        assert create(context).status_code == 404


@pytest.mark.parametrize(
    "table,changes",
    [
        ("membership", {"is_active": False}),
        ("membership", {"deleted_at": timezone.now()}),
        ("project_membership", {"is_active": False}),
        ("project_membership", {"deleted_at": timezone.now()}),
        ("project", {"deleted_at": timezone.now()}),
        ("user", {"is_active": False}),
        ("user", {"is_bot": True}),
    ],
)
def test_current_revoked_authority_is_non_enumerating_even_with_stale_user(context, table, changes):
    expected = http_read(context, product_id=uuid.uuid4())
    item = getattr(context, table)
    type(item).objects.filter(id=item.id).update(**changes)
    before = counts()
    actual = http_read(context)
    assert actual.status_code == 404 and actual.data == expected.data
    assert actual["Cache-Control"] == "no-store" and "ETag" not in actual
    assert counts() == before


def test_admin_public_project_and_other_workspace_do_not_bypass_exact_membership(context):
    Project.objects.filter(id=context.project.id).update(network=2)
    ProjectMember.objects.filter(id=context.project_membership.id).update(is_active=False)
    assert http_read(context).status_code == 404
    beta = Workspace.objects.create(name="Beta", slug="beta", owner=context.user)
    WorkspaceMember.objects.create(workspace=beta, member=context.user, role=20)
    assert http_read(context, slug="beta").status_code == 404


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_PROJECT_ASSOCIATIONS_ENABLED", False),
        ("CURVE_PROJECT_ASSOCIATIONS_ENABLED", "true"),
        ("CURVE_ENABLED", False),
        ("CURVE_ENABLED_WORKSPACE_SLUGS", frozenset()),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
        ("CURVE_LOCAL_PLANE_INSTALLATION_ID", None),
        ("CURVE_LOCAL_PLANE_INSTALLATION_ID", "invalid"),
    ],
)
def test_disabled_or_missing_installation_never_means_available(context, settings, setting, value):
    setattr(settings, setting, value)
    before = counts()
    assert http_read(context).status_code == 404 and counts() == before


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?source_project_id=",
        "?source_project_id=nope",
        "?source_project_id=00000000000000000000000000000001",
        "?source_project_id=FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
        "?source_project_id={id}&source_project_id={id}",
        "?source_project_id={id}&can_associate=true",
        "?source_project_id={id}&provider_installation_id={id}",
    ],
)
def test_query_is_exact_canonical_single_uuid(context, query):
    response = http_read(context, query=query.replace("{id}", str(context.project.id)))
    assert response.status_code == 404
    assert response.data == http_read(context, product_id=uuid.uuid4()).data


@pytest.mark.parametrize("archived", ["project", "product"])
def test_archived_product_or_source_is_unavailable(context, archived):
    if archived == "project":
        Project.objects.filter(id=context.project.id).update(archived_at=timezone.now())
    else:
        context.product.state = "ARCHIVED"
        context.product.archived_at = timezone.now()
        context.product.archived_by = {}
        context.product.version += 1
        context.product.save()
    assert http_read(context).status_code == 404


def test_anonymous_and_wrong_method_are_fixed_no_store_denials(context):
    expected = http_read(context, product_id=uuid.uuid4()).data
    assert http_read(context, client_=APIClient()).data == expected
    path = (
        f"/api/v1/workspaces/alpha/curve/products/{context.product.id}/"
        f"project-association-preconditions/?source_project_id={context.project.id}"
    )
    response = client(context.user).post(path, {}, format="json")
    assert response.status_code == 404 and response.data == expected and response["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    ["membership", "project_membership", "user", "project", "product_version", "installation", "gate", "association"],
)
def test_final_snapshot_rejects_same_transaction_changes_and_rolls_them_back(context, monkeypatch, settings, change):
    import plane.curve.project_association_read as module

    original = module._snapshot
    calls = []
    before = counts()

    def snapshot(current):
        value = original(current)
        calls.append(True)
        if len(calls) == 1:
            if change in {"membership", "project_membership", "user"}:
                row = getattr(context, change)
                type(row).objects.filter(id=row.id).update(is_active=False)
            elif change == "project":
                Project.objects.filter(id=context.project.id).update(archived_at=timezone.now())
            elif change == "product_version":
                current.product.version += 1
                current.product.save()
            elif change == "installation":
                settings.CURVE_LOCAL_PLANE_INSTALLATION_ID = str(uuid.uuid4())
            elif change == "gate":
                settings.CURVE_PROJECT_ASSOCIATIONS_ENABLED = False
            else:
                assert create(context).status_code == 201
        return value

    monkeypatch.setattr(module, "_snapshot", snapshot)
    assert http_read(context).status_code == 404
    assert counts() == before
    context.membership.refresh_from_db()
    assert context.membership.is_active


def worker(call):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout='8s'")
        return call()
    finally:
        close_old_connections()


@pytest.mark.parametrize("first", ["read", "create", "revoke"])
def test_read_serializes_with_create_and_revocation(context, first):
    attempted, finished = Event(), Event()

    def pending():
        attempted.set()
        try:
            return create(context) if first == "read" else http_read(context)
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            if first == "read":
                assert read(context)["availability"] == "AVAILABLE"
            elif first == "create":
                assert create(context).status_code == 201
            else:
                ProjectMember.objects.filter(id=context.project_membership.id).update(is_active=False)
            task = pool.submit(worker, pending)
            assert attempted.wait(timeout=5)
            assert not finished.wait(timeout=0.15)
        result = task.result(timeout=25)
    if first == "read":
        assert result.status_code == 201
        assert http_read(context).data["availability"] == "ASSOCIATED_WITH_SELECTED_PRODUCT"
    elif first == "create":
        assert result.status_code == 200 and result.data["availability"] == "ASSOCIATED_WITH_SELECTED_PRODUCT"
    else:
        assert result.status_code == 404


def test_read_contract_pin_is_separate_and_closed():
    import plane.curve.project_association_read as module

    module.require_read_contract_integrity()
    assert (
        "sha256:" + sha256((module.DIRECTORY / "manifest-v1.json").read_bytes()).hexdigest() == module.MANIFEST_DIGEST
    )
    schema = json.loads((module.DIRECTORY / "project-association-precondition-v1.schema.json").read_bytes())
    assert set(schema["required"]) == set(schema["properties"]) == FIELDS
    assert schema["additionalProperties"] is False


def test_real_session_authentication_and_fresh_product_version(context):
    session = APIClient()
    session.force_login(context.user)
    initial = http_read(context, client_=session)
    assert initial.status_code == 200 and initial.data["product_version"] == 1
    context.product.version += 1
    context.product.save()
    fresh = http_read(context, client_=session)
    assert fresh.status_code == 200 and fresh.data["product_version"] == 2
    assert fresh["ETag"] == f'"curve-product:{context.product.id}:v2"'
    assert create(context, version=initial.data["product_version"]).status_code == 412
    assert create(context, version=fresh.data["product_version"], key="fresh-product").status_code == 201


def test_read_first_blocks_concurrent_membership_revocation_until_snapshot_finishes(context):
    attempted, finished = Event(), Event()

    def revoke():
        attempted.set()
        try:
            return ProjectMember.objects.filter(id=context.project_membership.id).update(is_active=False)
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            assert read(context)["availability"] == "AVAILABLE"
            task = pool.submit(worker, revoke)
            assert attempted.wait(timeout=5) and not finished.wait(timeout=0.15)
        assert task.result(timeout=25) == 1
    assert http_read(context).status_code == 404


@pytest.mark.parametrize(
    "name", ["manifest-v1.json", "policy-v1.json", "project-association-precondition-v1.schema.json"]
)
def test_read_packet_corruption_denies_without_side_effects(context, monkeypatch, name):
    from pathlib import Path
    import plane.curve.project_association_read as module

    original = Path.read_bytes
    monkeypatch.setattr(
        Path, "read_bytes", lambda p: original(p) + b" " if p == module.DIRECTORY / name else original(p)
    )
    before = counts()
    response = http_read(context)
    assert response.status_code == 404 and counts() == before
