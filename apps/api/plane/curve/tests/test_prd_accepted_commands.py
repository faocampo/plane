# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
import uuid
from types import SimpleNamespace
from dataclasses import replace

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from plane.curve.models import PrdAcceptedCommand, GateAssignment, Operation, OutboxEvent, ImmutableRecordError
from plane.curve.policy_services import execute_authorized_mutation
from plane.curve.prd_policy_context import build_prd_policy_context
from plane.curve.prd_commands import parse_prd_command
from plane.curve.prd_command_repository import record_accepted_prd_command
from plane.curve.services import _create_operation_authorized
from plane.curve.tests.test_prd_lifecycle_repository import review_fixture
from plane.curve.tests.test_prd_policy_context import resolver
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


@pytest.fixture
def fixture(settings):
    binding, _, initiative, checkpoint, gate = review_fixture()
    users = {}
    for assignment in GateAssignment.objects.filter(initiative=initiative):
        user = User.objects.create(
            username=assignment.gate_type.lower(),
            id=assignment.approver_user_id,
            email=f"{assignment.gate_type.lower()}@example.invalid",
        )
        users[user.id] = user
    actor = users[gate.approver_user_id]
    workspace = Workspace.objects.create(
        id=initiative.workspace_id, slug="command-fixture", name="Synthetic", owner=actor
    )
    for user in users.values():
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = {workspace.slug}
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_PRD_COMMANDS_ENABLED = True
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "synthetic-recorder"
    return binding, initiative, checkpoint, gate, actor, workspace


def accept(fixture, action="APPROVE", *, save=True, fail=False, mismatch_key=False):
    binding, initiative, checkpoint, gate, actor, workspace = fixture
    body = dict(
        gate_assignment_id=str(gate.id),
        checkpoint_id=str(checkpoint.id),
        artifact_version_id=str(checkpoint.artifact_version_id),
        content_digest=checkpoint.content_digest,
        provider_version=checkpoint.provider_version,
        evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
        confirmed_risk_tier=initiative.risk_tier,
        rationale="Synthetic private rationale 🧪",
    )
    route = "approve"
    if action == "SUBMIT":
        route = "submit"
        body = dict(
            external_document_binding_id=str(binding.id),
            evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
            completeness_check_id=str(uuid.uuid4()),
        )
    elif action != "APPROVE":
        route = "return-for-revision"
        body["decision"] = "CHANGES_REQUESTED" if action == "REQUEST_CHANGES" else "REJECTED"
    command = parse_prd_command(
        route=route,
        body=json.dumps(body).encode(),
        if_match=f'"{initiative.version}"',
        idempotency_key=str(uuid.uuid4()),
    )
    request = SimpleNamespace(user=actor)

    def context():
        return build_prd_policy_context(
            request=request,
            workspace_slug=workspace.slug,
            initiative_id=initiative.id,
            action=command.action,
            acl_resolver=resolver,
            for_update=True,
        )

    def callback(receipt, _):
        result = _create_operation_authorized(
            authorization_receipt=receipt,
            authorization_action=command.action,
            workspace_id=workspace.id,
            principal_scope=f"HUMAN:{actor.id}",
            command_scope=f"PRD_{action}:{initiative.id}",
            raw_idempotency_key=command.idempotency_key,
            canonical_request=command.operation_request_identity(),
            operation_type="WORKFLOW_COMMAND",
            command_type=f"PRD_{action}",
            target=dict(receipt.resource_ref),
            actor={"actor_type": "HUMAN", "actor_id": str(actor.id)},
            correlation_id="synthetic-command",
            destination="CURVE_PRD_CANDIDATE_V1",
        )
        protected = {}
        if command.rationale_bytes is not None:
            protected = dict(
                rationale_ref=dict(
                    object_id=str(uuid.uuid4()),
                    digest="sha256:" + hashlib.sha256(command.rationale_bytes).hexdigest(),
                    size_bytes=len(command.rationale_bytes),
                    media_type="text/plain; charset=utf-8",
                ),
                access_envelope_id=uuid.uuid4(),
                retention_policy_version_id=uuid.uuid4(),
            )
        record = PrdAcceptedCommand.from_command(command=command, operation=result.operation, **protected)
        if save:
            record = record_accepted_prd_command(
                authorization_receipt=receipt,
                command=replace(command, idempotency_key="different-key") if mismatch_key else command,
                operation=result.operation,
                **protected,
            )
        if fail:
            raise RuntimeError("Synthetic transaction failure")
        return record, command

    return execute_authorized_mutation(context_builder=context, mutation_callback=callback)


@pytest.mark.parametrize("action", ["SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"])
def test_all_commands_round_trip_without_inline_rationale(fixture, action):
    record, command = accept(fixture, action)
    loaded = PrdAcceptedCommand.objects.get(operation_id=record.operation_id)
    payload = loaded.verified_payload(rationale_bytes=command.rationale_bytes)
    assert loaded.action == command.action and loaded.request_digest == command.request_digest
    assert "rationale" not in loaded.subject
    assert payload.get("rationale") == (None if action == "SUBMIT" else command.rationale_bytes.decode())
    assert "Synthetic private rationale" not in json.dumps(loaded.subject)
    assert "Synthetic private rationale" not in json.dumps(Operation.objects.get(id=record.operation_id).target)
    assert OutboxEvent.objects.count() == 1
    assert (
        PrdAcceptedCommand.objects.find_by_id(workspace_id=record.workspace_id, record_id=record.operation_id) == loaded
    )
    assert PrdAcceptedCommand.objects.find_by_id(workspace_id=uuid.uuid4(), record_id=record.operation_id) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", {"rationale": "Synthetic protected sentinel"}),
        ("subject", []),
        ("subject", {"checkpoint_id": True}),
        ("rationale_digest", "invalid"),
        ("rationale_size_bytes", 0),
        ("rationale_access_envelope_id", None),
        ("expected_version", 99),
        ("actor_id", uuid.UUID(int=12)),
        ("workspace_id", uuid.UUID(int=13)),
    ],
)
def test_raw_insert_rejects_invalid_durable_metadata(fixture, field, value):
    record, _ = accept(fixture, save=False)
    setattr(record, field, value)
    with pytest.raises(DatabaseError), transaction.atomic():
        record.save_base(force_insert=True)
    assert PrdAcceptedCommand.objects.count() == 0


@pytest.mark.parametrize(
    "key",
    [
        "gate_assignment_id",
        "checkpoint_id",
        "artifact_version_id",
        "evidence_snapshot_id",
        "content_digest",
        "provider_version",
        "confirmed_risk_tier",
    ],
)
def test_raw_review_subject_substitution_is_rejected(fixture, key):
    record, _ = accept(fixture, save=False)
    record.subject[key] = str(uuid.uuid4()) if key.endswith("_id") else "changed"
    with pytest.raises(DatabaseError), transaction.atomic():
        record.save_base(force_insert=True)


def test_command_and_outbox_roll_back_together(fixture):
    with pytest.raises(RuntimeError, match="Synthetic transaction failure"):
        accept(fixture, fail=True)
    assert PrdAcceptedCommand.objects.count() == Operation.objects.count() == OutboxEvent.objects.count() == 0


def test_immutable_orm_and_raw_database_history(fixture):
    record, _ = accept(fixture)
    with pytest.raises(ImmutableRecordError):
        record.delete()
    with pytest.raises(ImmutableRecordError):
        record.save()
    with pytest.raises(ImmutableRecordError):
        PrdAcceptedCommand.objects.filter(operation_id=record.operation_id).update(action="CURVE.PRD.REJECT")
    for statement in [
        "DELETE FROM curve_prd_accepted_command WHERE operation_id=%s",
        "UPDATE curve_prd_accepted_command SET request_digest=request_digest WHERE operation_id=%s",
    ]:
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement, [record.operation_id])


def test_operation_cannot_move_retained_command_to_another_workspace(fixture):
    record, _ = accept(fixture)
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE curve_operation SET workspace_id=%s WHERE id=%s", [uuid.uuid4(), record.operation_id])


def test_rationale_integrity_and_full_original_request_are_verified(fixture):
    record, command = accept(fixture)
    with pytest.raises(ValidationError, match="PRD_COMMAND_RATIONALE_MISMATCH"):
        record.verified_payload(rationale_bytes=b"changed")
    record.subject["provider_version"] = "changed"
    with pytest.raises(ValidationError, match="PRD_COMMAND_DIGEST_MISMATCH"):
        record.verified_payload(rationale_bytes=command.rationale_bytes)


def test_invalid_utf8_protected_bytes_do_not_expose_decoding_context(fixture):
    record, _ = accept(fixture)
    record.rationale_digest = "sha256:" + hashlib.sha256(b"\xff").hexdigest()
    record.rationale_size_bytes = 1
    with pytest.raises(ValidationError) as error:
        record.verified_payload(rationale_bytes=b"\xff")
    assert error.value.__suppress_context__


def test_mismatched_operation_idempotency_rolls_back_acceptance(fixture):
    with pytest.raises(ValidationError, match="PRD_COMMAND_IDEMPOTENCY_MISMATCH"):
        accept(fixture, mismatch_key=True)
    assert PrdAcceptedCommand.objects.count() == Operation.objects.count() == OutboxEvent.objects.count() == 0


def test_append_requires_active_matching_receipt(fixture):
    record, command = accept(fixture, save=False)
    with pytest.raises(PermissionError):
        record_accepted_prd_command(authorization_receipt=None, command=command, operation=record.operation)
    assert PrdAcceptedCommand.objects.count() == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("command_type", "PRD_REJECT"),
        ("target", {}),
        ("created_by", {"actor_type": "SERVICE", "actor_id": "synthetic"}),
        ("policy_version_ref", None),
        ("effective_principal", {"actor_type": "HUMAN", "actor_id": "another-human"}),
    ],
)
def test_raw_command_cannot_attach_to_mismatched_operation(fixture, field, value):
    record, _ = accept(fixture, save=False)
    with connection.cursor() as cursor:
        parameter = json.dumps(value) if isinstance(value, dict) else value
        cursor.execute(
            f"UPDATE curve_operation SET {connection.ops.quote_name(field)}=%s WHERE id=%s",
            [parameter, record.operation_id],
        )
    with pytest.raises(DatabaseError, match="PRD_COMMAND_(OPERATION|POLICY)_MISMATCH"), transaction.atomic():
        record.save_base(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_migration_reverses_empty_but_preserves_retained_commands(fixture):
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    previous = [("curve", "0014_prd_policy_identity")]
    try:
        MigrationExecutor(connection).migrate(previous)
    finally:
        MigrationExecutor(connection).migrate(latest)
    accept(fixture)
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate(previous)
    finally:
        MigrationExecutor(connection).migrate(latest)
    assert PrdAcceptedCommand.objects.count() == 1
