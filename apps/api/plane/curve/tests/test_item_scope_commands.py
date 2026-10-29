# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import IntegrityError, connection

from plane.curve.item_scope_services import execute_item_scope_preparation
from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.services import IdempotencyConflict, OptimisticConcurrencyError
from plane.curve.tests.test_item_scope_authority_native import (
    scope as native_scope,
    parent as native_parent,
    material as native_material,
)
from plane.db.models import WorkspaceMember

scope, parent, material = native_scope, native_parent, native_material
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def enabled(settings, material):
    settings.CURVE_ITEM_SCOPE_PREPARATION_ENABLED = True
    settings.CURVE_LOCAL_ITEM_MATERIAL_ENABLED = True
    settings.CURVE_LOCAL_ITEM_MATERIAL_ROOT = str(material)


def execute(scope, parent, **changes):
    args = dict(
        request=SimpleNamespace(user=scope.member, headers={}),
        workspace_slug=scope.workspace.slug,
        product_id=scope.product.id,
        roadmap_id=parent.id,
        payload={"body": "Synthetic outcome"},
        expected_version=parent.version,
        raw_idempotency_key="synthetic-scope-preparation",
    )
    args.update(changes)
    return execute_item_scope_preparation(**args)


def counts():
    return [model.objects.count() for model in (IdempotencyRecord, DomainEvent, OutboxEvent)]


def test_prepare_and_replay_retain_one_object_one_event_and_fresh_decisions(scope, parent, material):
    first = execute(scope, parent)
    second = execute(scope, parent)
    assert first.resource_ref == second.resource_ref
    assert not first.replayed and second.replayed
    assert counts() == [1, 1, 1]
    assert PolicyDecision.objects.count() == 2
    assert list(AuditEvent.objects.order_by("sequence").values_list("outcome", flat=True)) == ["SUCCEEDED", "NO_EFFECT"]
    assert len(json.loads((material / "catalog.json").read_bytes())["objects"]) == 1
    assert "Synthetic outcome" not in json.dumps(list(DomainEvent.objects.values_list("payload", flat=True)))


def test_stale_parent_has_no_material_or_receipt_effect(scope, parent, material):
    with pytest.raises(OptimisticConcurrencyError):
        execute(scope, parent, expected_version=parent.version + 1)
    assert counts() == [0, 0, 0]
    assert not json.loads((material / "catalog.json").read_bytes())["objects"]
    assert AuditEvent.objects.get().outcome == "NO_EFFECT"


def test_same_key_different_body_is_rejected(scope, parent, material):
    execute(scope, parent)
    with pytest.raises(IdempotencyConflict):
        execute(scope, parent, payload={"body": "Changed outcome"})
    assert counts() == [1, 1, 1]
    assert len(json.loads((material / "catalog.json").read_bytes())["objects"]) == 1


@pytest.mark.parametrize("change", ["removed", "restored", "inactive", "bot", "disabled"])
def test_replay_rechecks_current_authority_and_original_material(scope, parent, settings, change):
    execute(scope, parent)
    membership = WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.member)
    if change in {"removed", "restored"}:
        membership.update(is_active=False)
        if change == "restored":
            membership.update(is_active=True)
    elif change in {"inactive", "bot"}:
        field = "is_active" if change == "inactive" else "is_bot"
        setattr(scope.member, field, change == "bot")
        scope.member.save(update_fields=[field])
    else:
        settings.CURVE_ITEM_SCOPE_PREPARATION_ENABLED = False
    with pytest.raises(CurvePolicyDenied):
        execute(scope, parent)
    assert counts() == [1, 1, 1]
    assert AuditEvent.objects.filter(outcome="DENIED").count() == 1


def test_policy_denial_precedes_external_writes(scope, parent, material):
    with pytest.raises(CurvePolicyDenied):
        execute(scope, parent, request=SimpleNamespace(user=scope.admin, headers={}))
    assert counts() == [0, 0, 0]
    assert not json.loads((material / "catalog.json").read_bytes())["objects"]


def test_late_database_failure_retains_private_orphan_without_success_receipt(scope, parent, material):
    with patch("plane.curve.item_scope_services.OutboxEvent.objects.create", side_effect=IntegrityError("synthetic")):
        with pytest.raises(IntegrityError):
            execute(scope, parent)
    assert counts() == [0, 0, 0]
    assert PolicyDecision.objects.count() == AuditEvent.objects.count() == 0
    assert len(json.loads((material / "catalog.json").read_bytes())["objects"]) == 1
    assert execute(scope, parent).response_status == 201
    assert counts() == [1, 1, 1]


def test_actual_commit_failure_rolls_back_receipt_and_event(scope, parent):
    with patch.object(connection, "commit", side_effect=IntegrityError("synthetic commit failure")):
        with pytest.raises(IntegrityError):
            execute(scope, parent)
    assert counts() == [0, 0, 0]
    assert PolicyDecision.objects.count() == AuditEvent.objects.count() == 0


def test_material_lease_survives_physical_commit(scope, parent, material):
    import fcntl
    from plane.curve.item_local_material import ItemMaterialUnavailable, LocalItemMaterialResolver

    original_commit = connection.commit
    observed = []

    def commit():
        with LocalItemMaterialResolver(str(material)) as competing:
            with pytest.raises(ItemMaterialUnavailable):
                with competing._lock(fcntl.LOCK_EX):
                    pytest.fail("writer acquired lock before physical commit")
        observed.append(True)
        return original_commit()

    with patch.object(connection, "commit", side_effect=commit):
        execute(scope, parent)
    assert observed == [True]
    assert counts() == [1, 1, 1]


def test_prepared_event_conforms_to_closed_schema(scope, parent):
    from pathlib import Path
    from jsonschema import Draft202012Validator, FormatChecker

    execute(scope, parent)
    schema = json.loads((Path(__file__).parents[1] / "items/scope-prepared-v1.schema.json").read_bytes())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(DomainEvent.objects.get().payload)


def test_retained_preparation_evidence_prevents_schema_reverse(scope, parent):
    from importlib import import_module
    from django.db import transaction

    execute(scope, parent)
    migration = import_module("plane.curve.migrations.0051_item_scope")
    with transaction.atomic(), connection.schema_editor() as editor:
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
            migration.require_compatible_reverse(None, editor)
    assert counts() == [1, 1, 1]


def test_changed_qualification_seal_prevents_external_preparation(scope, parent, material):
    from django.db import transaction
    from plane.curve.prd_commands import PrdCommandError

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE curve_item_scope_coverage DISABLE TRIGGER curve_item_scope_coverage_immutable")
            cursor.execute("UPDATE curve_item_scope_coverage SET catalog_digest=%s", ["sha256:" + "0" * 64])
            cursor.execute("ALTER TABLE curve_item_scope_coverage ENABLE TRIGGER curve_item_scope_coverage_immutable")
        # Durable commands cannot run nested, so exercise the identical mandatory
        # qualification gate directly and ensure the storage remains untouched.
        from plane.curve.scope_reopening_qualification import require_item_scope_qualification

        with pytest.raises(PrdCommandError):
            require_item_scope_qualification()
        transaction.set_rollback(True)
    assert counts() == [0, 0, 0]
    assert not json.loads((material / "catalog.json").read_bytes())["objects"]
    assert execute(scope, parent).response_status == 201
