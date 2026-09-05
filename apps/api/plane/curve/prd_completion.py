# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Internal PRD activity application service; no transport or runtime activation.

Only workspace/Operation IDs cross the activity boundary. The configured runtime
authorizes worker scope and obtains fresh provider/storage observations outside
database transactions. Protected bytes stay in the preparation context. Domain
effects and the terminal Operation/audit/outbox commit together.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.db.models import User, Workspace, WorkspaceMember
from .initiative_serialization import serialize_gate_assignment
from .models import DocumentCheckpoint, GateAssignment, Initiative, Operation, PrdAcceptedCommand, PrdReviewDecision
from .policy_services import (
    execute_authorized_mutation,
    policy_decision_ref_for_receipt,
    transition_operation_with_service_authorization,
)
from .prd_acceptance import _preflight
from .prd_commands import PrdCommand
from .prd_lifecycle_repository import record_prd_decision_transition, record_prd_submission_transition
from .prd_metadata_validation import instant
from .prd_policy_context import build_prd_policy_context
from .prd_review_validation import validate_review_subject
from .services import _append_audit_event, sha256_digest


class PrdCompletionUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("PRD_COMPLETION_UNAVAILABLE")


@dataclass
class PrdCompletionPreparation:
    operation_id: uuid.UUID
    request_digest: str
    valid_from: datetime
    valid_until: datetime
    checks: dict = field(repr=False)
    rationale_bytes: bytes | None = field(default=None, repr=False)
    normalized_bytes: bytes | None = field(default=None, repr=False)
    provider_version: str | None = None
    content_digest: str | None = None
    provider_validation_cutoff: datetime | None = None
    access_evaluation_id: uuid.UUID | None = None
    policy_version_ids: list | None = None
    # Unsaved (EvidenceSnapshot, ArtifactVersion, DocumentCheckpoint) from the
    # approved capture adapter. The repository validates their complete graph.
    submission: tuple | None = field(default=None, repr=False)
    committed_operation_id: uuid.UUID | None = None


_CHECKS = frozenset(
    {"provider_capability", "storage_policy", "source_access", "evidence_access", "body_access", "readiness"}
)
_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
_DESTINATION = "CURVE_PRD_CANDIDATE_V1"


def _require(value):
    if not value:
        raise PrdCompletionUnavailable


def _command(record, rationale_bytes=None):
    # Metadata preflight precedes protected reads; full original payload integrity
    # is independently verified with the retrieved rationale at final use.
    return PrdCommand(
        record.action,
        record.expected_version,
        record.request_digest,
        tuple(sorted(record.subject.items())),
        rationale_bytes,
        "internal-completion",
    )


def _proof(prepared, record):
    now = timezone.now()
    _require(
        type(prepared) is PrdCompletionPreparation
        and prepared.operation_id == record.operation_id
        and prepared.request_digest == record.request_digest
        and prepared.committed_operation_id is None
        and type(prepared.checks) is dict
        and set(prepared.checks) == _CHECKS
        and all(value is True for value in prepared.checks.values())
        and isinstance(prepared.valid_from, datetime)
        and prepared.valid_from.utcoffset() is not None
        and isinstance(prepared.valid_until, datetime)
        and prepared.valid_until.utcoffset() is not None
        and record.accepted_at <= prepared.valid_from <= now < prepared.valid_until
        and isinstance(prepared.provider_validation_cutoff, datetime)
        and prepared.provider_validation_cutoff.utcoffset() is not None
        and prepared.valid_from <= prepared.provider_validation_cutoff <= now
    )


def _worker_grant(runtime, workspace_id, operation_id):
    grant = runtime.worker_authorization(workspace_id=workspace_id, operation_id=operation_id)
    _require(
        type(grant) is dict
        and set(grant) == {"workspace_id", "operation_id", "actor", "authorization"}
        and grant["workspace_id"] == workspace_id
        and grant["operation_id"] == operation_id
    )
    authorization = grant["authorization"]
    now = timezone.now()
    _require(
        type(authorization) is dict
        and authorization.get("active") is True
        and authorization.get("workspace_id") == str(workspace_id)
        and authorization.get("service") == grant["actor"]
        and type(grant["actor"]) is dict
        and grant["actor"].get("actor_type") == "SERVICE"
        and "CURVE.OPERATION.TRANSITION" in authorization.get("allowed_actions", [])
    )
    issued = datetime.fromisoformat(authorization["issued_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00"))
    _require(issued.utcoffset() is not None and expires.utcoffset() is not None and issued <= now < expires)
    return grant


def _transition(runtime, operation, status, error=None):
    grant = _worker_grant(runtime, operation.workspace_id, operation.id)
    return transition_operation_with_service_authorization(
        workspace_id=operation.workspace_id,
        operation_id=operation.id,
        expected_version=operation.aggregate_version,
        status=status,
        service_actor=grant["actor"],
        service_authorization=grant["authorization"],
        correlation_id=operation.correlation_id,
        causation_id=str(operation.id),
        progress_percent=100 if status == "SUCCEEDED" else None,
        error=error,
        destination=_DESTINATION,
    )


def _outcome(operation, effect=False):
    return {
        "operation_id": str(operation.id),
        "status": operation.status,
        "version": operation.aggregate_version,
        "effect_applied": effect,
    }


def _review(record, prepared, initiative, actor):
    checkpoint = DocumentCheckpoint.objects.find_by_id(
        workspace_id=record.workspace_id, record_id=initiative.current_prd_checkpoint_id, for_update=True
    )
    _require(checkpoint is not None and prepared.submission is None)
    _require(
        type(prepared.normalized_bytes) is bytes
        and len(prepared.normalized_bytes) == checkpoint.body_size_bytes
        and sha256_digest(prepared.normalized_bytes) == checkpoint.content_digest
    )
    if record.action == "CURVE.PRD.APPROVE":
        _require(
            prepared.provider_version == checkpoint.provider_version
            and prepared.content_digest == checkpoint.content_digest
        )
    payload = record.verified_payload(rationale_bytes=prepared.rationale_bytes)
    wire = {key: deepcopy(value) for key, value in payload.items() if key != "decision"}
    wire.update(
        schema_version="1.0",
        id=str(uuid.uuid4()),
        workspace_id=str(record.workspace_id),
        initiative_id=str(record.initiative_id),
        access_evaluation_id=str(prepared.access_evaluation_id),
        policy_version_ids=deepcopy(prepared.policy_version_ids),
        state={
            "CURVE.PRD.APPROVE": "APPROVED",
            "CURVE.PRD.REQUEST_CHANGES": "CHANGES_REQUESTED",
            "CURVE.PRD.REJECT": "REJECTED",
        }[record.action],
        decided_by=actor,
        decided_at=instant(timezone.now()),
        provider_validation_cutoff=instant(prepared.provider_validation_cutoff),
    )
    assignments = list(
        GateAssignment.objects.filter(workspace_id=record.workspace_id, initiative_id=initiative.id)
        .select_for_update()
        .order_by("id")
    )
    active_ids = list(
        WorkspaceMember.objects.filter(
            workspace_id=record.workspace_id,
            is_active=True,
            member__is_active=True,
            member__is_bot=False,
            member_id__in=[item.approver_user_id for item in assignments],
        ).values_list("member_id", flat=True)
    )
    validate_review_subject(
        checkpoint=checkpoint.as_record(),
        decision=wire,
        assignments=[serialize_gate_assignment(item) for item in assignments],
        active_human_ids=[str(value) for value in active_ids],
        authenticated_actor=actor,
        current_checkpoint_id=str(initiative.current_prd_checkpoint_id),
        current_risk_tier=initiative.risk_tier,
        current_policy_version_ids=prepared.policy_version_ids,
    )
    decision = PrdReviewDecision.from_wire(
        decision=wire,
        rationale_ref={
            "object_id": str(record.rationale_object_id),
            "digest": record.rationale_digest,
            "size_bytes": record.rationale_size_bytes,
            "media_type": "text/plain; charset=utf-8",
        },
        rationale_access_envelope_id=record.rationale_access_envelope_id,
        rationale_retention_policy_version_id=record.rationale_retention_policy_version_id,
    )
    return record_prd_decision_transition(
        workspace_id=record.workspace_id,
        initiative_id=initiative.id,
        expected_version=record.expected_version,
        expected_checkpoint_id=checkpoint.id,
        actor=actor,
        decision=decision,
    )


def _submit(record, prepared, initiative, actor):
    record.verified_payload(rationale_bytes=prepared.rationale_bytes)
    _require(type(prepared.submission) is tuple and len(prepared.submission) == 3)
    snapshot, version, checkpoint = prepared.submission
    _require(
        type(prepared.normalized_bytes) is bytes
        and len(prepared.normalized_bytes) == checkpoint.body_size_bytes
        and sha256_digest(prepared.normalized_bytes) == checkpoint.content_digest
        and prepared.provider_version == checkpoint.provider_version
        and prepared.content_digest == checkpoint.content_digest
        and str(checkpoint.external_document_binding_id) == record.subject["external_document_binding_id"]
        and str(checkpoint.evidence_snapshot_id) == record.subject["evidence_snapshot_id"]
        and str(checkpoint.completeness_check_id) == record.subject["completeness_check_id"]
        and prepared.valid_from <= checkpoint.recorded_at <= timezone.now()
    )
    return record_prd_submission_transition(
        workspace_id=record.workspace_id,
        initiative_id=initiative.id,
        expected_version=record.expected_version,
        expected_checkpoint_id=initiative.current_prd_checkpoint_id,
        actor=actor,
        artifact_id=version.artifact_id,
        expected_parent_version_id=version.parent_version_id,
        snapshot=snapshot,
        version=version,
        checkpoint=checkpoint,
    )


def complete_prd_operation(*, workspace_id, operation_id):
    """Run an accepted command under a trusted, explicitly configured runtime.

    Runtime worker_authorization and revalidate_completion are current local
    authority reads. prepare_completion is a bounded context manager outside DB
    locks and owns approved cleanup/reconciliation of unused protected objects.
    This service is internal; it is never exposed as a human approval endpoint.
    """
    _require(not transaction.get_connection().in_atomic_block)
    runtime = getattr(settings, "CURVE_PRD_COMPLETION_RUNTIME", None)
    _require(
        runtime is not None
        and getattr(settings, "CURVE_PRD_COMMANDS_ENABLED", False) is True
        and all(
            callable(getattr(runtime, name, None))
            for name in ("worker_authorization", "resolve_acl", "prepare_completion", "revalidate_completion")
        )
    )
    workspace_id, operation_id = uuid.UUID(str(workspace_id)), uuid.UUID(str(operation_id))
    try:
        _worker_grant(runtime, workspace_id, operation_id)
        record = PrdAcceptedCommand.objects.find_by_id(workspace_id=workspace_id, record_id=operation_id)
        _require(record is not None)
        record.validate_metadata()
        workspace = Workspace.objects.get(id=workspace_id)
        request = SimpleNamespace(
            user=User.objects.get(id=record.actor_id),
            _curve_policy_correlation_id=Operation.objects.only("correlation_id")
            .get(workspace_id=workspace_id, id=operation_id)
            .correlation_id,
        )
        actor = {"actor_type": "HUMAN", "actor_id": str(record.actor_id)}

        def context():
            return build_prd_policy_context(
                request=request,
                workspace_slug=workspace.slug,
                initiative_id=record.initiative_id,
                action=record.action,
                acl_resolver=runtime.resolve_acl,
                for_update=True,
            )

        def phase(prepared=None):
            def mutate(receipt, _):
                ref = policy_decision_ref_for_receipt(receipt)
                operation = Operation.objects.select_for_update().get(workspace_id=workspace_id, id=operation_id)
                binding_valid = (
                    operation.target
                    == {
                        "resource_type": "INITIATIVE",
                        "resource_id": str(record.initiative_id),
                        "resource_version": record.expected_version,
                    }
                    and operation.created_by == actor
                    and (operation.effective_principal is None or operation.effective_principal == actor)
                    and operation.command_type == "PRD_" + record.action.removeprefix("CURVE.PRD.")
                    and operation.operation_type == "WORKFLOW_COMMAND"
                )

                def audit(outcome, target=None):
                    _append_audit_event(
                        workspace_id=workspace_id,
                        action=record.action + ".COMPLETION",
                        target_ref=target or dict(receipt.resource_ref),
                        outcome=outcome,
                        actor=actor,
                        correlation_id=operation.correlation_id,
                        causation_id=str(operation_id),
                        policy_decision_ref=ref,
                    )

                try:
                    with transaction.atomic():
                        _require(binding_valid)
                        if operation.status in _TERMINAL:
                            audit("NO_EFFECT")
                            return _outcome(operation)
                        if operation.status == "CANCEL_REQUESTED":
                            operation = _transition(runtime, operation, "CANCELLED")
                            audit("NO_EFFECT")
                            return _outcome(operation)
                        _preflight(_command(record), workspace_id, record.initiative_id)
                        if prepared is None:
                            if operation.status == "PENDING":
                                operation = _transition(runtime, operation, "QUEUED")
                            if operation.status == "QUEUED":
                                operation = _transition(runtime, operation, "RUNNING")
                            _require(operation.status == "RUNNING")
                            audit("NO_EFFECT")
                            return None
                        _require(operation.status == "RUNNING")
                        _proof(prepared, record)
                        _require(runtime.revalidate_completion(prepared=prepared, command=record) is True)
                        _proof(prepared, record)
                        initiative = Initiative.objects.find_by_id(
                            workspace_id=workspace_id, record_id=record.initiative_id, for_update=True
                        )
                        initiative = (_submit if record.action == "CURVE.PRD.SUBMIT" else _review)(
                            record, prepared, initiative, actor
                        )
                        result_ref = {
                            "resource_type": "INITIATIVE",
                            "resource_id": str(initiative.id),
                            "resource_version": initiative.version,
                        }
                        operation.result_ref = result_ref
                        operation.save(update_fields=["result_ref", "updated_at"])
                        operation = _transition(runtime, operation, "SUCCEEDED")
                        audit("SUCCEEDED", result_ref)
                        return _outcome(operation, True)
                except Exception:
                    audit("NO_EFFECT")
                    raise PrdCompletionUnavailable from None

            return execute_authorized_mutation(
                context_builder=context, mutation_callback=mutate, no_effect_exceptions=(PrdCompletionUnavailable,)
            )

        first = phase()
        if first is not None:
            return first
        with runtime.prepare_completion(command=record) as prepared:
            result = phase(prepared)
            if result["effect_applied"]:
                prepared.committed_operation_id = operation_id
            return result
    except Exception:
        # Current worker authorization is independently evaluated when settling
        # failures, including loss of the original human's approval permission.
        try:
            with transaction.atomic():
                _worker_grant(runtime, workspace_id, operation_id)
                operation = Operation.objects.select_for_update().get(workspace_id=workspace_id, id=operation_id)
                _require(
                    PrdAcceptedCommand.objects.filter(workspace_id=workspace_id, operation_id=operation_id).exists()
                )
                if operation.status not in _TERMINAL:
                    status = "CANCELLED" if operation.status == "CANCEL_REQUESTED" else "FAILED"
                    operation = _transition(
                        runtime,
                        operation,
                        status,
                        None if status == "CANCELLED" else {"code": "PRD_COMPLETION_REJECTED", "retryable": False},
                    )
                return _outcome(operation)
        except Exception:
            raise PrdCompletionUnavailable from None
