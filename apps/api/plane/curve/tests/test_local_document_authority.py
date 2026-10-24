# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811

from types import SimpleNamespace

import pytest
from django.db import transaction
from plane.db.models import User, WorkspaceMember, ProjectMember
from plane.curve.local_document_authority import require_local_document_authority
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def local(two_stage, settings):
    settings.CURVE_LOCAL_PRD_ENABLED = True
    # The local authorization boundary must resolve actual native access rather
    # than the external-document test fixture's acceptance/completion adapters.
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = None
    settings.CURVE_PRD_COMPLETION_RUNTIME = None
    return two_stage


def authorize(local, *, actor=None, action="UPLOAD", version=None):
    return require_local_document_authority(
        request=SimpleNamespace(user=actor or local.user),
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        action=action,
        expected_version=local.initiative.version if version is None else version,
    )


def test_creator_can_prepare_upload_and_repeat_authority_is_stable(local):
    with transaction.atomic():
        first = authorize(local)
    with transaction.atomic():
        second = authorize(local)
    assert first.fence == second.fence
    assert first.current_source is None
    assert {r["gate_type"] for r in first.context.reviewers} == {"PRD_APPROVAL", "PLAN_APPROVAL"}


def test_technical_approver_can_read_but_cannot_upload_for_creator(local):
    with transaction.atomic():
        assert authorize(local, actor=local.reviewers[1], action="READ").action == "READ"
    with pytest.raises(PrdCommandError), transaction.atomic():
        authorize(local, actor=local.reviewers[1])


@pytest.mark.parametrize(
    "change",
    [
        "actor_membership",
        "technical_membership",
        "technical_project_access",
        "inactive_actor",
        "archived_product",
        "legacy_initiative",
    ],
)
def test_access_is_rechecked_against_current_native_rows(local, change):
    with transaction.atomic():
        authorize(local)
    if change == "actor_membership":
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)
    elif change == "technical_membership":
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
    elif change == "technical_project_access":
        ProjectMember.objects.filter(project=local.project, member=local.reviewers[1]).update(is_active=False)
    elif change == "inactive_actor":
        User.objects.filter(id=local.user.id).update(is_active=False)
    elif change == "archived_product":
        from plane.curve.initiative_services import cancel_initiative
        from plane.curve.product_services import archive_product

        cancel_initiative(
            request=local.request,
            workspace_slug=local.workspace.slug,
            initiative_id=local.initiative.id,
            expected_version=local.initiative.version,
            raw_idempotency_key="cancel-for-archive",
            payload={"reason": "Synthetic lifecycle test"},
        )
        local.product.refresh_from_db()
        archive_product(
            request=local.request,
            workspace_slug=local.workspace.slug,
            product_id=local.product.id,
            expected_version=local.product.version,
            raw_idempotency_key="archive-for-upload-test",
        )
        local.initiative.refresh_from_db()
    else:
        local.initiative.schema_version = "1.1"
        local.initiative.save(update_fields=["schema_version"])
    with pytest.raises(PrdCommandError), transaction.atomic():
        authorize(local)


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_LOCAL_PRD_ENABLED", False),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
        ("CURVE_SCOPED_PRD_COMMANDS_ENABLED", False),
    ],
)
def test_feature_and_environment_gates_remain_closed(local, settings, setting, value):
    setattr(settings, setting, value)
    with pytest.raises(PrdCommandError), transaction.atomic():
        authorize(local)


def test_upload_requires_current_version_and_transaction(local):
    with pytest.raises(PrdCommandError, match="LOCAL_PRD_TRANSACTION_REQUIRED"):
        authorize(local)
    with pytest.raises(PrdCommandError), transaction.atomic():
        authorize(local, version=local.initiative.version + 1)
    with pytest.raises(PrdCommandError), transaction.atomic():
        authorize(local, version=True)


def test_unassigned_workspace_admin_cannot_read_or_upload(local):
    user = User.objects.create(email="unassigned-admin@example.invalid", username="unassigned-admin")
    WorkspaceMember.objects.create(workspace=local.workspace, member=user, is_active=True, role=20)
    ProjectMember.objects.create(workspace=local.workspace, project=local.project, member=user, is_active=True, role=20)
    for action in ("READ", "UPLOAD"):
        with pytest.raises(PrdCommandError), transaction.atomic():
            authorize(local, actor=user, action=action)
