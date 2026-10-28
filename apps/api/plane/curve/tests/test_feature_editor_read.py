# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from types import SimpleNamespace
from uuid import uuid4

import pytest

from plane.curve.feature_editor_read import read_feature_editors
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.tests.test_feature_editor_commands import command
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def read(scope, user=None, **kwargs):
    return read_feature_editors(
        request=SimpleNamespace(user=user or scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        **kwargs,
    )


@pytest.mark.parametrize("actor", ["owner", "admin"])
def test_managers_read_active_grant(scope, actor):
    result = command(scope)
    data = read(scope, getattr(scope, actor))
    assert data["can_manage_editors"] is True
    assert data["next_cursor"] is None
    assert len(data["results"]) == 1
    assert data["results"][0]["status"] == "ACTIVE"
    assert data["results"][0]["id"] == result.resource_ref["resource_id"]


def test_editor_cannot_read_management_list(scope):
    command(scope)
    with pytest.raises(CurvePolicyResourceNotFound):
        read(scope, scope.member)


def test_restoration_does_not_show_old_grant_as_active(scope):
    old = command(scope)
    members = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    members.update(is_active=False)
    members.update(is_active=True)
    assert read(scope, grant_id=old.resource_ref["resource_id"])["status"] == "MEMBERSHIP_LOST"
    new = command(scope, key="synthetic-fresh-editor")
    assert read(scope, grant_id=new.resource_ref["resource_id"])["status"] == "ACTIVE"


def test_revoked_grant_retains_status_and_version(scope):
    result = command(scope)
    command(scope, grant_id=result.resource_ref["resource_id"], version=1, key="synthetic-revoke")
    data = read(scope, grant_id=result.resource_ref["resource_id"])
    assert data["status"] == "REVOKED"
    assert data["version"] == 2
    assert data["revoked_by"] == str(scope.owner.id)


def test_missing_scoped_grant_is_hidden(scope):
    command(scope)
    with pytest.raises(CurvePolicyResourceNotFound):
        read(scope, grant_id=uuid4())


def test_pagination_has_no_duplicate_grants(scope):
    command(scope)
    command(scope, target=scope.admin, key="synthetic-admin-editor")
    first = read(scope, page_size=1)
    second = read(scope, page_size=1, after=first["next_cursor"])
    assert first["next_cursor"] is not None
    assert second["next_cursor"] is None
    assert first["results"][0]["id"] != second["results"][0]["id"]


def test_removed_manager_cannot_read_retained_history(scope):
    command(scope)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    with pytest.raises(CurvePolicyResourceNotFound):
        read(scope)
