# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Additive roadmap persistence; command authority is resolved by scoped services."""

import uuid

from django.db import models

from .models import ImmutableRecordError, ImmutableRecordModel, ProductQuerySet


class RoadmapQuerySet(ProductQuerySet):
    def delete(self):
        raise ImmutableRecordError("Roadmap aggregates retain history; hard deletion is unavailable")


class RoadmapAggregate(models.Model):
    objects = models.Manager.from_queryset(RoadmapQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(editable=False)
    product_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)
    created_by = models.JSONField(editable=False)
    updated_by = models.JSONField(editable=False)
    tombstoned_at = models.DateTimeField(null=True, blank=True, editable=False)
    tombstoned_by = models.JSONField(null=True, blank=True, editable=False)
    tombstone_reason = models.TextField(null=True, blank=True, editable=False)
    immutable_identity_fields = ("workspace_id", "product_id", "created_at", "created_by")

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = (
                type(self)
                .objects.filter(workspace_id=self.workspace_id, pk=self.pk)
                .values(*self.immutable_identity_fields)
                .first()
            )
            if original is None or any(
                original[field] != getattr(self, field) for field in self.immutable_identity_fields
            ):
                raise ImmutableRecordError("Roadmap identity and creation attribution are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Roadmap aggregates retain history; hard deletion is unavailable")


def aggregate_constraints(prefix):
    return [
        models.UniqueConstraint(fields=["workspace_id", "product_id", "id"], name=f"{prefix}_scope_uq"),
        models.CheckConstraint(condition=models.Q(version__gte=1), name=f"{prefix}_version_ck"),
        models.CheckConstraint(
            condition=(
                models.Q(tombstoned_at__isnull=True, tombstoned_by__isnull=True, tombstone_reason__isnull=True)
                | models.Q(
                    tombstoned_at__isnull=False,
                    tombstoned_by__isnull=False,
                    tombstone_reason__isnull=False,
                    tombstone_reason__regex=r"\S",
                )
            ),
            name=f"{prefix}_tombstone_ck",
        ),
    ]


class Roadmap(RoadmapAggregate):
    name = models.CharField(max_length=255)
    owner_user_id = models.UUIDField()
    horizon_start = models.DateField(null=True, blank=True)
    horizon_end = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "curve_roadmap"
        constraints = aggregate_constraints("curve_rmap") + [
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="curve_rmap_name_ck"),
            models.CheckConstraint(
                condition=models.Q(horizon_start__isnull=True)
                | models.Q(horizon_end__isnull=True)
                | models.Q(horizon_start__lte=models.F("horizon_end")),
                name="curve_rmap_horizon_ck",
            ),
        ]


class MilestoneType(models.TextChoices):
    RELEASE_VERSION = "RELEASE_VERSION", "Release or version"
    CALENDAR_PERIOD = "CALENDAR_PERIOD", "Calendar period"
    PRODUCT_OUTCOME = "PRODUCT_OUTCOME", "Product outcome"
    INTERNAL_DEVELOPMENT_PHASE = "INTERNAL_DEVELOPMENT_PHASE", "Internal development phase"


class Milestone(RoadmapAggregate):
    roadmap_id = models.UUIDField(editable=False)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=32, choices=MilestoneType.choices)
    position = models.PositiveBigIntegerField()
    target_start = models.DateField(null=True, blank=True)
    target_end = models.DateField(null=True, blank=True)
    immutable_identity_fields = RoadmapAggregate.immutable_identity_fields + ("roadmap_id",)

    class Meta:
        db_table = "curve_milestone"
        constraints = aggregate_constraints("curve_mstone") + [
            models.UniqueConstraint(
                fields=["workspace_id", "product_id", "roadmap_id", "id"], name="curve_mstone_rmap_scope_uq"
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "roadmap_id", "position"],
                name="curve_mstone_position_uq",
                deferrable=models.Deferrable.DEFERRED,
            ),
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="curve_mstone_name_ck"),
            models.CheckConstraint(condition=models.Q(type__in=MilestoneType.values), name="curve_mstone_type_ck"),
            models.CheckConstraint(
                condition=models.Q(target_start__isnull=True)
                | models.Q(target_end__isnull=True)
                | models.Q(target_start__lte=models.F("target_end")),
                name="curve_mstone_target_ck",
            ),
        ]


class Feature(RoadmapAggregate):
    name = models.CharField(max_length=255)
    description = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "curve_feature"
        constraints = aggregate_constraints("curve_feature") + [
            models.CheckConstraint(condition=models.Q(name__regex=r"\S"), name="curve_feature_name_ck"),
        ]


class RoadmapItemStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "Proposed"
    COMMITTED = "COMMITTED", "Committed"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    PAUSED = "PAUSED", "Paused"
    DELIVERED = "DELIVERED", "Delivered"
    CANCELLED = "CANCELLED", "Cancelled"


class RoadmapItem(RoadmapAggregate):
    roadmap_id = models.UUIDField(editable=False)
    milestone_id = models.UUIDField()
    feature_id = models.UUIDField(editable=False)
    defining_initiative_id = models.UUIDField(editable=False)
    owner_user_id = models.UUIDField()
    scope_body = models.JSONField()
    status = models.CharField(max_length=16, choices=RoadmapItemStatus.choices, default=RoadmapItemStatus.PROPOSED)
    priority = models.CharField(max_length=8)
    confidence = models.CharField(max_length=6)
    health = models.CharField(max_length=9)
    planned_start = models.DateField(null=True, blank=True)
    planned_end = models.DateField(null=True, blank=True)
    declared_progress = models.PositiveSmallIntegerField(default=0)
    progress_note = models.TextField(default="")
    approved_prd_version_id = models.UUIDField(null=True, blank=True)
    immutable_identity_fields = RoadmapAggregate.immutable_identity_fields + (
        "roadmap_id",
        "feature_id",
        "defining_initiative_id",
    )

    class Meta:
        db_table = "curve_roadmap_item"
        constraints = aggregate_constraints("curve_ritem") + [
            models.UniqueConstraint(
                fields=["workspace_id", "product_id", "defining_initiative_id", "id"], name="curve_ritem_pair_uq"
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "defining_initiative_id"], name="curve_ritem_initiative_uq"
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "milestone_id", "feature_id"], name="curve_ritem_placement_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=RoadmapItemStatus.values), name="curve_ritem_status_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(priority__in=["CRITICAL", "HIGH", "MEDIUM", "LOW"]), name="curve_ritem_priority_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__in=["HIGH", "MEDIUM", "LOW"]), name="curve_ritem_confidence_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(health__in=["ON_TRACK", "AT_RISK", "OFF_TRACK", "UNKNOWN"]),
                name="curve_ritem_health_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(declared_progress__gte=0, declared_progress__lte=100), name="curve_ritem_progress_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(status="PROPOSED", planned_start__isnull=True, planned_end__isnull=True)
                | models.Q(
                    planned_start__isnull=False, planned_end__isnull=False, planned_start__lte=models.F("planned_end")
                ),
                name="curve_ritem_schedule_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="COMMITTED") | models.Q(approved_prd_version_id__isnull=False),
                name="curve_ritem_prd_ck",
            ),
        ]


class RoadmapItemHistory(ImmutableRecordModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(editable=False)
    product_id = models.UUIDField(editable=False)
    roadmap_item_id = models.UUIDField(editable=False)
    sequence = models.PositiveBigIntegerField(editable=False)
    recorded_at = models.DateTimeField(editable=False)
    recorded_by = models.JSONField(editable=False)
    change_type = models.CharField(max_length=32, editable=False)
    before_version = models.PositiveBigIntegerField(editable=False)
    after_version = models.PositiveBigIntegerField(editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_roadmap_item_history"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "roadmap_item_id", "sequence"], name="curve_rihist_sequence_uq"
            ),
            models.CheckConstraint(condition=models.Q(sequence__gte=1), name="curve_rihist_sequence_ck"),
            models.CheckConstraint(
                condition=models.Q(before_version__gte=1, after_version=models.F("before_version") + 1),
                name="curve_rihist_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(change_type__in=["PROGRESS_CHANGED", "MILESTONE_MOVED"]), name="curve_rihist_type_ck"
            ),
        ]
