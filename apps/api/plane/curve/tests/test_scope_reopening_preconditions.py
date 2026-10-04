# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Minimal fresh-client reopening pins reveal no removed-source or PRD history."""
# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import Issue, Workspace, WorkspaceMember
from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision
from plane.curve.prd_read_context import PrdReadUnavailable
from plane.curve.scope_reopening_models import ScopeReopening
from plane.curve.scope_reopening_read import ACTION, POLICY_EDITION, SCHEMA_VERSION, read_scope_reopening_preconditions
from plane.curve.tests.test_prd_lifecycle_repository import raw_update
from plane.curve.tests.test_prd_policy_context import resolver
from plane.curve.tests.test_scope_reopening_services import (  # noqa: F401
    accept,
    adopt,
    bridge,
    complete,
    configuration,
    context,
    existing_lifecycle_command,
    make_issue,
    post,
    raw_gate,
    reopen,
    reopening,
    replacement,
    review_command,
    selection,
    stage,
    submit,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
FIELDS = {
    "schema_version",
    "policy_edition",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "expected_scope_revision",
    "eligibility",
    "pending_reopening",
}


def read(bridge, *, request=None, slug=None, initiative_id=None):
    return read_scope_reopening_preconditions(
        request=request or bridge.request,
        workspace_slug=slug or bridge.workspace.slug,
        initiative_id=initiative_id or bridge.initiative.id,
    )


def http_read(bridge, *, user=None, slug=None, initiative_id=None):
    client = APIClient()
    client.force_authenticate(user=user or bridge.user)
    return client.get(
        f"/api/v1/workspaces/{slug or bridge.workspace.slug}/curve/initiatives/"
        f"{initiative_id or bridge.initiative.id}/scope-reopening/v1/preconditions/"
    )


def counters():
    return {
        model._meta.db_table: model.objects.count()
        for model in (AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision, ScopeReopening)
    }


def test_read_packet_is_independently_pinned_and_closed():
    root = Path(__file__).parents[1] / "scope_reopening_read_candidate"
    assert "sha256:" + sha256((root / "manifest-v1.json").read_bytes()).hexdigest() == (
        "sha256:f272f465c5660eff2f8a4f95be1bbac69e162e3c50724c375629e71ab4fcc3de"
    )
    assert json.loads((root / "manifest-v1.json").read_text()) == {
        "policy-v1.json": "sha256:bff7796e940087af1d1150f142800204fa9c26786ed911c9f449c44a0515916a",
        "scope-reopening-precondition-v1.schema.json": (
            "sha256:ae1ee3cd886156c83ca0c4f5e20b690fe7b67b34373c1cda4d6c29595b8b091e"
        ),
    }
    schema = json.loads((root / "scope-reopening-precondition-v1.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"]) == FIELDS
    policy = json.loads((root / "policy-v1.json").read_text())
    assert policy["policy_key"] == "CURVE_SCOPE_REOPENING_PRECONDITION_POLICY"
    assert len(policy["actions"]) == 1 and policy["actions"][0]["action"] == ACTION
    assert policy["actions"][0]["allowed_roles"] == ["PRODUCT_APPROVER"]


@pytest.mark.parametrize("state", ["ALIGNING", "PRD_REVIEW", "PLANNING"])
def test_read_has_exact_target_pins_no_history_or_side_effects(reopening, state):
    stage(reopening, state)
    before = counters()
    response = http_read(reopening)
    assert response.status_code == 200, response.data
    assert response["Cache-Control"] == "no-store" and response["ETag"] == f'"{reopening.initiative.version}"'
    assert response.data == dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        workspace_id=str(reopening.workspace.id),
        initiative_id=str(reopening.initiative.id),
        initiative_version=reopening.initiative.version,
        expected_scope_revision=1,
        eligibility="REOPENABLE",
        pending_reopening=False,
    )
    assert set(response.data) == FIELDS and counters() == before
    assert str(reopening.issue.id) not in json.dumps(response.data)
    assert str(reopening.association.id) not in json.dumps(response.data)
    assert str(reopening.product.id) not in json.dumps(response.data)


def test_exact_read_action_acl_is_required(reopening):
    calls = []

    def deny(**kwargs):
        calls.append(kwargs["action"])
        value = resolver(**kwargs)
        if kwargs["action"] == ACTION:
            value["object_acl"]["deny_principals"] = [kwargs["actor"]]
        return value

    reopening.runtime.resolve_acl = deny
    before = counters()
    assert http_read(reopening).status_code == 404
    assert calls and set(calls) == {"CURVE.SCOPE.REOPEN_PRECONDITIONS.READ"}
    assert counters() == before


@pytest.mark.parametrize("kind", ["admin", "creator", "missing", "wrong_workspace", "inactive_actor"])
def test_denied_missing_and_cross_workspace_read_are_non_enumerating(reopening, kind):
    expected = http_read(reopening, initiative_id=uuid.uuid4())
    assert expected.status_code == 404
    kwargs = {}
    if kind == "admin":
        user = reopening.reviewers[1]
        WorkspaceMember.objects.filter(workspace=reopening.workspace, member=user).update(role=20)
        kwargs["user"] = user
    elif kind == "creator":
        raw_gate(reopening.gates[0], valid_until=timezone.now() - timedelta(seconds=1))
    elif kind == "missing":
        kwargs["initiative_id"] = uuid.uuid4()
    elif kind == "wrong_workspace":
        other = Workspace.objects.create(name="Other", slug="other", owner=reopening.user)
        WorkspaceMember.objects.create(workspace=other, member=reopening.user, role=20)
        kwargs["slug"] = other.slug
    else:
        WorkspaceMember.objects.filter(workspace=reopening.workspace, member=reopening.user).update(is_active=False)
    actual = http_read(reopening, **kwargs)
    assert actual.status_code == expected.status_code == 404
    assert actual.data == expected.data
    assert actual["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_SCOPE_REOPENING_ENABLED", False),
        ("CURVE_SCOPE_PROPOSALS_ENABLED", False),
        ("CURVE_SCOPED_PRD_COMMANDS_ENABLED", False),
        ("CURVE_PRD_COMMANDS_ENABLED", False),
        ("CURVE_ENABLED", False),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
    ],
)
def test_read_disabled_and_unqualified_contexts_are_hidden(reopening, settings, setting, value):
    setattr(settings, setting, value)
    assert http_read(reopening).status_code == 404


@pytest.mark.parametrize("change", ["version", "assignment", "actor_membership", "reviewer_membership"])
def test_last_acl_callback_cannot_return_stale_preconditions(reopening, change):
    calls = []

    def callback(**kwargs):
        calls.append(kwargs["action"])
        value = resolver(**kwargs)
        if len(calls) == 2:
            if change == "version":
                raw_update(reopening.initiative.id, version=reopening.initiative.version + 1)
            elif change == "assignment":
                raw_gate(reopening.gates[1], valid_until=timezone.now() - timedelta(seconds=1))
            else:
                member = reopening.reviewers[1] if change == "reviewer_membership" else reopening.user
                WorkspaceMember.objects.filter(workspace=reopening.workspace, member=member).update(is_active=False)
        return value

    reopening.runtime.resolve_acl = callback
    before = counters()
    with pytest.raises(PrdReadUnavailable):
        read(reopening)
    assert calls and counters() == before
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.version == 3
    assert WorkspaceMember.objects.get(workspace=reopening.workspace, member=reopening.user).is_active


def test_fresh_client_can_remediate_deleted_old_member_then_submit_and_approve(reopening):
    stage(reopening, "PLANNING")
    checkpoint = reopening.initiative.current_prd_checkpoint_id
    new_issue = make_issue(reopening)
    Issue.all_objects.filter(id=reopening.issue.id).delete()
    client = APIClient()
    client.force_authenticate(user=reopening.user)
    base = f"/api/v1/workspaces/{reopening.workspace.slug}/curve/initiatives/{reopening.initiative.id}"
    preconditions = client.get(base + "/scope-reopening/v1/preconditions/")
    assert preconditions.status_code == 200, preconditions.data
    assert set(preconditions.data) == FIELDS
    payload = replacement(
        reopening, items=[selection(reopening, new_issue)], expected=preconditions.data["expected_scope_revision"]
    )
    replaced = client.post(
        base + "/scope-reopening/v1/reopen-and-replace/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_IF_MATCH=f'"{preconditions.data["initiative_version"]}"',
        HTTP_IDEMPOTENCY_KEY="fresh-client-remediation",
    )
    assert replaced.status_code == 201, replaced.data
    adopt(reopening, SimpleNamespace(data=replaced.data))
    pending = client.get(base + "/scope-reopening/v1/preconditions/")
    assert pending.status_code == 200 and pending.data["pending_reopening"] is True
    assert pending.data["expected_scope_revision"] == 2
    subject, _, _ = submit(reopening)
    assert reopening.initiative.current_prd_checkpoint_id != checkpoint
    operation = accept(reopening, review_command(reopening, subject)).operation
    assert complete(reopening, operation)["status"] == "SUCCEEDED"
    reopening.initiative.refresh_from_db()
    assert reopening.initiative.state == "PLANNING" and reopening.initiative.pending_scope_reopening_id is None


def test_pending_paused_read_returns_only_state_blocked_and_boolean(reopening):
    adopt(reopening, reopen(reopening))
    existing_lifecycle_command(reopening, "pause")
    result = read(reopening)
    assert set(result) == FIELDS
    assert result["eligibility"] == "STATE_BLOCKED" and result["pending_reopening"] is True
