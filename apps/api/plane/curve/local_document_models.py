# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Append-only uploaded PRD metadata; protected document bytes stay in storage."""

from copy import deepcopy
import uuid

from django.db import models

from .local_document_record import validate_local_document_record
from .local_document_store import LocalDocumentUnavailable
from .prd_models import PrdImmutableModel


class LocalPrdSource(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    predecessor = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)
    version = models.PositiveBigIntegerField(editable=False)
    uploaded_by = models.UUIDField(editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_prd_source"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lprd_scope_uq"),
            models.UniqueConstraint(fields=["workspace_id", "initiative", "version"], name="curve_lprd_version_uq"),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=9007199254740991), name="curve_lprd_version_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lprd_digest_ck"
            ),
        ]

    def as_record(self):
        return deepcopy(self.payload)

    @classmethod
    def from_record(cls, value):
        value = validate_local_document_record(value)
        return cls(
            id=value["id"],
            workspace_id=value["workspace_id"],
            initiative_id=value["initiative_id"],
            predecessor_id=value["predecessor_id"],
            version=value["version"],
            uploaded_by=value["uploaded_by"],
            digest=value["digest"],
            payload=value,
        )

    def validate_metadata(self):
        value = validate_local_document_record(self.payload)
        expected = dict(
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            predecessor_id=str(self.predecessor_id) if self.predecessor_id else None,
            version=self.version,
            uploaded_by=str(self.uploaded_by),
            digest=self.digest,
        )
        if any(value[key] != item for key, item in expected.items()):
            raise LocalDocumentUnavailable
