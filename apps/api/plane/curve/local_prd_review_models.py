# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Append-only native local Product submissions and decisions."""

from copy import deepcopy
import uuid
from django.db import models
from .prd_models import PrdImmutableModel
from .local_document_store import LocalDocumentUnavailable
from .local_prd_review import validate_submission, validate_decision


class LocalPrdSubmission(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    source = models.ForeignKey("curve.LocalPrdSource", on_delete=models.PROTECT)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_prd_submission"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lprs_scope_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "initiative_version"], name="curve_lprs_version_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                name="curve_lprs_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lprs_digest_ck"
            ),
        ]

    @classmethod
    def from_record(cls, value):
        value = validate_submission(value)
        return cls(
            **{
                key: value[key]
                for key in ("id", "workspace_id", "initiative_id", "source_id", "initiative_version", "digest")
            },
            payload=value,
        )

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        value = validate_submission(self.payload)
        expected = dict(
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            source_id=str(self.source_id),
            initiative_version=self.initiative_version,
            digest=self.digest,
        )
        if any(value[key] != item for key, item in expected.items()):
            raise LocalDocumentUnavailable
        source = self.source
        source.validate_metadata()
        if (
            str(source.workspace_id) != str(self.workspace_id)
            or str(source.initiative_id) != str(self.initiative_id)
            or value["source_digest"] != source.digest
            or value["source_version"] != source.version
            or value["content_digest"] != source.payload["snapshot"]["digest"]
        ):
            raise LocalDocumentUnavailable


class LocalPrdDecision(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    submission = models.OneToOneField("curve.LocalPrdSubmission", on_delete=models.PROTECT)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    state = models.CharField(max_length=32, editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_prd_decision"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lprd_dec_scope_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "initiative_version"], name="curve_lprd_dec_version_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                name="curve_lprd_dec_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["APPROVED", "CHANGES_REQUESTED"]), name="curve_lprd_dec_state_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lprd_dec_digest_ck"
            ),
        ]

    @classmethod
    def from_record(cls, value, submission):
        value = validate_decision(value, submission.as_record())
        return cls(
            **{
                key: value[key]
                for key in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "submission_id",
                    "initiative_version",
                    "state",
                    "digest",
                )
            },
            payload=value,
        )

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        self.submission.validate_metadata()
        value = validate_decision(self.payload, self.submission.as_record())
        expected = dict(
            id=str(self.id),
            workspace_id=str(self.workspace_id),
            initiative_id=str(self.initiative_id),
            submission_id=str(self.submission_id),
            initiative_version=self.initiative_version,
            state=self.state,
            digest=self.digest,
        )
        if any(value[key] != item for key, item in expected.items()):
            raise LocalDocumentUnavailable
