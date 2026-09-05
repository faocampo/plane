# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Append-only external PRD capture metadata; object bytes remain protected."""

import uuid
from copy import deepcopy

from django.db import models
from django.utils import timezone

from .models import ExternalDocumentBinding
from .prd_metadata_validation import MAX_SAFE_INTEGER, instant, require_metadata, validate_external_record
from .prd_models import PrdArtifactVersion, PrdEvidenceSnapshot, PrdImmutableModel
from .prd_review_validation import validate_checkpoint_subject


class DocumentCheckpoint(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    external_document_binding = models.ForeignKey(ExternalDocumentBinding, on_delete=models.PROTECT)
    artifact_version = models.ForeignKey(PrdArtifactVersion, on_delete=models.PROTECT)
    evidence_snapshot = models.ForeignKey(PrdEvidenceSnapshot, on_delete=models.PROTECT)
    predecessor = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)
    checkpoint_number = models.PositiveBigIntegerField(editable=False)
    provider_connection = models.ForeignKey("curve.ProviderConnection", on_delete=models.PROTECT)
    provider_file_id = models.CharField(max_length=512, editable=False)
    provider_container_id = models.CharField(max_length=512, editable=False)
    provider_version = models.CharField(max_length=512, editable=False)
    revision_id = models.CharField(max_length=512, null=True, blank=True, editable=False)
    body_object_id = models.UUIDField(editable=False)
    content_digest = models.CharField(max_length=71, editable=False)
    body_size_bytes = models.PositiveBigIntegerField(editable=False)
    normalization_schema_version = models.CharField(max_length=255, editable=False)
    access_evaluation_id = models.UUIDField(editable=False)
    completeness_check_id = models.UUIDField(editable=False)
    retention_policy_version_id = models.UUIDField(editable=False)
    access_envelope_id = models.UUIDField(editable=False)
    submitted_or_approved_by = models.JSONField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_document_checkpoint"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_cp_scope_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "external_document_binding", "id"],
                name="curve_cp_binding_scope_uq",
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "external_document_binding", "checkpoint_number"], name="curve_cp_number_uq"
            ),
            models.UniqueConstraint(fields=["workspace_id", "artifact_version"], name="curve_cp_artifact_ver_uq"),
            *[
                models.CheckConstraint(
                    condition=models.Q(**{field + "__gte": 1, field + "__lte": MAX_SAFE_INTEGER}), name=name
                )
                for field, name in (
                    ("checkpoint_number", "curve_cp_number_ck"),
                    ("body_size_bytes", "curve_cp_size_ck"),
                )
            ],
            models.CheckConstraint(
                condition=models.Q(content_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_cp_digest_ck"
            ),
            models.CheckConstraint(condition=~models.Q(normalization_schema_version=""), name="curve_cp_schema_ck"),
            *[
                models.CheckConstraint(condition=models.Q(**{field + "__regex": r"^[A-Za-z0-9._~-]+$"}), name=name)
                for field, name in (
                    ("provider_file_id", "curve_cp_file_ck"),
                    ("provider_container_id", "curve_cp_container_ck"),
                    ("provider_version", "curve_cp_source_ver_ck"),
                    ("revision_id", "curve_cp_revision_ck"),
                )
            ],
        ]

    def as_record(self):
        return dict(
            schema_version="1.0",
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            external_document_binding_id=str(self.external_document_binding_id),
            artifact_version_id=str(self.artifact_version_id),
            evidence_snapshot_id=str(self.evidence_snapshot_id),
            checkpoint_number=self.checkpoint_number,
            checkpoint_type="SUBMITTED",
            provider_connection_id=str(self.provider_connection_id),
            provider_file_id=self.provider_file_id,
            provider_container_id=self.provider_container_id,
            provider_version=self.provider_version,
            revision_id=self.revision_id,
            normalized_content_ref=dict(
                object_id=str(self.body_object_id),
                digest=self.content_digest,
                size_bytes=self.body_size_bytes,
                media_type="application/json",
            ),
            content_digest=self.content_digest,
            normalization_schema_version=self.normalization_schema_version,
            access_evaluation_id=str(self.access_evaluation_id),
            completeness_check_id=str(self.completeness_check_id),
            retention_policy_version_id=str(self.retention_policy_version_id),
            access_envelope_id=str(self.access_envelope_id),
            predecessor_id=str(self.predecessor_id) if self.predecessor_id else None,
            submitted_or_approved_by=deepcopy(self.submitted_or_approved_by),
            recorded_at=instant(self.recorded_at),
        )

    def validate_metadata(self):
        record = self.as_record()
        validate_external_record("Checkpoint", record)
        binding = ExternalDocumentBinding.objects.find_by_id(
            workspace_id=self.workspace_id, record_id=self.external_document_binding_id
        )
        version = PrdArtifactVersion.objects.find_by_id(
            workspace_id=self.workspace_id, record_id=self.artifact_version_id
        )
        snapshot = PrdEvidenceSnapshot.objects.find_by_id(
            workspace_id=self.workspace_id, record_id=self.evidence_snapshot_id
        )
        predecessor = None
        if self.predecessor_id:
            predecessor = type(self).objects.find_by_id(workspace_id=self.workspace_id, record_id=self.predecessor_id)
            require_metadata(predecessor is not None, "CHECKPOINT_REFERENCE_UNAVAILABLE")
        require_metadata(
            all(item is not None for item in (binding, version, snapshot)), "CHECKPOINT_REFERENCE_UNAVAILABLE"
        )
        validate_checkpoint_subject(
            binding=binding.as_record(),
            checkpoint=record,
            artifact_version=version.as_record(),
            evidence_snapshot=snapshot.as_record(),
            predecessor=predecessor.as_record() if predecessor else None,
        )
