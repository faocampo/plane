# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from copy import deepcopy
import uuid
from django.db import models
from .prd_models import PrdImmutableModel
from .local_document_store import LocalDocumentUnavailable
from .local_plan_review import validate_plan_revision


class LocalPlanRevision(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    prd_submission = models.ForeignKey("curve.LocalPrdSubmission", on_delete=models.PROTECT)
    prd_decision = models.ForeignKey("curve.LocalPrdDecision", on_delete=models.PROTECT)
    predecessor = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    version = models.PositiveBigIntegerField(editable=False)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_plan_revision"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lplan_scope_uq"),
            models.UniqueConstraint(fields=["workspace_id", "initiative", "version"], name="curve_lplan_version_uq"),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=9007199254740991), name="curve_lplan_version_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                name="curve_lplan_initversion_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lplan_digest_ck"
            ),
        ]

    @classmethod
    def from_record(cls, value, submission, approval):
        value = validate_plan_revision(value, submission=submission.as_record(), approval=approval.as_record())
        return cls(
            **{
                key: value[key]
                for key in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "prd_submission_id",
                    "prd_decision_id",
                    "predecessor_id",
                    "version",
                    "initiative_version",
                    "digest",
                )
            },
            payload=value,
        )

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        self.prd_submission.validate_metadata()
        self.prd_decision.validate_metadata()
        value = validate_plan_revision(
            self.payload, submission=self.prd_submission.as_record(), approval=self.prd_decision.as_record()
        )
        expected = {
            key: str(getattr(self, key))
            for key in ("id", "workspace_id", "initiative_id", "prd_submission_id", "prd_decision_id")
        }
        expected.update(
            version=self.version,
            initiative_version=self.initiative_version,
            digest=self.digest,
            predecessor_id=str(self.predecessor_id) if self.predecessor_id else None,
        )
        if any(value[key] != item for key, item in expected.items()):
            raise LocalDocumentUnavailable
        if self.predecessor_id:
            prior = self.predecessor
            if (
                str(prior.workspace_id) != str(self.workspace_id)
                or str(prior.initiative_id) != str(self.initiative_id)
                or prior.version + 1 != self.version
            ):
                raise LocalDocumentUnavailable


class LocalPlanSubmission(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    plan_revision = models.OneToOneField("curve.LocalPlanRevision", on_delete=models.PROTECT)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_plan_submission"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lpls_scope_uq"),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                name="curve_lpls_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lpls_digest_ck"
            ),
        ]

    @classmethod
    def from_record(cls, value, plan):
        from .local_plan_review import validate_plan_submission

        plan.validate_metadata()
        value = validate_plan_submission(
            value,
            plan=plan.as_record(),
            prd_submission=plan.prd_submission.as_record(),
            prd_approval=plan.prd_decision.as_record(),
        )
        return cls(
            **{
                key: value[key]
                for key in ("id", "workspace_id", "initiative_id", "plan_revision_id", "initiative_version", "digest")
            },
            payload=value,
        )

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        validated = self.from_record(self.payload, self.plan_revision)
        for key in ("id", "workspace_id", "initiative_id", "plan_revision_id", "initiative_version", "digest"):
            if str(getattr(self, key)) != str(getattr(validated, key)):
                raise LocalDocumentUnavailable


class LocalPlanDecision(PrdImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    plan_submission = models.OneToOneField("curve.LocalPlanSubmission", on_delete=models.PROTECT)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    state = models.CharField(max_length=32, editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_local_plan_decision"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lpld_scope_uq"),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                name="curve_lpld_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["APPROVED", "CHANGES_REQUESTED"]), name="curve_lpld_state_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lpld_digest_ck"
            ),
        ]

    @classmethod
    def from_record(cls, value, submission):
        from .local_plan_review import validate_plan_decision

        submission.validate_metadata()
        plan = submission.plan_revision
        value = validate_plan_decision(
            value,
            submission=submission.as_record(),
            plan=plan.as_record(),
            prd_submission=plan.prd_submission.as_record(),
            prd_approval=plan.prd_decision.as_record(),
        )
        return cls(
            **{
                key: value[key]
                for key in (
                    "id",
                    "workspace_id",
                    "initiative_id",
                    "plan_submission_id",
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
        validated = self.from_record(self.payload, self.plan_submission)
        for key in (
            "id",
            "workspace_id",
            "initiative_id",
            "plan_submission_id",
            "initiative_version",
            "state",
            "digest",
        ):
            if str(getattr(self, key)) != str(getattr(validated, key)):
                raise LocalDocumentUnavailable
