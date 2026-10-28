# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace

import pytest

from plane.curve.feature_services import execute_feature_command
from plane.curve.feature_read import read_features
from plane.curve.models import AuditEvent, DomainEvent, Feature, IdempotencyRecord, OutboxEvent
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.services import OptimisticConcurrencyError
from plane.curve.tests.test_feature_editor_commands import command as editor_command
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def command(scope, *, user=None, feature=None, version=None, key="synthetic-feature-create", name="Example Feature"):
    return execute_feature_command(
        request=SimpleNamespace(user=user or scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        action="UPDATE_FEATURE" if feature else "CREATE_FEATURE",
        feature_id=feature,
        payload={"name": name, "description": None},
        expected_version=version,
        raw_idempotency_key=key,
    )


def counts(scope):
    return [
        model.objects.filter(workspace_id=scope.workspace.id).count()
        for model in (Feature, DomainEvent, OutboxEvent, IdempotencyRecord)
    ]


def test_owner_create_update_replay_preserves_original_result(scope):
    created = command(scope)
    identity = created.resource_ref["resource_id"]
    updated = command(scope, feature=identity, version=1, key="synthetic-update", name="Updated Feature")
    retried = command(scope, feature=identity, version=1, key="synthetic-update", name="Updated Feature")
    original = command(scope)
    assert retried.replayed and original.replayed
    assert original.resource_ref == created.resource_ref
    assert retried.resource_ref == updated.resource_ref
    assert counts(scope) == [1, 2, 2, 2]
    row = Feature.objects.get(id=identity)
    assert row.name == "Updated Feature" and row.version == 2
    assert AuditEvent.objects.filter(workspace_id=scope.workspace.id).count() == 4


@pytest.mark.parametrize("actor", ["admin", "member"])
def test_management_role_alone_cannot_create_feature(scope, actor):
    with pytest.raises(CurvePolicyDenied):
        command(scope, user=getattr(scope, actor))
    assert counts(scope) == [0, 0, 0, 0]


def test_explicit_editor_can_edit_but_revocation_blocks_replay(scope):
    grant = editor_command(scope)
    created = command(scope, user=scope.member)
    editor_command(scope, grant_id=grant.resource_ref["resource_id"], version=1, key="synthetic-revoke")
    before = counts(scope)
    with pytest.raises(CurvePolicyDenied):
        command(scope, user=scope.member)
    assert counts(scope) == before
    assert Feature.objects.get(id=created.resource_ref["resource_id"]).version == 1


def test_restored_membership_does_not_restore_feature_editing(scope):
    editor_command(scope)
    command(scope, user=scope.member)
    memberships = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    memberships.update(is_active=False)
    memberships.update(is_active=True)
    with pytest.raises(CurvePolicyDenied):
        command(scope, user=scope.member, key="synthetic-after-restoration")
    editor_command(scope, key="synthetic-fresh-grant")
    assert command(scope, user=scope.member, key="synthetic-after-restoration").response_status == 201


def test_stale_update_has_no_feature_event_or_receipt_effect(scope):
    created = command(scope)
    before = counts(scope)
    with pytest.raises(OptimisticConcurrencyError):
        command(scope, feature=created.resource_ref["resource_id"], version=2, key="synthetic-stale")
    assert counts(scope) == before


def test_product_member_reads_metadata_without_edit_authority(scope):
    created = command(scope)
    args = dict(
        request=SimpleNamespace(user=scope.member, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
    )
    listing = read_features(**args)
    assert listing["is_editor"] is False
    assert "description" not in listing["results"][0]
    detail = read_features(**args, feature_id=created.resource_ref["resource_id"])
    assert detail["can_edit"] is False and detail["description"] is None
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member).update(is_active=False)
    with pytest.raises(CurvePolicyDenied):
        read_features(**args)


def test_event_failure_rolls_back_feature_outbox_and_receipt(scope, monkeypatch):
    from django.db import IntegrityError
    from plane.curve import feature_services

    original = feature_services._event

    def fail_after_event(*args, **kwargs):
        original(*args, **kwargs)
        raise IntegrityError("synthetic-event-boundary-failure")

    monkeypatch.setattr(feature_services, "_event", fail_after_event)
    with pytest.raises(IntegrityError):
        command(scope)
    assert counts(scope) == [0, 0, 0, 0]
    assert list(AuditEvent.objects.filter(workspace_id=scope.workspace.id).values_list("outcome", flat=True)) == [
        "NO_EFFECT"
    ]
