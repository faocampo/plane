# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection, IntegrityError

from plane.curve.item_local_material import DESTINATION, EDITION
from plane.curve.item_creation_services import execute_item_creation
from plane.curve.models import (
    Initiative,
    RoadmapItem,
    GateAssignment,
    DomainEvent,
    OutboxEvent,
    IdempotencyRecord,
    AuditEvent,
)
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.services import OptimisticConcurrencyError, IdempotencyConflict
from plane.curve.tests.test_item_creation_facts import prepared as item_prepared
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.curve.tests.test_feature_local_material import canonical, digest
from plane.db.models import WorkspaceMember

scope = roadmap_scope
prepared = item_prepared
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def material(scope, prepared, settings, tmp_path):
    tmp_path.chmod(0o700)
    member = WorkspaceMember.objects.get(workspace=scope.workspace, member=scope.owner)
    with connection.cursor() as cursor:
        cursor.execute("SELECT generation FROM curve_feature_membership_lifetime WHERE membership_id=%s", [member.id])
        generation = cursor.fetchone()[0]
    body = b'{"type":"doc","content":[]}'
    object_id = str(uuid4())
    ref = {
        "object_id": object_id,
        "digest": digest(body),
        "size_bytes": len(body),
        "media_type": "application/json",
        "editor_schema_version": "synthetic-v1",
    }
    catalog = {
        "schema_version": EDITION,
        "generation": 1,
        "objects": {
            object_id: {
                "workspace_id": str(scope.workspace.id),
                "product_id": str(scope.product.id),
                "roadmap_id": str(prepared[0].id),
                "reference": ref,
                "access_envelope_id": str(uuid4()),
                "classification": "RESTRICTED",
                "destination": DESTINATION,
                "grants": {
                    str(scope.owner.id): {
                        "membership_id": str(member.id),
                        "membership_generation": generation,
                        "acl_generation": 1,
                        "can_read": True,
                    }
                },
            }
        },
    }
    for name, data in (("catalog.lock", b""), (object_id, body), ("catalog.json", canonical(catalog))):
        path = tmp_path / name
        path.write_bytes(data)
        path.chmod(0o600)
    settings.CURVE_LOCAL_ITEM_MATERIAL_ENABLED = True
    settings.CURVE_LOCAL_ITEM_MATERIAL_ROOT = str(tmp_path)
    return SimpleNamespace(root=tmp_path, reference=ref, catalog=catalog)


def command(scope, prepared, material, *, user=None, key="synthetic-item-create", version=None, payload=None):
    parent = prepared[0]
    value = deepcopy(prepared[3]) if payload is None else deepcopy(payload)
    value["scope_body"] = material.reference
    return execute_item_creation(
        request=SimpleNamespace(user=user or scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        roadmap_id=parent.id,
        payload=value,
        expected_version=parent.version if version is None else version,
        raw_idempotency_key=key,
    )


def counts(scope):
    return [
        m.objects.filter(workspace_id=scope.workspace.id).count()
        for m in (Initiative, RoadmapItem, GateAssignment, DomainEvent, OutboxEvent, IdempotencyRecord)
    ]


def test_joint_creation_has_two_reviewers_and_exact_replay(scope, prepared, material):
    before = counts(scope)
    parent_version = prepared[0].version
    created = command(scope, prepared, material)
    after = counts(scope)
    assert [a - b for a, b in zip(after, before)] == [1, 1, 2, 2, 2, 1]
    item = RoadmapItem.objects.get(id=created.resource_ref["resource_id"])
    initiative = Initiative.objects.get(id=created.resource_ref["initiative_ref"]["resource_id"])
    assert item.defining_initiative_id == initiative.id and initiative.roadmap_item_id == item.id
    assert (initiative.schema_version, initiative.mode, initiative.state) == ("1.2", "ROADMAP", "DRAFT")
    assert (item.status, item.declared_progress, item.progress_note, item.approved_prd_version_id) == (
        "PROPOSED",
        0,
        "",
        None,
    )
    assert item.owner_user_id == scope.owner.id
    assert set(initiative.gate_assignments.values_list("gate_type", flat=True)) == {"PRD_APPROVAL", "PLAN_APPROVAL"}
    prepared[0].refresh_from_db()
    assert prepared[0].version == parent_version
    replay = command(scope, prepared, material)
    assert replay.replayed and replay.resource_ref == created.resource_ref
    assert replay.response_digest == created.response_digest and counts(scope) == after


@pytest.mark.parametrize("actor", ["admin", "member"])
def test_only_current_roadmap_owner_can_create(scope, prepared, material, actor):
    before = counts(scope)
    with pytest.raises(CurvePolicyDenied):
        command(scope, prepared, material, user=getattr(scope, actor))
    assert counts(scope) == before


def test_stale_parent_and_changed_replay_payload_leave_no_pair(scope, prepared, material):
    before = counts(scope)
    with pytest.raises(OptimisticConcurrencyError):
        command(scope, prepared, material, version=prepared[0].version + 1)
    assert counts(scope) == before
    command(scope, prepared, material)
    before = counts(scope)
    changed = deepcopy(prepared[3])
    changed["initiative"]["title"] = "Changed request"
    with pytest.raises(IdempotencyConflict):
        command(scope, prepared, material, payload=changed)
    assert counts(scope) == before


def test_late_failure_rolls_back_pair_assignments_events_and_receipt(scope, prepared, material, monkeypatch):
    from plane.curve import item_creation_services

    original = item_creation_services._append_item_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise IntegrityError("synthetic-late-creation-failure")

    monkeypatch.setattr(item_creation_services, "_append_item_event", fail)
    before = counts(scope)
    audit_before = AuditEvent.objects.filter(workspace_id=scope.workspace.id).count()
    with pytest.raises(IntegrityError):
        command(scope, prepared, material)
    assert counts(scope) == before
    assert AuditEvent.objects.filter(workspace_id=scope.workspace.id).count() == audit_before


@pytest.mark.parametrize("who", ["owner", "member", "admin"])
def test_access_loss_blocks_creation_and_successful_replay(scope, prepared, material, who):
    command(scope, prepared, material)
    before = counts(scope)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=getattr(scope, who)).update(is_active=False)
    for key in ("synthetic-item-create", "synthetic-new-request"):
        with pytest.raises(CurvePolicyDenied) as denied:
            command(scope, prepared, material, key=key)
        expected = "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED" if who == "owner" else "ACTIVE_HUMAN_REVIEWERS_REQUIRED"
        assert denied.value.reason_codes == (expected,)
    assert counts(scope) == before


def test_membership_restoration_requires_current_explicit_scope_grant(scope, prepared, material):
    from plane.curve.item_local_material import LocalItemMaterialResolver

    created = command(scope, prepared, material)
    member = WorkspaceMember.objects.get(workspace=scope.workspace, member=scope.owner)
    WorkspaceMember.objects.filter(id=member.id).update(is_active=False)
    WorkspaceMember.objects.filter(id=member.id).update(is_active=True)
    before = counts(scope)
    with pytest.raises(CurvePolicyDenied) as denied:
        command(scope, prepared, material)
    assert denied.value.reason_codes == ("PROTECTED_MATERIAL_UNAVAILABLE",)
    with connection.cursor() as cursor:
        cursor.execute("SELECT generation FROM curve_feature_membership_lifetime WHERE membership_id=%s", [member.id])
        generation = cursor.fetchone()[0]
    updated = deepcopy(material.catalog)
    updated["generation"] += 1
    updated["objects"][material.reference["object_id"]]["grants"][str(scope.owner.id)].update(
        membership_generation=generation, acl_generation=2
    )
    with LocalItemMaterialResolver(str(material.root)) as writer:
        writer.publish_catalog(expected_digest=digest(canonical(material.catalog)), replacement=updated)
    replay = command(scope, prepared, material)
    assert replay.replayed and replay.resource_ref == created.resource_ref
    assert counts(scope) == before


def test_scope_revocation_blocks_replay_without_duplicate_effects(scope, prepared, material):
    from plane.curve.item_local_material import LocalItemMaterialResolver

    command(scope, prepared, material)
    before = counts(scope)
    updated = deepcopy(material.catalog)
    updated["generation"] += 1
    updated["objects"][material.reference["object_id"]]["grants"][str(scope.owner.id)].update(
        can_read=False, acl_generation=2
    )
    with LocalItemMaterialResolver(str(material.root)) as writer:
        writer.publish_catalog(expected_digest=digest(canonical(material.catalog)), replacement=updated)
    with pytest.raises(CurvePolicyDenied) as denied:
        command(scope, prepared, material)
    assert denied.value.reason_codes == ("PROTECTED_MATERIAL_UNAVAILABLE",)
    assert counts(scope) == before


@pytest.mark.parametrize(
    "model", [Initiative, RoadmapItem, GateAssignment, DomainEvent, OutboxEvent, IdempotencyRecord]
)
def test_failure_after_each_write_boundary_leaves_no_partial_creation(scope, prepared, material, monkeypatch, model):
    original = model.save

    def fail_after_write(row, *args, **kwargs):
        value = original(row, *args, **kwargs)
        if model is not IdempotencyRecord or row.state == "COMPLETED":
            raise IntegrityError("synthetic-write-boundary-failure")
        return value

    monkeypatch.setattr(model, "save", fail_after_write)
    before = counts(scope)
    with pytest.raises(IntegrityError):
        command(scope, prepared, material)
    assert counts(scope) == before


def test_content_change_after_writes_rolls_back_before_commit(scope, prepared, material, monkeypatch):
    from plane.curve import item_creation_services
    from plane.curve.item_local_material import ItemMaterialUnavailable

    original = item_creation_services._append_item_event

    def corrupt_after_writes(*args, **kwargs):
        original(*args, **kwargs)
        path = material.root / material.reference["object_id"]
        path.write_bytes(b"x" * material.reference["size_bytes"])

    monkeypatch.setattr(item_creation_services, "_append_item_event", corrupt_after_writes)
    before = counts(scope)
    with pytest.raises(ItemMaterialUnavailable):
        command(scope, prepared, material)
    assert counts(scope) == before


def test_deferred_reciprocal_constraint_failure_rolls_back_at_physical_commit(scope, prepared, material, monkeypatch):
    from plane.curve import item_creation_services

    original = item_creation_services._append_item_event
    write_returned = []

    def corrupt_link(receipt, item, ref, key_digest):
        original(receipt, item, ref, key_digest)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE curve_roadmap_item SET defining_initiative_id=%s WHERE id=%s", [uuid4(), item.id])

        write_returned.append(True)

    monkeypatch.setattr(item_creation_services, "_append_item_event", corrupt_link)
    before = counts(scope)
    with pytest.raises(IntegrityError):
        command(scope, prepared, material)
    assert write_returned == [True]
    assert counts(scope) == before
