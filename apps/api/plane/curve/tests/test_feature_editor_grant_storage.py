# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Grant retention and scope integrity; command authorization is separately qualified."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from plane.curve.models import Product
from plane.curve.tests.test_feature_membership_lifetime import membership as membership_fixture, sql, generation
from plane.db.models import WorkspaceMember

membership = membership_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def scope(membership):
    actor = {"actor_type": "HUMAN", "actor_id": str(membership.member_id)}
    product = Product.objects.create(
        workspace_id=membership.workspace_id,
        key="grant-test",
        name="Synthetic Product",
        timezone="UTC",
        owner_user_id=membership.member_id,
        created_by=actor,
        updated_by=actor,
    )
    assert sql("SELECT to_regclass('curve_feature_editor_grant')")[0][0] is not None
    return SimpleNamespace(membership=membership, product=product)


def grant(scope, **changes):
    member = scope.membership
    fields = dict(
        id=uuid4(),
        workspace_id=member.workspace_id,
        product_id=scope.product.id,
        member_id=member.member_id,
        membership_id=member.id,
        membership_generation=generation(member),
        granted_by=member.member_id,
        granted_at=timezone.now(),
    )
    fields.update(changes)
    sql(
        "INSERT INTO curve_feature_editor_grant ("
        + ",".join(fields)
        + ") VALUES ("
        + ",".join(["%s"] * len(fields))
        + ")",
        list(fields.values()),
    )
    return fields["id"]


def rows():
    return sql("SELECT id, membership_generation, revoked_at FROM curve_feature_editor_grant ORDER BY granted_at, id")


def revoke(scope, grant_id):
    sql(
        "UPDATE curve_feature_editor_grant SET version=2, revoked_at=%s, revoked_by=%s WHERE id=%s",
        [timezone.now(), scope.membership.member_id, grant_id],
    )


def test_grant_revoke_regrant_retains_original_history(scope):
    first = grant(scope)
    revoke(scope, first)
    second = grant(scope)
    retained = rows()
    assert len(retained) == 2
    assert retained[0][0] == first and retained[0][2] is not None
    assert retained[1][0] == second and retained[1][2] is None


def test_duplicate_active_grant_is_rejected(scope):
    first = grant(scope)
    with pytest.raises(DatabaseError), transaction.atomic():
        grant(scope)
    assert rows() == [(first, 0, None)]


def test_membership_restore_requires_new_generation_and_preserves_old_evidence(scope):
    first = grant(scope)
    WorkspaceMember.objects.filter(id=scope.membership.id).update(is_active=False)
    WorkspaceMember.objects.filter(id=scope.membership.id).update(is_active=True)
    with pytest.raises(DatabaseError, match="MEMBERSHIP_STALE"), transaction.atomic():
        grant(scope, membership_generation=0)
    second = grant(scope)
    assert rows() == [(first, 0, None), (second, 1, None)]


@pytest.mark.parametrize("field", ["workspace_id", "product_id", "member_id", "membership_id"])
def test_foreign_scope_is_rejected(scope, field):
    with pytest.raises(DatabaseError), transaction.atomic():
        grant(scope, **{field: uuid4()})
    assert rows() == []


@pytest.mark.parametrize("field", ["is_active", "deleted_at"])
def test_inactive_membership_cannot_receive_grant(scope, field):
    WorkspaceMember.objects.filter(id=scope.membership.id).update(
        **{field: False if field == "is_active" else timezone.now()}
    )
    with pytest.raises(DatabaseError, match="MEMBERSHIP_UNAVAILABLE"), transaction.atomic():
        grant(scope)
    assert rows() == []


@pytest.mark.parametrize("change", ["membership_generation=1", "granted_at=now()", "member_id=gen_random_uuid()"])
def test_grant_identity_and_attribution_are_immutable(scope, change):
    first = grant(scope)
    with pytest.raises(DatabaseError, match="GRANT_IMMUTABLE"), transaction.atomic():
        sql("UPDATE curve_feature_editor_grant SET " + change + " WHERE id=%s", [first])
    assert rows() == [(first, 0, None)]


def test_revocation_is_final_even_when_membership_is_inactive(scope):
    first = grant(scope)
    WorkspaceMember.objects.filter(id=scope.membership.id).update(is_active=False)
    revoke(scope, first)
    before = rows()
    with pytest.raises(DatabaseError, match="GRANT_IMMUTABLE"), transaction.atomic():
        sql("UPDATE curve_feature_editor_grant SET revoked_at=NULL, revoked_by=NULL WHERE id=%s", [first])
    assert rows() == before


@pytest.mark.parametrize("command", ["DELETE FROM", "TRUNCATE"])
def test_grant_history_cannot_be_deleted(scope, command):
    first = grant(scope)
    sql("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(DatabaseError, match="GRANT_HISTORY_RETAINED"), transaction.atomic():
        sql(command + " curve_feature_editor_grant")
    assert rows() == [(first, 0, None)]


def test_revocation_rolls_back_with_failed_transaction(scope):
    first = grant(scope)
    with pytest.raises(RuntimeError), transaction.atomic():
        revoke(scope, first)
        raise RuntimeError("synthetic failure")
    assert rows() == [(first, 0, None)]


def test_grant_versions_follow_retained_history(scope):
    first = grant(scope)
    assert sql("SELECT version FROM curve_feature_editor_grant WHERE id=%s", [first]) == [(1,)]
    revoke(scope, first)
    assert sql("SELECT version FROM curve_feature_editor_grant WHERE id=%s", [first]) == [(2,)]
    second = grant(scope)
    assert sql("SELECT version FROM curve_feature_editor_grant WHERE id=%s", [second]) == [(1,)]


@pytest.mark.parametrize("version", [0, 2, 3])
def test_new_grant_cannot_skip_initial_version(scope, version):
    with pytest.raises(DatabaseError, match="GRANT_MUST_START_ACTIVE"), transaction.atomic():
        grant(scope, version=version)
    assert rows() == []


@pytest.mark.parametrize("version", [0, 1, 3])
def test_revocation_requires_next_version(scope, version):
    first = grant(scope)
    with pytest.raises(DatabaseError, match="GRANT_IMMUTABLE"), transaction.atomic():
        sql(
            "UPDATE curve_feature_editor_grant SET version=%s, revoked_at=%s, revoked_by=%s WHERE id=%s",
            [version, timezone.now(), scope.membership.member_id, first],
        )
    assert sql("SELECT version, revoked_at FROM curve_feature_editor_grant WHERE id=%s", [first]) == [(1, None)]


def test_revoked_grant_version_cannot_rewind(scope):
    first = grant(scope)
    revoke(scope, first)
    with pytest.raises(DatabaseError, match="GRANT_IMMUTABLE"), transaction.atomic():
        sql("UPDATE curve_feature_editor_grant SET version=1 WHERE id=%s", [first])
    assert sql("SELECT version FROM curve_feature_editor_grant WHERE id=%s", [first]) == [(2,)]
