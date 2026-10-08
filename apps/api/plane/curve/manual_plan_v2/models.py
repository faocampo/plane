# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""One mutable draft head and append-only, private-input revision metadata."""

import uuid
from django.db import models
from django.utils import timezone

from .validation import MAX_INTEGER


class ImmutableDraftError(PermissionError):
    pass


class DraftQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableDraftError("Use the guarded manual-plan command")

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableDraftError("Use the guarded manual-plan command")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableDraftError("Use the guarded manual-plan command")

    def delete(self):
        raise ImmutableDraftError("Manual-plan history is retained")


class DraftRecord(models.Model):
    objects = models.Manager.from_queryset(DraftQuerySet)()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)

    class Meta:
        abstract = True
        app_label = "curve"

    def save(self, *args, **kwargs):
        from .repository import assert_draft_write

        assert_draft_write(self)
        if not self._state.adding and type(self) is not ManualPlanDraftV2:
            raise ImmutableDraftError("Manual-plan revisions are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableDraftError("Manual-plan history is retained")


class ManualPlanDraftV2(DraftRecord):
    initiative_id = models.UUIDField(editable=False)
    product_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    current_revision_id = models.UUIDField(editable=False)

    class Meta:
        app_label = "curve"
        db_table = "curve_manual_plan_draft_v2"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_mpd2_ws_id_uq"),
            models.UniqueConstraint(fields=["workspace_id", "initiative_id"], name="curve_mpd2_init_uq"),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=MAX_INTEGER), name="curve_mpd2_ver_ck"
            ),
        ]


class ManualPlanRevisionV2(DraftRecord):
    product_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(db_index=True, editable=False)
    draft_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(editable=False)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    predecessor_id = models.UUIDField(null=True, editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)
    original_input_identity = models.JSONField(editable=False)
    input_identity_digest = models.CharField(max_length=71, editable=False)
    validation_receipt = models.JSONField(editable=False)
    validation_receipt_digest = models.CharField(max_length=71, editable=False)
    policy_decision_id = models.UUIDField(editable=False)
    command_receipt_id = models.UUIDField(editable=False)
    created_by = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "curve"
        db_table = "curve_manual_plan_revision_v2"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_mpr2_ws_id_uq"),
            models.UniqueConstraint(fields=["workspace_id", "draft_id", "version"], name="curve_mpr2_seq_uq"),
            models.UniqueConstraint(fields=["workspace_id", "command_receipt_id"], name="curve_mpr2_cmd_uq"),
            models.UniqueConstraint(fields=["workspace_id", "policy_decision_id"], name="curve_mpr2_policy_uq"),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=MAX_INTEGER), name="curve_mpr2_ver_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=2, initiative_version__lte=MAX_INTEGER),
                name="curve_mpr2_init_ver_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(version=1, predecessor_id__isnull=True)
                    | models.Q(version__gt=1, predecessor_id__isnull=False)
                ),
                name="curve_mpr2_prev_ck",
            ),
            *[
                models.CheckConstraint(condition=models.Q(**{key + "__regex": r"^sha256:[0-9a-f]{64}$"}), name=name)
                for key, name in (
                    ("digest", "curve_mpr2_digest_ck"),
                    ("input_identity_digest", "curve_mpr2_input_ck"),
                    ("validation_receipt_digest", "curve_mpr2_valid_ck"),
                )
            ],
        ]

    def as_record(self):
        from .contracts import verify_revision

        return verify_revision(self)
