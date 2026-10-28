# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Native acceptance cases for the forthcoming qualified editor command successor.

These require the dedicated policy constraint, migration and runtime qualification.
They deliberately use the real service and database, with no authorization substitute.
"""

from types import SimpleNamespace
from uuid import UUID

import pytest
from django.db import connection

from plane.curve.feature_editor_policy import scoped_grant
from plane.curve.feature_editor_services import execute_feature_editor_command, FeatureEditorCommandError
from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.services import IdempotencyConflict, OptimisticConcurrencyError, ReplayResourceUnavailable
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def command(scope, *, user=None, key="synthetic-editor-command", grant_id=None, version=None, target=None):
    return execute_feature_editor_command(
        request=SimpleNamespace(user=user or scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        action="REVOKE_FEATURE_EDITOR" if grant_id else "GRANT_FEATURE_EDITOR",
        payload={} if grant_id else {"member_id": str((target or scope.member).id)},
        raw_idempotency_key=key,
        grant_id=grant_id,
        expected_version=version,
    )


def row(scope, result):
    return scoped_grant(
        workspace_id=scope.workspace.id, product_id=scope.product.id, grant_id=UUID(result.resource_ref["resource_id"])
    )


def counts(scope):
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM curve_feature_editor_grant WHERE workspace_id=%s", [scope.workspace.id])
        grants = cursor.fetchone()[0]
    return [grants] + [
        model.objects.filter(workspace_id=scope.workspace.id).count()
        for model in (DomainEvent, OutboxEvent, IdempotencyRecord)
    ]


@pytest.mark.parametrize("actor", ["owner", "admin"])
def test_authorized_grant_and_replay_retain_original_identity(scope, actor):
    first = command(scope, user=getattr(scope, actor))
    replay = command(scope, user=getattr(scope, actor))
    assert first.resource_ref == replay.resource_ref
    assert first.response_digest == replay.response_digest
    assert not first.replayed and replay.replayed
    assert row(scope, first)["granted_by"] == getattr(scope, actor).id
    assert row(scope, first)["version"] == 1
    assert counts(scope) == [1, 1, 1, 1]
    assert PolicyDecision.objects.filter(workspace_id=scope.workspace.id).count() == 2
    assert AuditEvent.objects.filter(workspace_id=scope.workspace.id).count() == 2


def test_editor_grant_does_not_authorize_managing_editors(scope):
    command(scope)
    before = counts(scope)
    with pytest.raises(CurvePolicyDenied):
        command(scope, user=scope.member, target=scope.admin)
    assert counts(scope) == before


def test_duplicate_grant_with_new_key_has_no_mutation_effect(scope):
    command(scope)
    before = counts(scope)
    with pytest.raises(FeatureEditorCommandError, match="ALREADY_GRANTED"):
        command(scope, key="synthetic-another-command")
    assert counts(scope) == before
    assert AuditEvent.objects.filter(workspace_id=scope.workspace.id, outcome="NO_EFFECT").count() == 1


def test_same_key_with_different_recipient_conflicts(scope):
    command(scope)
    with pytest.raises(IdempotencyConflict):
        command(scope, target=scope.admin)
    assert counts(scope) == [1, 1, 1, 1]


def test_revocation_and_retry_use_original_version_precondition(scope):
    granted = command(scope)
    identity = granted.resource_ref["resource_id"]
    revoked = command(scope, grant_id=identity, version=1, key="synthetic-revoke-command")
    replay = command(scope, grant_id=identity, version=1, key="synthetic-revoke-command")
    assert revoked.resource_ref == replay.resource_ref
    assert revoked.resource_ref["resource_version"] == 2
    assert replay.replayed
    assert counts(scope) == [1, 2, 2, 2]
    with pytest.raises(ReplayResourceUnavailable):
        command(scope)
    assert counts(scope) == [1, 2, 2, 2]


def test_stale_revocation_version_leaves_grant_and_outbox_unchanged(scope):
    granted = command(scope)
    with pytest.raises(OptimisticConcurrencyError):
        command(scope, grant_id=granted.resource_ref["resource_id"], version=2, key="synthetic-stale-revoke")
    assert row(scope, granted)["revoked_at"] is None
    assert counts(scope) == [1, 1, 1, 1]


def test_replay_rechecks_actor_membership(scope):
    command(scope)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    with pytest.raises(CurvePolicyDenied):
        command(scope)
    assert counts(scope) == [1, 1, 1, 1]


def test_restored_target_requires_new_grant_not_successful_replay(scope):
    first = command(scope)
    memberships = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    memberships.update(is_active=False)
    memberships.update(is_active=True)
    with pytest.raises(ReplayResourceUnavailable):
        command(scope)
    second = command(scope, key="synthetic-fresh-grant-command")
    assert first.resource_ref["resource_id"] != second.resource_ref["resource_id"]
    assert row(scope, second)["membership_generation"] == row(scope, first)["membership_generation"] + 1
    assert counts(scope) == [2, 2, 2, 2]


def test_owner_can_revoke_after_target_membership_loss(scope):
    first = command(scope)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member).update(is_active=False)
    result = command(scope, grant_id=first.resource_ref["resource_id"], version=1, key="synthetic-lost-target-revoke")
    assert row(scope, result)["revoked_at"] is not None
    assert counts(scope) == [1, 2, 2, 2]


def test_outbox_failure_rolls_back_grant_event_receipt_and_policy_evidence(scope, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(OutboxEvent.objects, "create", unavailable)
    with pytest.raises(RuntimeError, match="synthetic outbox failure"):
        command(scope)
    assert counts(scope) == [0, 0, 0, 0]
    assert PolicyDecision.objects.filter(workspace_id=scope.workspace.id).count() == 0
    assert AuditEvent.objects.filter(workspace_id=scope.workspace.id).count() == 0
