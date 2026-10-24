# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Append-only scoped pre-submission readiness metadata."""

import uuid
from copy import deepcopy
from datetime import datetime

from django.db import models
from django.utils import timezone

from .prd_models import PrdImmutableModel
from .prd_metadata_validation import require_metadata
from .prd_readiness import validate_prd_readiness_report


class PrdReadinessRecord(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    binding = models.ForeignKey("curve.ExternalDocumentBinding", on_delete=models.PROTECT)
    policy_decision = models.ForeignKey("curve.PolicyDecision", on_delete=models.PROTECT)
    payload = models.JSONField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_prd_readiness_record"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_readiness_scope_uq"),
        ]

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        from .models import Initiative, ExternalDocumentBinding, PolicyDecision

        validate_prd_readiness_report(self.payload)
        report = self.payload
        for field in (
            "id",
            "workspace_id",
            "initiative_id",
            "prd_binding_id",
            "idea_brief_version_id",
            "evidence_snapshot_id",
        ):
            try:
                require_metadata(str(uuid.UUID(report[field])) == report[field], "READINESS_RECORD_ID_INVALID")
            except (ValueError, TypeError, AttributeError):
                require_metadata(False, "READINESS_RECORD_ID_INVALID")
        require_metadata(
            report["id"] == str(self.id)
            and report["workspace_id"] == str(self.workspace_id)
            and report["initiative_id"] == str(self.initiative_id)
            and report["prd_binding_id"] == str(self.binding_id),
            "READINESS_RECORD_SCOPE_INVALID",
        )
        initiative = Initiative.objects.find_by_id(workspace_id=self.workspace_id, record_id=self.initiative_id)
        binding = ExternalDocumentBinding.objects.find_by_id(workspace_id=self.workspace_id, record_id=self.binding_id)
        policy = PolicyDecision.objects.filter(workspace_id=self.workspace_id, id=self.policy_decision_id).first()
        require_metadata(
            initiative is not None and binding is not None and policy is not None,
            "READINESS_RECORD_REFERENCE_UNAVAILABLE",
        )
        require_metadata(
            initiative.version == report["initiative_version"] and initiative.state in {"ALIGNING", "PRD_REVIEW"},
            "READINESS_RECORD_VERSION_CONFLICT",
        )
        require_metadata(
            binding.initiative_id == initiative.id and binding.provider_file_id == report["provider_file_id"],
            "READINESS_RECORD_BINDING_MISMATCH",
        )
        require_metadata(
            policy.action == "CURVE.PRD.SUBMIT"
            and policy.effect == "ALLOW"
            and policy.policy_key == "CURVE_PRD_POLICY"
            and policy.resource_type == "INITIATIVE"
            and policy.resource_id == initiative.id
            and policy.resource_version == report["initiative_version"]
            and type(policy.subject) is dict
            and policy.subject.get("actor_type") == "HUMAN"
            and policy.effective_principal == policy.subject,
            "READINESS_RECORD_POLICY_MISMATCH",
        )
        checked_at = datetime.fromisoformat(report["checked_at"])
        require_metadata(
            self.recorded_at.tzinfo is not None
            and initiative.created_at <= checked_at <= self.recorded_at <= timezone.now(),
            "READINESS_RECORD_TIME_INVALID",
        )
