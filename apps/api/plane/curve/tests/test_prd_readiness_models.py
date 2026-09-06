# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from plane.curve.models import PrdReadinessRecord, AuditEvent, ImmutableRecordError
from plane.curve.policy_services import execute_authorized_mutation
from plane.curve.prd_policy_context import build_prd_policy_context
from plane.curve.prd_metadata_validation import instant
from plane.curve.prd_readiness import PrdReadinessError, evaluate_prd_readiness
from plane.curve.prd_readiness_repository import append_prd_readiness_report
from plane.curve.tests.test_prd_accepted_commands import fixture as command_fixture, accept
from plane.curve.tests.test_prd_policy_context import resolver
from plane.curve.tests.test_prd_readiness import scenario, mutate

fixture = command_fixture
pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def report_for(fixture, blocked=False):
    binding, initiative, checkpoint, _, actor, workspace = fixture
    args = scenario.__wrapped__()
    args.update(
        id=str(uuid.uuid4()),
        workspace_id=str(workspace.id),
        initiative_id=str(initiative.id),
        initiative_version=initiative.version,
        evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
        active_human_ids=[str(actor.id)],
        checked_at=instant(timezone.now()),
    )
    for kind in ("prd", "idea_brief"):
        args[kind] = replace(args[kind], workspace_id=str(workspace.id), initiative_id=str(initiative.id))
    args["prd"] = replace(
        args["prd"],
        binding_id=str(binding.id),
        provider_file_id=binding.provider_file_id,
        provider_version=binding.current_provider_version,
    )
    args["idea_brief"] = replace(args["idea_brief"], artifact_version_id=str(uuid.uuid4()))
    mutate(
        args, "prd", lambda content: content["document_properties"].__setitem__("documentId", binding.provider_file_id)
    )
    args["inventory"].update(
        workspace_id=str(workspace.id),
        initiative_id=str(initiative.id),
        checked_at=args["checked_at"],
        complete=not blocked,
    )
    return evaluate_prd_readiness(**args)


def append(fixture, report, after=None):
    _, initiative, _, _, actor, workspace = fixture

    def context():
        return build_prd_policy_context(
            request=SimpleNamespace(user=actor),
            workspace_slug=workspace.slug,
            initiative_id=initiative.id,
            action="CURVE.PRD.SUBMIT",
            acl_resolver=resolver,
            for_update=True,
        )

    def callback(receipt, _):
        record = append_prd_readiness_report(authorization_receipt=receipt, report=report)
        if after:
            after(record, receipt)
        return record

    return execute_authorized_mutation(context_builder=context, mutation_callback=callback)


def raw_insert(template, payload_changes=None, **columns):
    identifier = uuid.uuid4()
    payload = template.as_record()
    payload.update(id=str(identifier), **(payload_changes or {}))
    values = dict(
        id=identifier,
        workspace_id=template.workspace_id,
        initiative_id=template.initiative_id,
        binding_id=template.binding_id,
        policy_decision_id=template.policy_decision_id,
        payload=json.dumps(payload),
        recorded_at=timezone.now(),
    )
    values.update(columns)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_prd_readiness_record "
            "(id,workspace_id,initiative_id,binding_id,policy_decision_id,payload,recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)",
            [
                values[key]
                for key in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "binding_id",
                    "policy_decision_id",
                    "payload",
                    "recorded_at",
                )
            ],
        )


@pytest.mark.parametrize("blocked", [False, True])
def test_ready_and_blocked_reports_are_scoped_immutable_and_audited(fixture, blocked):
    report = report_for(fixture, blocked)
    record = append(fixture, report)
    assert record.as_record() == report.as_dict()
    assert record.payload["status"] == ("BLOCKED" if blocked else "READY")
    assert PrdReadinessRecord.objects.find_by_id(workspace_id=uuid.uuid4(), record_id=record.id) is None
    audit = AuditEvent.objects.get(action="CURVE.PRD.READINESS_RECORDED")
    assert audit.policy_decision_ref["resource_id"] == str(record.policy_decision_id)
    assert (
        audit.actor == record.policy_decision.subject and audit.correlation_id == record.policy_decision.correlation_id
    )
    assert "protected definition" not in json.dumps(record.as_record())
    detached = record.as_record()
    detached["reasons"].append("changed")
    assert record.payload["reasons"] != detached["reasons"]
    for action in (
        record.save,
        record.delete,
        lambda: PrdReadinessRecord.objects.filter(id=record.id).update(payload={}),
        lambda: PrdReadinessRecord.objects.bulk_create([record]),
    ):
        with pytest.raises(ImmutableRecordError):
            action()


def test_repository_requires_current_transaction_and_active_policy_receipt(fixture):
    report = report_for(fixture)
    with pytest.raises((ValidationError, PermissionError)):
        append_prd_readiness_report(authorization_receipt=None, report=report)
    captured = []
    append(fixture, report, after=lambda _, receipt: captured.append(receipt))
    with pytest.raises(PermissionError):
        append_prd_readiness_report(authorization_receipt=captured[0], report=report_for(fixture))


def test_outer_failure_rolls_back_report_and_linked_audit(fixture):
    def fail(*_):
        raise RuntimeError("synthetic failure")

    with pytest.raises(RuntimeError, match="synthetic failure"):
        append(fixture, report_for(fixture), after=fail)
    assert PrdReadinessRecord.objects.count() == 0
    assert not AuditEvent.objects.filter(action="CURVE.PRD.READINESS_RECORDED").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_body", "synthetic protected sentinel"),
        ("profile_digest", "sha256:" + "0" * 64),
        ("reasons", ["synthetic protected sentinel"]),
        ("reasons", [{}]),
        ("status", "READY_EXTRA"),
        ("status", {}),
        ("initiative_version", True),
        ("initiative_version", 0),
        ("content_digest", "invalid"),
        ("idea_brief_digest", "invalid"),
        ("inventory_digest", "invalid"),
        ("checked_at", "2026-01-01T00:00:60Z"),
        ("checked_at", "2030-01-01T00:00:00Z"),
        ("idea_brief_version_id", "not-a-uuid"),
        ("evidence_snapshot_id", "not-a-uuid"),
        ("provider_version", "value with spaces"),
        ("provider_file_id", "synthetic-other"),
    ],
)
def test_orm_and_database_reject_invalid_report_payloads(fixture, field, value):
    original = append(fixture, report_for(fixture))
    payload = original.as_record()
    payload.update(id=str(uuid.uuid4()), **{field: value})
    with pytest.raises((ValidationError, PrdReadinessError)):
        PrdReadinessRecord.objects.create(
            id=uuid.UUID(payload["id"]),
            workspace_id=original.workspace_id,
            initiative_id=original.initiative_id,
            binding_id=original.binding_id,
            policy_decision_id=original.policy_decision_id,
            payload=payload,
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_insert(original, {field: value})


@pytest.mark.parametrize("column", ["workspace_id", "initiative_id", "binding_id", "policy_decision_id"])
def test_database_rejects_scope_or_reference_substitution(fixture, column):
    original = append(fixture, report_for(fixture))
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_insert(original, **{column: uuid.uuid4()})


def test_duplicate_reason_codes_and_mismatched_status_fail_database_guard(fixture):
    original = append(fixture, report_for(fixture))
    for changed in (
        {"status": "BLOCKED", "reasons": []},
        {"status": "READY", "reasons": ["BLOCKERS_UNRESOLVED"]},
        {"status": "BLOCKED", "reasons": ["BLOCKERS_UNRESOLVED", "BLOCKERS_UNRESOLVED"]},
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            raw_insert(original, changed)


def test_another_action_policy_cannot_authorize_readiness_storage(fixture):
    original = append(fixture, report_for(fixture))
    command, _ = accept(fixture)
    policy_id = command.operation.policy_version_ref["resource_id"]
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_insert(original, policy_decision_id=policy_id)


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_raw_report_history_cannot_be_changed(fixture, verb):
    record = append(fixture, report_for(fixture))
    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            sql = (
                "UPDATE curve_prd_readiness_record SET payload='{}'::jsonb WHERE id=%s"
                if verb == "UPDATE"
                else "DELETE FROM curve_prd_readiness_record WHERE id=%s"
            )
            cursor.execute(sql, [record.id])


@pytest.mark.django_db(transaction=True)
def test_readiness_migration_reverses_empty_and_preserves_retained_history(fixture):
    executor = MigrationExecutor(connection)
    executor.migrate([("curve", "0015_prd_accepted_command")])
    executor = MigrationExecutor(connection)
    executor.migrate([("curve", "0016_prd_readiness_record")])
    record = append(fixture, report_for(fixture))
    with pytest.raises(DatabaseError):
        MigrationExecutor(connection).migrate([("curve", "0015_prd_accepted_command")])
    assert PrdReadinessRecord.objects.filter(id=record.id).exists()


@pytest.mark.parametrize("same_workspace", [False, True])
def test_existing_foreign_binding_cannot_be_substituted(fixture, same_workspace):
    from plane.curve.models import ExternalDocumentBinding, Initiative
    from plane.curve.tests.test_external_document_models import binding_values, initiative_values

    original = append(fixture, report_for(fixture))
    if same_workspace:
        other_initiative = Initiative.objects.create(**initiative_values(original.workspace_id))
        binding = fixture[0]
        foreign = ExternalDocumentBinding.objects.create(
            workspace_id=original.workspace_id,
            initiative=other_initiative,
            provider_connection=binding.provider_connection,
            provider_file_id="synthetic-other-document",
            provider_container_id=binding.provider_container_id,
            canonical_url="https://docs.example.invalid/documents/synthetic-other-document",
            current_provider_version=binding.current_provider_version,
            current_modified_at=timezone.now(),
            created_by=binding.created_by,
        )
    else:
        foreign = ExternalDocumentBinding.objects.create(**binding_values())
    with pytest.raises(DatabaseError), transaction.atomic():
        raw_insert(
            original,
            {"prd_binding_id": str(foreign.id), "provider_file_id": foreign.provider_file_id},
            binding_id=foreign.id,
        )


def test_duplicate_report_identity_cannot_append_or_rewrite_history(fixture):
    report = report_for(fixture)
    original = append(fixture, report)
    with pytest.raises(DatabaseError):
        append(fixture, report)
    assert PrdReadinessRecord.objects.count() == 1
    original.refresh_from_db()
    assert original.payload == report.as_dict()
    assert AuditEvent.objects.filter(action="CURVE.PRD.READINESS_RECORDED").count() == 1


def test_metadata_composition_requires_the_owning_command_audit(fixture, monkeypatch):
    from plane.curve import prd_readiness_repository

    # The command kernel refuses to commit metadata if the owning command omits
    # its linked audit. The metadata-only helper cannot waive that invariant.
    monkeypatch.setattr(
        __import__(__name__, fromlist=["append_prd_readiness_report"]),
        "append_prd_readiness_report",
        prd_readiness_repository.record_prd_readiness_metadata,
    )
    with pytest.raises(RuntimeError, match="exactly one linked audit"):
        append(fixture, report_for(fixture))
    assert PrdReadinessRecord.objects.count() == 0
