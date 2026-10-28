# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Exercise candidate lifetime SQL in rollback-only PostgreSQL transactions."""

from dataclasses import replace
from uuid import uuid4

import pytest
from django.db import connection, DatabaseError, transaction
from django.utils import timezone

from plane.curve.feature_editor_rules import FeatureEditorAction, feature_editor_reason
from plane.curve.tests.test_feature_editor_rules import GRANTED
from plane.db.models import User, Workspace, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def sql(statement, params=None):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchall() if cursor.description else None


@pytest.fixture
def membership():
    user = User.objects.create(email="editor@example.invalid", username="editor@example.invalid")
    workspace = Workspace.objects.create(name="Synthetic workspace", slug="editor-test", owner=user)
    member = WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    assert sql("SELECT to_regclass('curve_feature_membership_lifetime')")[0][0] is not None
    return member


def generation(member):
    return sql("SELECT generation FROM curve_feature_membership_lifetime WHERE membership_id=%s", [member.id])[0][0]


def test_existing_and_new_memberships_start_at_zero(membership):
    assert generation(membership) == 0
    user = User.objects.create(email="second@example.invalid", username="second@example.invalid")
    fresh = WorkspaceMember.objects.create(workspace_id=membership.workspace_id, member=user, role=15)
    assert generation(fresh) == 0


@pytest.mark.parametrize("method", ["save", "queryset", "sql"])
def test_deactivation_and_restoration_require_fresh_grant(membership, method):
    if method == "save":
        membership.is_active = False
        membership.save(update_fields=["is_active"])
    elif method == "queryset":
        WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
    else:
        sql("UPDATE workspace_members SET is_active=false WHERE id=%s", [membership.id])
    assert generation(membership) == 1
    sql("UPDATE workspace_members SET is_active=true WHERE id=%s", [membership.id])
    assert generation(membership) == 1
    facts = replace(GRANTED, membership_generation=generation(membership))
    assert (
        feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, facts) == "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED"
    )
    fresh = replace(facts, grant_membership_generation=1)
    assert feature_editor_reason(FeatureEditorAction.UPDATE_FEATURE, fresh) == "ALLOW"


def test_soft_delete_restore_and_repeated_cycles(membership):
    for expected in (1, 2):
        sql("UPDATE workspace_members SET deleted_at=%s WHERE id=%s", [timezone.now(), membership.id])
        assert generation(membership) == expected
        sql("UPDATE workspace_members SET deleted_at=NULL WHERE id=%s", [membership.id])
        assert generation(membership) == expected


def test_hard_delete_and_uuid_reuse_cannot_restore_prior_generation(membership):
    sql("DELETE FROM workspace_members WHERE id=%s", [membership.id])
    assert generation(membership) == 1
    WorkspaceMember.objects.create(
        id=membership.id, workspace_id=membership.workspace_id, member_id=membership.member_id, role=15
    )
    assert generation(membership) == 2


def test_unrelated_changes_do_not_invalidate_editors(membership):
    WorkspaceMember.objects.filter(id=membership.id).update(role=20, company_role="Synthetic role")
    assert generation(membership) == 0


def test_membership_identity_reassignment_invalidates_grants(membership):
    user = User.objects.create(email="replacement@example.invalid", username="replacement@example.invalid")
    WorkspaceMember.objects.filter(id=membership.id).update(member=user)
    assert generation(membership) == 1


def test_failed_membership_change_rolls_back_generation(membership):
    with pytest.raises(RuntimeError), transaction.atomic():
        WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
        assert generation(membership) == 1
        raise RuntimeError("synthetic rollback")
    assert generation(membership) == 0
    membership.refresh_from_db()
    assert membership.is_active


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE curve_feature_membership_lifetime SET generation=0",
        "DELETE FROM curve_feature_membership_lifetime",
        "TRUNCATE curve_feature_membership_lifetime CASCADE",
        "INSERT INTO curve_feature_membership_lifetime VALUES ('00000000-0000-0000-0000-000000000099', 0)",
    ],
)
def test_direct_lifetime_mutation_is_rejected(membership, statement):
    with pytest.raises(DatabaseError, match="FEATURE_MEMBERSHIP_LIFETIME_DIRECT_WRITE"), transaction.atomic():
        sql(statement)
    assert generation(membership) == 0


def test_primary_key_change_is_rejected(membership):
    with pytest.raises(DatabaseError, match="FEATURE_MEMBERSHIP_ID_IMMUTABLE"), transaction.atomic():
        sql("UPDATE workspace_members SET id=%s WHERE id=%s", [uuid4(), membership.id])
    assert generation(membership) == 0


def test_workspace_reassignment_invalidates_grants(membership):
    other = Workspace.objects.create(name="Other synthetic workspace", slug="other", owner_id=membership.member_id)
    WorkspaceMember.objects.filter(id=membership.id).update(workspace=other)
    assert generation(membership) == 1


def test_repeated_deactivation_does_not_advance_until_new_loss(membership):
    for _ in range(2):
        WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
        assert generation(membership) == 1
    WorkspaceMember.objects.filter(id=membership.id).update(is_active=True)
    WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
    assert generation(membership) == 2


def test_truncate_invalidates_lifetimes_and_rollback_preserves_them(membership):
    sql("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(RuntimeError), transaction.atomic():
        sql("TRUNCATE workspace_members CASCADE")
        assert generation(membership) == 1
        raise RuntimeError("synthetic rollback")
    assert generation(membership) == 0
    assert WorkspaceMember.objects.filter(id=membership.id).exists()
