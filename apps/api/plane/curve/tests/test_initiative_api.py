# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from pathlib import Path

import pytest
from django.db import IntegrityError
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from rest_framework.test import APIClient

from plane.curve.initiative_services import MANUAL_FIRST_WORKFLOW_VERSION_ID
from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    GateAssignment,
    GateType,
    IdempotencyRecord,
    Initiative,
    InitiativeBusinessIntent,
    OutboxEvent,
    PolicyDecision,
    Product,
    ProductState,
)
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def _curve_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha", "beta"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "curve-initiative-api-test"


def _user(email):
    return User.objects.create(email=email, username=email)


def _workspace(*, slug, owner, role=20):
    workspace = Workspace.objects.create(name=slug.title(), slug=slug, owner=owner)
    WorkspaceMember.objects.create(workspace=workspace, member=owner, role=role, is_active=True)
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


def _actor(user):
    return {"actor_type": "HUMAN", "actor_id": str(user.id)}


def _product(workspace, owner, *, key="mobile-platform", state=ProductState.ACTIVE):
    archived = state == ProductState.ARCHIVED
    return Product.objects.create(
        workspace_id=workspace.id,
        key=key,
        name="Mobile Platform",
        description="Synthetic INTERNAL Product",
        timezone="America/Argentina/Buenos_Aires",
        state=state,
        owner_user_id=owner.id,
        created_by=_actor(owner),
        updated_by=_actor(owner),
        archived_at=timezone.now() if archived else None,
        archived_by=_actor(owner) if archived else None,
    )


def _gate_payload(*approvers):
    return [
        {"gate_type": GateType.PRD_APPROVAL, "approver_user_id": str(approvers[0].id)},
        {"gate_type": GateType.PLAN_APPROVAL, "approver_user_id": str(approvers[1].id)},
        {"gate_type": GateType.CODE_READINESS, "approver_user_id": str(approvers[2].id)},
    ]


def _payload(
    product,
    approvers,
    *,
    keyword="Example-capability",
    risk="STANDARD",
    mode="STANDALONE",
    business_intent=InitiativeBusinessIntent.STRATEGIC,
):
    return {
        "product_id": str(product.id),
        "mode": mode,
        "keyword": keyword,
        "title": "Example capability overview",
        "description": {
            "schema_version": "1.0",
            "format": "MARKDOWN",
            "body": "Synthetic INTERNAL Initiative description.",
        },
        "risk_tier": risk,
        "business_intent": business_intent,
        "gate_assignments": _gate_payload(*approvers),
    }


def _create(client, payload, *, slug="alpha", idem="initiative-create-key-0001"):
    return client.post(
        f"/api/v1/workspaces/{slug}/curve/initiatives/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=idem,
    )


def _url(initiative_id, suffix="", *, slug="alpha"):
    return f"/api/v1/workspaces/{slug}/curve/initiatives/{initiative_id}/{suffix}"


def _mutate(client, initiative, suffix, payload, *, idem):
    return client.post(
        _url(initiative.id, suffix),
        payload,
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative.id}:v{initiative.version}"',
        HTTP_IDEMPOTENCY_KEY=idem,
    )


@pytest.fixture(scope="module")
def initiative_schema_contracts():
    schema_directory = Path(__file__).parents[1] / "contracts" / "schemas"
    schemas = {path.name: json.loads(path.read_text()) for path in schema_directory.glob("*.schema.json")}
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas.values())
    return {
        name: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for name, schema in schemas.items()
    }


def test_create_is_atomic_contract_valid_and_idempotently_replayed(initiative_schema_contracts):
    creator = _user("initiative-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    approvers = (
        creator,
        _add_member(workspace, email="initiative-plan-approver@example.com"),
        _add_member(workspace, email="initiative-code-approver@example.com"),
    )
    product = _product(workspace, creator)
    client = _client(creator)
    payload = _payload(product, approvers)

    created = _create(client, payload)
    replay = _create(client, payload)

    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    assert created["ETag"] == f'"curve-initiative:{created.json()["id"]}:v1"'
    assert created["Location"].endswith(f"{created.json()['id']}/")
    assert created.json()["workspace_id"] == str(workspace.id)
    assert created.json()["creator"] == _actor(creator)
    initiative_schema_contracts["initiative-v1.1.schema.json"].validate(created.json())
    assert Initiative.objects.filter(workspace_id=workspace.id).count() == 1
    assert GateAssignment.objects.filter(workspace_id=workspace.id).count() == 3
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_type="INITIATIVE").count() == 1
    assert OutboxEvent.objects.filter(workspace_id=workspace.id, destination="CURVE_INITIATIVE_LOCAL_V1").count() == 1
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 1
    assert PolicyDecision.objects.filter(workspace_id=workspace.id, policy_key="CURVE_INITIATIVE_POLICY").count() == 2
    assert AuditEvent.objects.filter(workspace_id=workspace.id, target_type="INITIATIVE").count() == 2
    event = DomainEvent.objects.get(workspace_id=workspace.id, aggregate_type="INITIATIVE")
    initiative_schema_contracts["initiative-event-v1.schema.json"].validate(event.payload)


def test_create_fails_closed_for_product_mode_keyword_and_workspace_boundaries():
    creator = _user("boundary-creator@example.com")
    alpha = _workspace(slug="alpha", owner=creator, role=15)
    beta_owner = _user("boundary-beta-owner@example.com")
    beta = _workspace(slug="beta", owner=beta_owner, role=15)
    approvers = (
        creator,
        _add_member(alpha, email="boundary-plan@example.com"),
        _add_member(alpha, email="boundary-code@example.com"),
    )
    product = _product(alpha, creator)
    archived = _product(alpha, creator, key="archived-product", state=ProductState.ARCHIVED)
    foreign = _product(beta, beta_owner, key="foreign-product")
    client = _client(creator)

    first = _create(client, _payload(product, approvers, keyword="Case-Key"), idem="boundary-first-key-0001")
    duplicate = _create(
        client,
        _payload(product, approvers, keyword="case-key"),
        idem="boundary-duplicate-key-01",
    )
    roadmap = _create(
        client,
        _payload(product, approvers, keyword="roadmap-key", mode="ROADMAP"),
        idem="boundary-roadmap-key-001",
    )
    inactive = _create(
        client,
        _payload(archived, approvers, keyword="inactive-key"),
        idem="boundary-inactive-key-01",
    )
    cross_workspace = _create(
        client,
        _payload(foreign, approvers, keyword="foreign-key"),
        idem="boundary-foreign-key-001",
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["errors"][0]["code"] == "INITIATIVE_KEYWORD_CONFLICT"
    assert roadmap.status_code == 409
    assert roadmap.json()["errors"][0]["code"] == "ROADMAP_MODE_NOT_AVAILABLE"
    assert inactive.status_code == 409
    assert inactive.json()["errors"][0]["code"] == "PRODUCT_INACTIVE"
    assert cross_workspace.status_code == 404
    assert Initiative.objects.filter(workspace_id=alpha.id).count() == 1
    assert Initiative.objects.filter(workspace_id=beta.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=alpha.id, aggregate_type="INITIATIVE").count() == 1


def test_gate_assignment_policy_enforces_active_humans_and_risk_separation():
    creator = _user("gate-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    other = _add_member(workspace, email="gate-other@example.com")
    inactive = _add_member(workspace, email="gate-inactive@example.com", active=False)
    product = _product(workspace, creator)
    client = _client(creator)

    overlap = (creator, creator, other)
    rejected_overlap = _create(
        client,
        _payload(product, overlap, keyword="standard-overlap"),
        idem="gate-standard-overlap-01",
    )
    rejected_inactive = _create(
        client,
        _payload(product, (creator, other, inactive), keyword="inactive-approver"),
        idem="gate-inactive-member-001",
    )
    accepted_low = _create(
        client,
        _payload(product, (creator, creator, creator), keyword="low-overlap", risk="LOW"),
        idem="gate-low-overlap-key-001",
    )

    assert rejected_overlap.status_code == 409
    assert rejected_inactive.status_code == 409
    assert accepted_low.status_code == 201
    assert Initiative.objects.filter(workspace_id=workspace.id).count() == 1
    assert GateAssignment.objects.filter(workspace_id=workspace.id).count() == 3


def test_draft_update_preserves_mutability_boundary_concurrency_and_replay():
    creator = _user("update-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    approvers = (
        creator,
        _add_member(workspace, email="update-plan@example.com"),
        _add_member(workspace, email="update-code@example.com"),
    )
    product = _product(workspace, creator)
    client = _client(creator)
    created = _create(client, _payload(product, approvers), idem="update-create-key-00001")
    initiative_id = created.json()["id"]
    url = _url(initiative_id)

    updated = client.patch(
        url,
        {
            "keyword": "Example-capability-v2",
            "title": "Updated SDK compatibility",
            "business_intent": InitiativeBusinessIntent.CUSTOMER_COMMITMENT,
        },
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="update-metadata-key-0001",
    )
    replay = client.patch(
        url,
        {
            "keyword": "Example-capability-v2",
            "title": "Updated SDK compatibility",
            "business_intent": InitiativeBusinessIntent.CUSTOMER_COMMITMENT,
        },
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="update-metadata-key-0001",
    )
    stale = client.patch(
        url,
        {"title": "Stale"},
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="update-stale-key-000001",
    )
    forbidden = client.patch(
        url,
        {"state": "ALIGNING"},
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative_id}:v2"',
        HTTP_IDEMPOTENCY_KEY="update-forbidden-key-001",
    )

    assert updated.status_code == replay.status_code == 200
    assert updated.json()["version"] == replay.json()["version"] == 2
    assert updated.json()["keyword"] == "Example-capability-v2"
    assert updated.json()["business_intent"] == InitiativeBusinessIntent.CUSTOMER_COMMITMENT
    assert stale.status_code == 412
    assert forbidden.status_code == 422
    sequences = (
        DomainEvent.objects.filter(aggregate_id=initiative_id).order_by("sequence").values_list("sequence", flat=True)
    )
    assert list(sequences) == [1, 2]


def test_draft_may_defer_business_intent_but_alignment_requires_it():
    creator = _user("intent-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    approvers = (
        creator,
        _add_member(workspace, email="intent-plan@example.com"),
        _add_member(workspace, email="intent-code@example.com"),
    )
    product = _product(workspace, creator)
    client = _client(creator)
    created = _create(
        client,
        _payload(product, approvers, keyword="intent-later", business_intent=None),
        idem="intent-create-key-00001",
    )
    initiative = Initiative.objects.get(id=created.json()["id"])
    rejected = _mutate(client, initiative, "accept-refinement/", {}, idem="intent-align-key-000001")

    assert created.status_code == 201
    assert created.json()["business_intent"] is None
    assert rejected.status_code == 422
    assert rejected.json()["errors"][0]["field"] == "business_intent"


def test_lifecycle_pins_workflow_and_supports_authorized_pause_resume_cancel():
    creator = _user("lifecycle-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    plan_approver = _add_member(workspace, email="lifecycle-plan@example.com")
    code_approver = _add_member(workspace, email="lifecycle-code@example.com")
    product = _product(workspace, creator)
    creator_client = _client(creator)
    created = _create(
        creator_client,
        _payload(product, (creator, plan_approver, code_approver)),
        idem="lifecycle-create-key-01",
    )
    initiative = Initiative.objects.get(id=created.json()["id"])

    accepted = _mutate(
        creator_client,
        initiative,
        "accept-refinement/",
        {},
        idem="lifecycle-accept-key-01",
    )
    initiative.refresh_from_db()
    paused = _mutate(
        _client(plan_approver),
        initiative,
        "pause/",
        {"reason": "Synthetic pause"},
        idem="lifecycle-pause-key-001",
    )
    initiative.refresh_from_db()
    resumed = _mutate(
        _client(code_approver),
        initiative,
        "resume/",
        {"reason": "Synthetic resume"},
        idem="lifecycle-resume-key-01",
    )
    initiative.refresh_from_db()
    cancelled = _mutate(
        creator_client,
        initiative,
        "cancel/",
        {"reason": "Synthetic cancellation"},
        idem="lifecycle-cancel-key-01",
    )
    initiative.refresh_from_db()
    terminal_retry = creator_client.post(
        _url(initiative.id, "resume/"),
        {"reason": "Cannot resume"},
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative.id}:v{initiative.version}"',
        HTTP_IDEMPOTENCY_KEY="lifecycle-terminal-key-01",
    )

    assert accepted.status_code == paused.status_code == resumed.status_code == cancelled.status_code == 200
    assert accepted.json()["workflow_version_id"] == str(MANUAL_FIRST_WORKFLOW_VERSION_ID)
    assert paused.json()["state"] == "PAUSED"
    assert paused.json()["paused_from_state"] == "ALIGNING"
    assert resumed.json()["state"] == "ALIGNING"
    assert cancelled.json()["state"] == initiative.state == "CANCELLED"
    assert terminal_retry.status_code == 409
    assert [
        event.payload["event_type"]
        for event in DomainEvent.objects.filter(aggregate_id=initiative.id).order_by("sequence")
    ] == [
        "INITIATIVE_CREATED",
        "INITIATIVE_REFINEMENT_ACCEPTED",
        "INITIATIVE_PAUSED",
        "INITIATIVE_RESUMED",
        "INITIATIVE_CANCELLED",
    ]


def test_restricted_commands_deny_unassigned_members_and_hide_cross_workspace_records():
    creator = _user("auth-creator@example.com")
    alpha = _workspace(slug="alpha", owner=creator, role=15)
    member = _add_member(alpha, email="auth-member@example.com")
    approvers = (
        creator,
        _add_member(alpha, email="auth-plan@example.com"),
        _add_member(alpha, email="auth-code@example.com"),
    )
    product = _product(alpha, creator)
    created = _create(_client(creator), _payload(product, approvers), idem="auth-create-key-000001")
    initiative_id = created.json()["id"]

    denied = _client(member).patch(
        _url(initiative_id),
        {"title": "Unauthorized"},
        format="json",
        HTTP_IF_MATCH=f'"curve-initiative:{initiative_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="auth-denied-key-000001",
    )
    beta_owner = _user("auth-beta-owner@example.com")
    _workspace(slug="beta", owner=beta_owner, role=15)
    hidden = _client(beta_owner).get(_url(initiative_id, slug="beta"))

    assert denied.status_code == 403
    assert hidden.status_code == 404
    assert Initiative.objects.get(id=initiative_id).version == 1
    assert DomainEvent.objects.filter(aggregate_id=initiative_id).count() == 1
    assert OutboxEvent.objects.filter(workspace_id=alpha.id, destination="CURVE_INITIATIVE_LOCAL_V1").count() == 1


def test_product_archive_uses_real_non_terminal_initiative_guard():
    admin = _user("archive-admin@example.com")
    workspace = _workspace(slug="alpha", owner=admin)
    plan_approver = _add_member(workspace, email="archive-plan@example.com")
    code_approver = _add_member(workspace, email="archive-code@example.com")
    product = _product(workspace, admin)
    client = _client(admin)
    created = _create(
        client,
        _payload(product, (admin, plan_approver, code_approver)),
        idem="archive-create-key-0001",
    )

    blocked = client.post(
        f"/api/v1/workspaces/alpha/curve/products/{product.id}/archive/",
        {},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product.id}:v1"',
        HTTP_IDEMPOTENCY_KEY="archive-blocked-key-001",
    )
    initiative = Initiative.objects.get(id=created.json()["id"])
    cancelled = _mutate(
        client,
        initiative,
        "cancel/",
        {"reason": "Complete the disposable archive proof"},
        idem="archive-cancel-key-001",
    )
    archived = client.post(
        f"/api/v1/workspaces/alpha/curve/products/{product.id}/archive/",
        {},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product.id}:v1"',
        HTTP_IDEMPOTENCY_KEY="archive-allowed-key-001",
    )

    assert blocked.status_code == 409
    assert cancelled.status_code == 200
    assert archived.status_code == 200
    assert archived.json()["state"] == "ARCHIVED"


def test_list_is_workspace_scoped_filterable_and_cursor_paginated():
    creator = _user("list-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    approvers = (
        creator,
        _add_member(workspace, email="list-plan@example.com"),
        _add_member(workspace, email="list-code@example.com"),
    )
    product = _product(workspace, creator)
    client = _client(creator)
    _create(client, _payload(product, approvers, keyword="list-first"), idem="list-create-first-key-01")
    _create(client, _payload(product, approvers, keyword="list-second"), idem="list-create-second-key-1")

    first_page = client.get("/api/v1/workspaces/alpha/curve/initiatives/?page_size=1&state=DRAFT")
    second_page = client.get(
        f"/api/v1/workspaces/alpha/curve/initiatives/?page_size=1&cursor={first_page.json()['next_cursor']}"
    )

    assert first_page.status_code == second_page.status_code == 200
    assert len(first_page.json()["results"]) == len(second_page.json()["results"]) == 1
    assert first_page.json()["results"][0]["id"] != second_page.json()["results"][0]["id"]
    assert second_page.json()["next_cursor"] is None


def test_database_failure_rolls_back_initiative_assignments_delivery_and_idempotency(monkeypatch):
    creator = _user("rollback-creator@example.com")
    workspace = _workspace(slug="alpha", owner=creator, role=15)
    approvers = (
        creator,
        _add_member(workspace, email="rollback-plan@example.com"),
        _add_member(workspace, email="rollback-code@example.com"),
    )
    product = _product(workspace, creator)

    def fail_outbox(*args, **kwargs):
        raise IntegrityError("synthetic outbox failure")

    monkeypatch.setattr(OutboxEvent.objects, "create", fail_outbox)
    client = _client(creator)
    client.raise_request_exception = False
    response = _create(
        client,
        _payload(product, approvers, keyword="rollback-proof"),
        idem="rollback-create-key-001",
    )

    assert response.status_code == 500
    assert Initiative.objects.filter(workspace_id=workspace.id).count() == 0
    assert GateAssignment.objects.filter(workspace_id=workspace.id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace.id, aggregate_type="INITIATIVE").count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace.id, destination="CURVE_INITIATIVE_LOCAL_V1").count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace.id).count() == 0
