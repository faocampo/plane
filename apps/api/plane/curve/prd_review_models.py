# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Immutable PRD review metadata with independently protected rationale bytes."""

import uuid
from copy import deepcopy
from datetime import datetime

from django.db import models

from .models import DocumentCheckpoint, GateAssignment
from .prd_metadata_validation import instant, require_metadata, validate_review_decision_record
from .prd_models import PrdImmutableModel
from .prd_review_rationale import RATIONALE_MEDIA_TYPE, review_decision_metadata


class PrdReviewDecision(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    gate_assignment = models.ForeignKey(GateAssignment, on_delete=models.PROTECT)
    checkpoint = models.ForeignKey(DocumentCheckpoint, on_delete=models.PROTECT)
    artifact_version = models.ForeignKey("curve.PrdArtifactVersion", on_delete=models.PROTECT)
    evidence_snapshot = models.ForeignKey("curve.PrdEvidenceSnapshot", on_delete=models.PROTECT)
    content_digest = models.CharField(max_length=71, editable=False)
    provider_version = models.CharField(max_length=512, editable=False)
    access_evaluation_id = models.UUIDField(editable=False)
    policy_version_ids = models.JSONField(editable=False)
    confirmed_risk_tier = models.CharField(max_length=16, editable=False)
    state = models.CharField(max_length=32, editable=False)
    decided_by = models.JSONField(editable=False)
    decided_at = models.DateTimeField(editable=False)
    provider_validation_cutoff = models.DateTimeField(editable=False)
    rationale_object_id = models.UUIDField(editable=False)
    rationale_digest = models.CharField(max_length=71, editable=False)
    rationale_size_bytes = models.PositiveIntegerField(editable=False)
    rationale_access_envelope_id = models.UUIDField(editable=False)
    rationale_retention_policy_version_id = models.UUIDField(editable=False)

    class Meta:
        db_table = "curve_prd_review_decision"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_prd_decision_scope_uq"),
            models.UniqueConstraint(fields=["workspace_id", "checkpoint"], name="curve_prd_decision_cp_uq"),
            models.CheckConstraint(
                condition=models.Q(state__in=["APPROVED", "CHANGES_REQUESTED", "REJECTED"]),
                name="curve_prd_decision_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(confirmed_risk_tier__in=["LOW", "STANDARD", "HIGH"]),
                name="curve_prd_decision_risk_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(rationale_size_bytes__gte=1, rationale_size_bytes__lte=8000),
                name="curve_prd_decision_size_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(content_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_prd_decision_digest_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(rationale_digest__regex=r"^sha256:[0-9a-f]{64}$"),
                name="curve_prd_rationale_digest_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(provider_version__regex=r"^[A-Za-z0-9._~-]+$"), name="curve_prd_decision_source_ck"
            ),
        ]

    def as_metadata(self):
        return dict(
            schema_version="1.0-candidate",
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            gate_assignment_id=str(self.gate_assignment_id),
            checkpoint_id=str(self.checkpoint_id),
            artifact_version_id=str(self.artifact_version_id),
            evidence_snapshot_id=str(self.evidence_snapshot_id),
            content_digest=self.content_digest,
            provider_version=self.provider_version,
            access_evaluation_id=str(self.access_evaluation_id),
            policy_version_ids=deepcopy(self.policy_version_ids),
            confirmed_risk_tier=self.confirmed_risk_tier,
            state=self.state,
            decided_by=deepcopy(self.decided_by),
            decided_at=instant(self.decided_at),
            provider_validation_cutoff=instant(self.provider_validation_cutoff),
            rationale_ref=dict(
                object_id=str(self.rationale_object_id),
                digest=self.rationale_digest,
                size_bytes=self.rationale_size_bytes,
                media_type=RATIONALE_MEDIA_TYPE,
            ),
            rationale_access_envelope_id=str(self.rationale_access_envelope_id),
            rationale_retention_policy_version_id=str(self.rationale_retention_policy_version_id),
        )

    @classmethod
    def from_wire(cls, *, decision, rationale_ref, rationale_access_envelope_id, rationale_retention_policy_version_id):
        """Build metadata after matching original rationale bytes to its reference.

        This proves byte/reference consistency, not storage existence or authority.
        The returned unsaved instance retains no rationale text.
        """
        record = review_decision_metadata(
            decision=decision,
            rationale_ref=rationale_ref,
            rationale_access_envelope_id=rationale_access_envelope_id,
            rationale_retention_policy_version_id=rationale_retention_policy_version_id,
        )
        values = {
            key: deepcopy(value) for key, value in record.items() if key not in ("schema_version", "rationale_ref")
        }
        for name in ("decided_at", "provider_validation_cutoff"):
            try:
                values[name] = datetime.fromisoformat(values[name].replace("Z", "+00:00"))
            except ValueError:
                require_metadata(False, "PRD_REVIEW_TIMESTAMP_INVALID")
        for name in (
            "id",
            "workspace_id",
            "initiative_id",
            "gate_assignment_id",
            "checkpoint_id",
            "artifact_version_id",
            "evidence_snapshot_id",
            "access_evaluation_id",
            "rationale_access_envelope_id",
            "rationale_retention_policy_version_id",
        ):
            values[name] = uuid.UUID(values[name])
        values.update(
            rationale_object_id=uuid.UUID(record["rationale_ref"]["object_id"]),
            rationale_digest=record["rationale_ref"]["digest"],
            rationale_size_bytes=record["rationale_ref"]["size_bytes"],
        )
        return cls(**values)

    def validate_metadata(self):
        record = self.as_metadata()
        validate_review_decision_record(record)
        checkpoint = DocumentCheckpoint.objects.find_by_id(workspace_id=self.workspace_id, record_id=self.checkpoint_id)
        assignment = GateAssignment.objects.find_by_id(
            workspace_id=self.workspace_id, record_id=self.gate_assignment_id
        )
        require_metadata(checkpoint is not None and assignment is not None, "PRD_REVIEW_REFERENCE_UNAVAILABLE")
        require_metadata(
            str(checkpoint.initiative_id) == str(self.initiative_id) == str(assignment.initiative_id),
            "PRD_REVIEW_SCOPE_MISMATCH",
        )
        require_metadata(
            str(checkpoint.artifact_version_id) == str(self.artifact_version_id)
            and str(checkpoint.evidence_snapshot_id) == str(self.evidence_snapshot_id)
            and checkpoint.content_digest == self.content_digest
            and checkpoint.provider_version == self.provider_version,
            "PRD_REVIEW_SUBJECT_MISMATCH",
        )
        require_metadata(
            assignment.gate_type == "PRD_APPROVAL" and str(assignment.approver_user_id) == self.decided_by["actor_id"],
            "PRD_REVIEW_PRODUCT_APPROVER_REQUIRED",
        )
