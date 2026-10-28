# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection

from plane.curve.feature_local_material import DESTINATION, EDITION, LocalFeatureMaterialResolver
from plane.curve.feature_services import execute_feature_command
from plane.curve.feature_read import read_features
from plane.curve.models import DomainEvent, Feature
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.tests.test_feature_commands import counts
from plane.curve.tests.test_feature_local_material import canonical, digest
from plane.curve.tests.test_roadmap_commands import scope as roadmap_scope
from plane.db.models import WorkspaceMember

scope = roadmap_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def material(scope, settings, tmp_path):
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
    settings.CURVE_LOCAL_FEATURE_MATERIAL_ENABLED = True
    settings.CURVE_LOCAL_FEATURE_MATERIAL_ROOT = str(tmp_path)
    return SimpleNamespace(root=tmp_path, reference=ref, catalog=catalog)


def command(scope, material, *, feature=None, clear=False, key="synthetic-protected-create"):
    return execute_feature_command(
        request=SimpleNamespace(user=scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        feature_id=feature,
        expected_version=1 if feature else None,
        action="UPDATE_FEATURE" if feature else "CREATE_FEATURE",
        payload={"name": "Protected Feature", "description": None if clear else material.reference},
        raw_idempotency_key=key,
    )


def revoke(scope, material):
    changed = deepcopy(material.catalog)
    changed["generation"] = 2
    changed["objects"][material.reference["object_id"]]["grants"][str(scope.owner.id)].update(
        can_read=False, acl_generation=2
    )
    with LocalFeatureMaterialResolver(str(material.root)) as resolver:
        resolver.publish_catalog(replacement=changed, expected_digest=digest(canonical(material.catalog)))


def test_material_classification_and_current_read_access(scope, material):
    result = command(scope, material)
    assert DomainEvent.objects.get(aggregate_id=result.resource_ref["resource_id"]).classification == "RESTRICTED"
    args = dict(
        request=SimpleNamespace(user=scope.owner, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
    )
    assert read_features(**args, feature_id=result.resource_ref["resource_id"])["description"] == material.reference
    revoke(scope, material)
    assert len(read_features(**args)["results"]) == 1
    with pytest.raises(CurvePolicyDenied):
        read_features(**args, feature_id=result.resource_ref["resource_id"])
    before = counts(scope)
    with pytest.raises(CurvePolicyDenied):
        command(scope, material)
    with pytest.raises(CurvePolicyDenied):
        command(scope, material, feature=result.resource_ref["resource_id"], clear=True, key="synthetic-clear")
    assert counts(scope) == before
    assert Feature.objects.get(id=result.resource_ref["resource_id"]).description == material.reference


def test_mismatched_protected_bytes_leave_no_command_effect(scope, material):
    (material.root / material.reference["object_id"]).write_bytes(b"synthetic-changed")
    with pytest.raises(CurvePolicyDenied):
        command(scope, material)
    assert counts(scope) == [0, 0, 0, 0]


def test_changed_material_before_commit_rolls_back_all_success_effects(scope, material, monkeypatch):
    from plane.curve import feature_services
    from plane.curve.feature_local_material import FeatureMaterialUnavailable
    from plane.curve.models import AuditEvent

    original = feature_services._event

    def change_after_event(*args, **kwargs):
        original(*args, **kwargs)
        (material.root / material.reference["object_id"]).write_bytes(b"synthetic-concurrent-content-change")

    monkeypatch.setattr(feature_services, "_event", change_after_event)
    with pytest.raises(FeatureMaterialUnavailable):
        command(scope, material)
    assert counts(scope) == [0, 0, 0, 0]
    assert list(AuditEvent.objects.filter(workspace_id=scope.workspace.id).values_list("outcome", flat=True)) == [
        "NO_EFFECT"
    ]


@pytest.mark.parametrize("operation", ["create", "read"])
def test_outer_transaction_cannot_outlive_the_material_lease(scope, material, operation):
    from django.db import transaction

    created = command(scope, material)
    before = counts(scope)
    with transaction.atomic():
        with pytest.raises(RuntimeError, match="durable atomic block cannot be nested"):
            if operation == "create":
                command(scope, material, key="synthetic-nested-create")
            else:
                read_features(
                    request=SimpleNamespace(user=scope.owner, headers={}),
                    workspace_slug=scope.workspace.slug,
                    product_id=scope.product.id,
                    feature_id=created.resource_ref["resource_id"],
                )
    assert counts(scope) == before
