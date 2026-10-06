# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Policy-owned command append; provider/storage preparation happens beforehand."""

from django.db import transaction

from .models import DocumentCheckpoint, ExternalDocumentBinding, GateAssignment, IdempotencyRecord, Initiative
from .policy_services import assert_active_mutation_receipt
from .prd_command_models import PrdAcceptedCommand
from .prd_commands import check_prd_command_subject
from .prd_metadata_validation import require_metadata
from .services import idempotency_key_digest, sha256_digest


def record_accepted_prd_command(
    *,
    authorization_receipt,
    command,
    operation,
    rationale_ref=None,
    access_envelope_id=None,
    retention_policy_version_id=None,
):
    """Join Operation, immutable command, idempotency result and outbox atomically.

    Invoke in the same authorized callback that creates a new Operation. Replay
    returns the existing record after current authorization and never appends.
    Current source/evidence/readiness and approved protected-storage checks are
    prerequisites supplied by the consuming handler, not proved by references.
    This helper performs database operations only.
    """
    require_metadata(transaction.get_connection().in_atomic_block, "PRD_COMMAND_TRANSACTION_REQUIRED")
    assert_active_mutation_receipt(
        authorization_receipt, action=command.action, workspace_id=operation.workspace_id, resource_ref=operation.target
    )
    require_metadata(
        operation.target.get("resource_version") == command.expected_version, "PRD_COMMAND_VERSION_CONFLICT"
    )
    initiative = Initiative.objects.find_by_id(
        workspace_id=operation.workspace_id, record_id=operation.target["resource_id"], for_update=True
    )
    require_metadata(initiative is not None, "PRD_COMMAND_SUBJECT_UNAVAILABLE")
    subject = command.subject_metadata()
    records = {}
    if command.action == "CURVE.PRD.SUBMIT":
        records["binding"] = ExternalDocumentBinding.objects.find_by_id(
            workspace_id=operation.workspace_id, record_id=subject["external_document_binding_id"], for_update=True
        )
    else:
        records["checkpoint"] = DocumentCheckpoint.objects.find_by_id(
            workspace_id=operation.workspace_id, record_id=subject["checkpoint_id"], for_update=True
        )
        records["gate_assignment"] = GateAssignment.objects.find_by_id(
            workspace_id=operation.workspace_id, record_id=subject["gate_assignment_id"], for_update=True
        )
    check_prd_command_subject(command=command, initiative=initiative, **records)
    action_suffix = command.action.removeprefix("CURVE.PRD.")
    require_metadata(
        IdempotencyRecord.objects.filter(
            workspace_id=operation.workspace_id,
            principal_scope=f"HUMAN:{operation.created_by['actor_id']}",
            command_scope=f"PRD_{action_suffix}:{initiative.id}",
            key_digest=idempotency_key_digest(command.idempotency_key),
            request_digest=sha256_digest(command.operation_request_identity()),
            state="COMPLETED",
            response_status=202,
            response_resource_ref__resource_type="OPERATION",
            response_resource_ref__resource_id=str(operation.id),
        ).exists(),
        "PRD_COMMAND_IDEMPOTENCY_MISMATCH",
    )
    record = PrdAcceptedCommand.from_command(
        command=command,
        operation=operation,
        rationale_ref=rationale_ref,
        access_envelope_id=access_envelope_id,
        retention_policy_version_id=retention_policy_version_id,
    )
    record.save()
    return record
