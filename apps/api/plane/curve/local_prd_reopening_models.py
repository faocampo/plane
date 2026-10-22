# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from copy import deepcopy
import uuid
from django.db import models
from .prd_models import PrdImmutableModel
from .local_document_store import LocalDocumentUnavailable
from .local_prd_reopening import validate_reopening


class LocalPrdReopening(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    submission = models.OneToOneField("curve.LocalPrdSubmission", on_delete=models.PROTECT)
    decision = models.OneToOneField("curve.LocalPrdDecision", on_delete=models.PROTECT)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_prd_reopening"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lpro_scope_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "initiative_version"], name="curve_lpro_version_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                name="curve_lpro_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lpro_digest_ck"
            ),
        ]

    @classmethod
    def from_record(cls, value, submission, decision):
        value = validate_reopening(value, submission.as_record(), decision.as_record())
        return cls(
            **{
                key: value[key]
                for key in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "submission_id",
                    "decision_id",
                    "initiative_version",
                    "digest",
                )
            },
            payload=value,
        )

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        self.submission.validate_metadata()
        self.decision.validate_metadata()
        value = validate_reopening(self.payload, self.submission.as_record(), self.decision.as_record())
        expected = dict(
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            submission_id=str(self.submission_id),
            decision_id=str(self.decision_id),
            initiative_version=self.initiative_version,
            digest=self.digest,
        )
        if any(value[key] != item for key, item in expected.items()):
            raise LocalDocumentUnavailable
