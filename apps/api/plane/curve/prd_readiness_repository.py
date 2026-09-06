# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Policy-owned readiness append; provider reads stay outside its transaction."""

import uuid

from django.db import transaction

from .models import Initiative, PrdReadinessRecord
from .policy_services import assert_active_mutation_receipt, policy_decision_ref_for_receipt
from .prd_metadata_validation import require_metadata, metadata_digest
from .prd_readiness import ReadinessReport


def record_prd_readiness_metadata(*, authorization_receipt, report):
    """Join an owning command's transaction and its single linked audit event."""
    require_metadata(transaction.get_connection().in_atomic_block, "READINESS_RECORD_TRANSACTION_REQUIRED")
    require_metadata(type(report) is ReadinessReport, "READINESS_RECORD_REQUIRED")
    payload = report.as_dict()
    workspace_id = uuid.UUID(payload["workspace_id"])
    initiative_id = uuid.UUID(payload["initiative_id"])
    assert_active_mutation_receipt(
        authorization_receipt,
        action="CURVE.PRD.SUBMIT",
        workspace_id=workspace_id,
        resource_ref={
            "resource_type": "INITIATIVE",
            "resource_id": str(initiative_id),
            "resource_version": payload["initiative_version"],
        },
    )
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    require_metadata(
        initiative is not None and initiative.version == payload["initiative_version"],
        "READINESS_RECORD_VERSION_CONFLICT",
    )
    record = PrdReadinessRecord(
        id=uuid.UUID(payload["id"]),
        workspace_id=workspace_id,
        initiative_id=initiative_id,
        binding_id=uuid.UUID(payload["prd_binding_id"]),
        policy_decision_id=uuid.UUID(policy_decision_ref_for_receipt(authorization_receipt)["resource_id"]),
        payload=payload,
    )
    record.save()
    return record


def append_prd_readiness_report(*, authorization_receipt, report):
    """Persist a standalone assessment with its own linked metadata-only audit."""
    record = record_prd_readiness_metadata(authorization_receipt=authorization_receipt, report=report)
    from .services import _append_audit_event

    policy = record.policy_decision
    _append_audit_event(
        workspace_id=record.workspace_id,
        action="CURVE.PRD.READINESS_RECORDED",
        target_ref={"resource_type": "PRD_READINESS", "resource_id": str(record.id), "resource_version": 1},
        outcome="SUCCEEDED",
        actor=policy.subject,
        effective_principal=policy.effective_principal,
        correlation_id=policy.correlation_id,
        after_digest=metadata_digest(record.payload),
        policy_decision_ref=policy_decision_ref_for_receipt(authorization_receipt),
    )
    return record
