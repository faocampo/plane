# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Immutable submitted PRD metadata. Runtime source/storage activation is separate."""

import uuid
from copy import deepcopy

from django.db import models
from django.utils import timezone

from .models import ImmutableQuerySet, ImmutableRecordError, WorkspaceScopedQuerySetMixin
from .prd_metadata_validation import MAX_SAFE_INTEGER, instant, metadata_digest, require_metadata, validate_record


class PrdImmutableQuerySet(WorkspaceScopedQuerySetMixin, ImmutableQuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("PRD metadata requires validated individual inserts")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("PRD metadata is append-only")


class PrdImmutableModel(models.Model):
    objects = models.Manager.from_queryset(PrdImmutableQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("PRD metadata is append-only")
        self.validate_metadata()
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("PRD metadata erasure requires a governed retention operation")


class PrdArtifact(models.Model):
    objects = models.Manager.from_queryset(PrdImmutableQuerySet)()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    current_version = models.ForeignKey(
        "curve.PrdArtifactVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_constraint=False,
        related_name="current_for_artifact",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_prd_artifact"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative"], name="curve_prd_art_ws_init_uq"),
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_prd_art_scope_uq"),
        ]

    def as_record(self):
        return dict(
            schema_version="1.0-candidate",
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            kind="PRD",
            created_at=instant(self.created_at),
            current_version_id=str(self.current_version_id) if self.current_version_id else None,
        )

    def save(self, *args, **kwargs):
        validate_record("Artifact", self.as_record())
        kwargs["force_insert" if self._state.adding else "force_update"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("PRD artifact deletion requires a governed retention operation")


class PrdEvidenceItemVersion(PrdImmutableModel):
    row_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_id = models.UUIDField(editable=False)
    workspace_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(editable=False)
    provider_connection = models.ForeignKey("curve.ProviderConnection", on_delete=models.PROTECT)
    envelope_digest = models.CharField(max_length=71, editable=False)
    record = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_prd_evidence_item_version"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "evidence_id", "version"], name="curve_prd_evidence_ver_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=MAX_SAFE_INTEGER), name="curve_prd_evidence_ver_ck"
            ),
        ]

    def validate_metadata(self):
        item = self.record
        validate_record("EvidenceItem", item)
        require_metadata(
            item["id"] == str(self.evidence_id)
            and item["workspace_id"] == str(self.workspace_id)
            and item["version"] == self.version
            and item["source"]["provider_connection_id"] == str(self.provider_connection_id),
            "PRD_EVIDENCE_IDENTITY_INVALID",
        )
        envelope = item["access_envelope"]
        self.envelope_digest = metadata_digest(envelope)
        require_metadata(
            envelope["workspace_id"] == item["workspace_id"]
            and envelope["effective_principal"] == item["effective_principal"]
            and item["effective_principal"]["actor_type"] == "HUMAN"
            and envelope["classification"] == item["classification"]
            and envelope["redaction_state"] == item["redaction_state"]
            and envelope["retention_policy_ref"]["resource_type"] == "RETENTION_POLICY_VERSION"
            and envelope["retention_policy_ref"]["resource_id"] == item["retention_policy_version_id"]
            and item["source"]["source_ref"] in envelope["source_refs"],
            "PRD_EVIDENCE_ENVELOPE_INVALID",
        )
        if item["content"] is not None:
            require_metadata(
                item["content"]["digest"] == item["content_digest"]
                and 0 < item["content"]["size_bytes"] <= MAX_SAFE_INTEGER,
                "PRD_EVIDENCE_CONTENT_INVALID",
            )


class PrdEvidenceSnapshot(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    artifact_version = models.ForeignKey(
        "curve.PrdArtifactVersion", on_delete=models.PROTECT, db_constraint=False, related_name="snapshots"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=71, editable=False)
    items = models.JSONField(default=list, editable=False)

    class Meta:
        db_table = "curve_prd_evidence_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "artifact_version"], name="curve_prd_snapshot_ver_uq"
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "artifact_version", "id"], name="curve_prd_snapshot_scope_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_prd_snapshot_digest_ck"
            ),
        ]

    def as_record(self):
        return dict(
            schema_version="1.0-candidate",
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            artifact_version_id=str(self.artifact_version_id),
            created_at=instant(self.created_at),
            digest=self.digest,
            items=deepcopy(self.items),
        )

    def compute_digest(self):
        record = self.as_record()
        record.pop("digest")
        return metadata_digest(record)

    def validate_metadata(self):
        validate_record("EvidenceSnapshot", self.as_record())
        require_metadata(self.digest == self.compute_digest(), "PRD_SNAPSHOT_DIGEST_INVALID")
        seen = set()
        for ordinal, entry in enumerate(self.items):
            key = (entry["evidence_item_id"], entry["evidence_item_version"])
            require_metadata(entry["ordinal"] == ordinal and key not in seen, "PRD_SNAPSHOT_MEMBERSHIP_INVALID")
            seen.add(key)
            if entry["material"]:
                require_metadata(bool(entry["claim_refs"]), "PRD_MATERIAL_CLAIM_REQUIRED")
            if entry["selected_excerpt_ref"]:
                require_metadata(
                    0 < entry["selected_excerpt_ref"]["size_bytes"] <= MAX_SAFE_INTEGER, "PRD_EXCERPT_INVALID"
                )


class PrdArtifactVersion(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    artifact = models.ForeignKey(PrdArtifact, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveBigIntegerField(editable=False)
    parent_version = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, db_constraint=False)
    evidence_snapshot = models.ForeignKey(PrdEvidenceSnapshot, on_delete=models.PROTECT, db_constraint=False)
    body_object_id = models.UUIDField(editable=False)
    body_digest = models.CharField(max_length=71, editable=False)
    body_size_bytes = models.PositiveBigIntegerField(editable=False)
    body_schema_id = models.CharField(max_length=512, editable=False)
    body_schema_version = models.PositiveBigIntegerField(editable=False)
    access_envelope_id = models.UUIDField(editable=False)
    retention_policy_version_id = models.UUIDField(editable=False)
    created_by = models.JSONField(editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_prd_artifact_version"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "artifact", "version_number"], name="curve_prd_art_ver_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "artifact", "id"], name="curve_prd_ver_art_scope_uq"
            ),
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_prd_ver_scope_uq"),
            models.CheckConstraint(
                condition=models.Q(version_number__gte=1, version_number__lte=MAX_SAFE_INTEGER),
                name="curve_prd_ver_number_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(body_size_bytes__gte=1, body_size_bytes__lte=MAX_SAFE_INTEGER),
                name="curve_prd_ver_size_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(body_schema_version__gte=1, body_schema_version__lte=MAX_SAFE_INTEGER),
                name="curve_prd_ver_schema_num_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(body_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_prd_ver_digest_ck"
            ),
            models.CheckConstraint(condition=~models.Q(body_schema_id=""), name="curve_prd_ver_schema_id_ck"),
        ]

    def as_record(self):
        return dict(
            schema_version="1.0-candidate",
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            artifact_id=str(self.artifact_id),
            version_number=self.version_number,
            state="SUBMITTED",
            body=dict(
                object_id=str(self.body_object_id),
                digest=self.body_digest,
                size_bytes=self.body_size_bytes,
                media_type="application/json",
            ),
            body_schema_id=self.body_schema_id,
            body_schema_version=self.body_schema_version,
            body_digest=self.body_digest,
            evidence_snapshot_id=str(self.evidence_snapshot_id),
            parent_version_id=str(self.parent_version_id) if self.parent_version_id else None,
            created_by=deepcopy(self.created_by),
            created_at=instant(self.created_at),
            generation_provenance=None,
            access_envelope_id=str(self.access_envelope_id),
            retention_policy_version_id=str(self.retention_policy_version_id),
        )

    def validate_metadata(self):
        validate_record("ArtifactVersion", self.as_record())
        require_metadata(self.created_by["actor_type"] == "HUMAN", "PRD_HUMAN_AUTHOR_REQUIRED")
