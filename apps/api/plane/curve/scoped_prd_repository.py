# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Receipt-bound scoped writes; final transitions are separate from legacy guards."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from django.db import transaction

from .policy_services import assert_active_mutation_receipt
from .prd_commands import PrdCommandError, check_prd_command_subject
from .prd_checkpoint_repository import append_document_checkpoint_metadata
from .scoped_prd_commands import ScopedPrdCommand, validate_scoped_command
from .scoped_prd_contracts import SCHEMA_VERSION, POLICY_EDITION, metadata_digest
from .scoped_prd_policy import require_scoped_current, scope_pins

_WRITE = ContextVar("scoped_prd_write", default=None)


@contextmanager
def scoped_write(receipt, context, *, action):
    assert_active_mutation_receipt(
        receipt, action=action, workspace_id=context.workspace.id, resource_ref=dict(receipt.resource_ref)
    )
    if receipt.resource_ref["resource_id"] != str(context.initiative.id):
        raise PermissionError("Scoped write subject mismatch")
    from .models import PolicyDecision

    policy = PolicyDecision.objects.get(id=receipt.decision_id, workspace_id=context.workspace.id)
    if (
        policy.subject != {"actor_type": "HUMAN", "actor_id": str(context.actor_id)}
        or policy.effective_principal != policy.subject
    ):
        raise PermissionError("Scoped write actor mismatch")
    token = _WRITE.set((receipt, context, action))
    try:
        yield
    finally:
        _WRITE.reset(token)


def assert_scoped_write(record):
    active = _WRITE.get()
    if active is None or not transaction.get_connection().in_atomic_block:
        raise PermissionError("Active scoped PRD receipt required")
    receipt, context, action = active
    assert_active_mutation_receipt(
        receipt, action=action, workspace_id=context.workspace.id, resource_ref=dict(receipt.resource_ref)
    )
    if record.workspace_id != context.workspace.id or record.initiative_id != context.initiative.id:
        raise PermissionError("Scoped write subject mismatch")
    if hasattr(record, "product_id") and record.product_id != context.product.id:
        raise PermissionError("Scoped write Product mismatch")
    from .scoped_prd_models import ScopedPrdDecision, ScopedPrdAcceptedCommand

    expected = (
        record.action
        if isinstance(record, ScopedPrdAcceptedCommand)
        else {
            "APPROVED": "CURVE.PRD.APPROVE",
            "CHANGES_REQUESTED": "CURVE.PRD.REQUEST_CHANGES",
            "REJECTED": "CURVE.PRD.REJECT",
        }[record.payload["state"]]
        if isinstance(record, ScopedPrdDecision)
        else "CURVE.PRD.SUBMIT"
    )
    if action != expected:
        raise PermissionError("Scoped write action mismatch")
    actor = getattr(record, "actor_id", getattr(record, "created_by", context.actor_id))
    if actor != context.actor_id:
        raise PermissionError("Scoped write actor mismatch")


def guard_command(command, workspace_id, initiative_id, actor_id, *, preflight=False):
    validate_scoped_command(command, metadata_only=True)
    from .models import ExternalDocumentBinding, DocumentCheckpoint, GateAssignment
    from .scoped_prd_models import ScopedPrdObservation, ScopedPrdSubject

    if type(command) is not ScopedPrdCommand:
        raise PrdCommandError("SCOPED_PRD_INVALID")
    payload = command.subject_metadata()
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("policy_edition") != POLICY_EDITION:
        raise PrdCommandError("SCOPED_PRD_INVALID")
    observation, subject = None, None
    if command.action == "CURVE.PRD.SUBMIT":
        observation = ScopedPrdObservation.objects.find_by_id(
            workspace_id=workspace_id, record_id=payload["observation_set_id"], for_update=True
        )
        if observation is None or observation.digest != payload["observation_digest"]:
            raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    else:
        subject = ScopedPrdSubject.objects.find_by_id(
            workspace_id=workspace_id, record_id=payload["scoped_subject_id"], for_update=True
        )
        if subject is None or subject.digest != payload["scoped_subject_digest"]:
            raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
        data = subject.as_record()
        for key in (
            "checkpoint_id",
            "artifact_version_id",
            "content_digest",
            "provider_version",
            "evidence_snapshot_id",
        ):
            if payload[key] != data[key]:
                raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    context = require_scoped_current(
        workspace_id=workspace_id,
        initiative_id=initiative_id,
        actor_id=actor_id,
        observation=observation,
        subject=subject,
    )
    if observation is not None and any(payload[key] != value for key, value in scope_pins(context).items()):
        raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    if preflight:
        if command.action == "CURVE.PRD.SUBMIT":
            records = dict(
                binding=ExternalDocumentBinding.objects.find_by_id(
                    workspace_id=workspace_id, record_id=payload["external_document_binding_id"], for_update=True
                )
            )
        else:
            records = dict(
                checkpoint=DocumentCheckpoint.objects.find_by_id(
                    workspace_id=workspace_id, record_id=payload["checkpoint_id"], for_update=True
                ),
                gate_assignment=GateAssignment.objects.find_by_id(
                    workspace_id=workspace_id, record_id=payload["gate_assignment_id"], for_update=True
                ),
            )
        check_prd_command_subject(command=command.legacy_command(), initiative=context.initiative, **records)
    return context


def entity(context, record_id):
    return dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        id=str(record_id),
        workspace_id=str(context.workspace.id),
        product_id=str(context.product.id),
        initiative_id=str(context.initiative.id),
    )


def sealed(payload):
    payload["digest"] = metadata_digest(payload)
    return payload


def record_scoped_submission(*, receipt, record, context, snapshot, version, checkpoint, readiness_record):
    import uuid
    from .prd_metadata_validation import metadata_digest as base_digest, instant
    from .scoped_prd_models import ScopedPrdObservation, ScopedPrdReadiness, ScopedPrdSubject

    context = authorize_record_write(receipt, record, "CURVE.PRD.SUBMIT")
    command_payload = record.subject
    base = readiness_record.payload
    if not (
        readiness_record.id == checkpoint.completeness_check_id
        and str(readiness_record.id) == command_payload["completeness_check_id"]
        and checkpoint.evidence_snapshot_id == snapshot.id == version.evidence_snapshot_id
        and str(checkpoint.evidence_snapshot_id)
        == command_payload["evidence_snapshot_id"]
        == base["evidence_snapshot_id"]
        and base["content_digest"] == checkpoint.content_digest == version.body_digest
        and base["provider_version"] == checkpoint.provider_version
        and base["prd_binding_id"]
        == str(checkpoint.external_document_binding_id)
        == command_payload["external_document_binding_id"]
        and readiness_record.workspace_id == record.workspace_id
        and readiness_record.initiative_id == record.initiative_id
    ):
        raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    observation = ScopedPrdObservation.objects.find_by_id(
        workspace_id=record.workspace_id, record_id=command_payload["observation_set_id"], for_update=True
    )
    if observation is None:
        raise PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404)
    initiative = context.initiative
    actor = {"actor_type": "HUMAN", "actor_id": str(record.actor_id)}
    if initiative.version != record.expected_version or initiative.state not in {"ALIGNING", "PRD_REVIEW"}:
        raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    if actor != checkpoint.submitted_or_approved_by:
        raise PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404)
    ready_payload = sealed(
        dict(
            entity(context, uuid.uuid4()),
            base_readiness_id=str(readiness_record.id),
            base_readiness_digest=base_digest(readiness_record.payload),
            **scope_pins(context),
            observation_set_id=str(observation.id),
            observation_digest=observation.digest,
        )
    )
    ready = ScopedPrdReadiness.from_payload(ready_payload)
    subject_payload = sealed(
        dict(
            entity(context, uuid.uuid4()),
            checkpoint_id=str(checkpoint.id),
            artifact_version_id=str(version.id),
            content_digest=checkpoint.content_digest,
            provider_version=checkpoint.provider_version,
            evidence_snapshot_id=str(snapshot.id),
            **scope_pins(context),
            observation_set_id=str(observation.id),
            observation_digest=observation.digest,
            scoped_readiness_id=str(ready.id),
            scoped_readiness_digest=ready.digest,
            members=[
                {k: v for k, v in item.items() if k not in {"source_version", "source_fingerprint"}}
                for item in context.observed_members
            ],
            created_by=str(record.actor_id),
            recorded_at=instant(checkpoint.recorded_at),
            controlling=False,
        )
    )
    subject = ScopedPrdSubject.from_payload(subject_payload, submission_operation_id=record.operation_id)
    with scoped_write(receipt, context, action=record.action):
        append_document_checkpoint_metadata(
            workspace_id=record.workspace_id,
            initiative_id=initiative.id,
            expected_initiative_version=record.expected_version,
            artifact_id=version.artifact_id,
            expected_parent_version_id=version.parent_version_id,
            expected_predecessor_id=initiative.current_prd_checkpoint_id,
            snapshot=snapshot,
            version=version,
            checkpoint=checkpoint,
        )
        ready.save()
        subject.save()
        initiative.current_prd_checkpoint_id = checkpoint.id
        initiative.controlling_prd_decision_id = None
        initiative.pending_scope_reopening_id = None
        initiative.state = "PRD_REVIEW"
        initiative.version += 1
        initiative.updated_by = deepcopy(actor)
        initiative.save(
            update_fields=[
                "current_prd_checkpoint_id",
                "pending_scope_reopening_id",
                "controlling_prd_decision_id",
                "state",
                "version",
                "updated_by",
                "updated_at",
            ]
        )
    return initiative


def record_scoped_decision(*, receipt, record, context, decision):
    import uuid
    from .prd_metadata_validation import instant
    from .scoped_prd_models import ScopedPrdSubject, ScopedPrdDecision

    context = authorize_record_write(receipt, record, record.action)
    initiative = context.initiative
    if initiative.version != record.expected_version or initiative.state != "PRD_REVIEW":
        raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    subject = ScopedPrdSubject.objects.find_by_id(
        workspace_id=record.workspace_id, record_id=record.subject["scoped_subject_id"], for_update=True
    )
    if (
        subject is None
        or subject.checkpoint_id != initiative.current_prd_checkpoint_id
        or decision.checkpoint_id != subject.checkpoint_id
    ):
        raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
    payload = sealed(
        dict(
            entity(context, uuid.uuid4()),
            decision_id=str(decision.id),
            scoped_subject_id=str(subject.id),
            scoped_subject_digest=subject.digest,
            state=decision.state,
            created_by=str(record.actor_id),
            recorded_at=instant(decision.decided_at),
            controlling=False,
        )
    )
    sidecar = ScopedPrdDecision.from_payload(payload, review_operation_id=record.operation_id)
    with scoped_write(receipt, context, action=record.action):
        decision.save()
        sidecar.save()
        initiative.controlling_prd_decision_id = decision.id
        initiative.state = "PLANNING" if decision.state == "APPROVED" else "ALIGNING"
        initiative.version += 1
        initiative.updated_by = deepcopy(decision.decided_by)
        initiative.save(update_fields=["controlling_prd_decision_id", "state", "version", "updated_by", "updated_at"])
    return initiative


def authorize_record_write(receipt, record, action):
    """Re-resolve durable command and exact current authority at the repository boundary."""
    from .scoped_prd_models import ScopedPrdAcceptedCommand
    from .models import Operation, PolicyDecision

    if action != record.action or action not in {
        "CURVE.PRD.SUBMIT",
        "CURVE.PRD.APPROVE",
        "CURVE.PRD.REQUEST_CHANGES",
        "CURVE.PRD.REJECT",
    }:
        raise PermissionError("Scoped write action mismatch")
    assert_active_mutation_receipt(
        receipt, action=action, workspace_id=record.workspace_id, resource_ref=dict(receipt.resource_ref)
    )
    stored = ScopedPrdAcceptedCommand.objects.find_by_id(
        workspace_id=record.workspace_id, record_id=record.operation_id, for_update=True
    )
    if stored is None or any(
        getattr(stored, key) != getattr(record, key)
        for key in ("action", "initiative_id", "actor_id", "expected_version", "request_digest", "subject", "edition")
    ):
        raise PermissionError("Scoped durable command mismatch")
    stored.validate_metadata()
    policy = PolicyDecision.objects.get(id=receipt.decision_id, workspace_id=record.workspace_id)
    if (
        policy.subject != {"actor_type": "HUMAN", "actor_id": str(record.actor_id)}
        or policy.effective_principal != policy.subject
        or dict(receipt.resource_ref)
        != {
            "resource_type": "INITIATIVE",
            "resource_id": str(record.initiative_id),
            "resource_version": record.expected_version,
        }
        or not Operation.objects.filter(
            id=record.operation_id, workspace_id=record.workspace_id, status="RUNNING"
        ).exists()
    ):
        raise PermissionError("Scoped action actor or operation mismatch")
    command = ScopedPrdCommand(
        record.action,
        record.expected_version,
        record.request_digest,
        tuple(sorted(record.subject.items())),
        None,
        "internal-repository",
    )
    return guard_command(command, record.workspace_id, record.initiative_id, record.actor_id, preflight=True)
