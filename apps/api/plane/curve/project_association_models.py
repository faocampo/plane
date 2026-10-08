# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Additive local association identity; never a Plane source mutation."""

import uuid

from django.db import models
from django.utils import timezone

from .models import ImmutableRecordError, WorkspaceScopedQuerySetMixin


POLICY_EDITION = "EXPLICIT_EXISTING_PROJECT_ASSOCIATION_V1"


class ProjectAssociationState(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ENDED = "ENDED", "Ended"


class ProjectAssociationQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Association changes require the guarded command service")

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("Association creation requires the guarded command service")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("Association changes require the guarded command service")

    def delete(self):
        raise ImmutableRecordError("Association history cannot be deleted")


class ProjectAssociation(models.Model):
    objects = models.Manager.from_queryset(ProjectAssociationQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    provider_installation_id = models.UUIDField(editable=False)
    source_project_id = models.UUIDField(editable=False)
    product_id = models.UUIDField(db_index=True, editable=False)
    state = models.CharField(
        max_length=16, choices=ProjectAssociationState.choices, default=ProjectAssociationState.ACTIVE
    )
    version = models.PositiveBigIntegerField(default=1, editable=False)
    effective_at = models.DateTimeField(default=timezone.now, editable=False)
    initiated_by = models.UUIDField(editable=False)
    policy_edition = models.CharField(max_length=64, default=POLICY_EDITION, editable=False)
    command_receipt_id = models.UUIDField(editable=False)
    source_observed_at = models.DateTimeField(default=timezone.now, editable=False)
    source_version = models.CharField(max_length=64, editable=False)
    ended_at = models.DateTimeField(null=True, editable=False)
    ended_by = models.UUIDField(null=True, editable=False)
    end_reason = models.CharField(max_length=1000, null=True, editable=False)
    end_receipt_id = models.UUIDField(null=True, editable=False)

    IMMUTABLE_FIELDS = (
        "id",
        "workspace_id",
        "provider_installation_id",
        "source_project_id",
        "product_id",
        "effective_at",
        "initiated_by",
        "policy_edition",
        "command_receipt_id",
        "source_observed_at",
        "source_version",
    )

    class Meta:
        db_table = "curve_project_association"
        indexes = [models.Index(fields=["workspace_id", "product_id", "state"], name="curve_passoc_product_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "provider_installation_id", "source_project_id"],
                condition=models.Q(state="ACTIVE"),
                name="curve_passoc_active_source_uq",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="curve_passoc_version_ck"),
            models.CheckConstraint(condition=models.Q(policy_edition=POLICY_EDITION), name="curve_passoc_policy_ck"),
            models.CheckConstraint(condition=~models.Q(source_version=""), name="curve_passoc_source_version_ck"),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="ACTIVE",
                        ended_at__isnull=True,
                        ended_by__isnull=True,
                        end_reason__isnull=True,
                        end_receipt_id__isnull=True,
                    )
                    | (
                        models.Q(
                            state="ENDED",
                            ended_at__isnull=False,
                            ended_by__isnull=False,
                            end_reason__isnull=False,
                            end_receipt_id__isnull=False,
                        )
                        & ~models.Q(end_reason="")
                        & models.Q(ended_at__gte=models.F("effective_at"))
                    )
                ),
                name="curve_passoc_end_fields_ck",
            ),
        ]

    def save(self, *args, **kwargs):
        from .project_association_policy import assert_association_write

        assert_association_write(self, creating=self._state.adding)
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS, "state", "version").first()
            if original is None or any(original[field] != getattr(self, field) for field in self.IMMUTABLE_FIELDS):
                raise ImmutableRecordError("Association identity and initial observation are immutable")
            if original["state"] != "ACTIVE" or self.state != "ENDED" or self.version != original["version"] + 1:
                raise ImmutableRecordError("Only an exact-version ACTIVE to ENDED transition is permitted")
        elif self.state != "ACTIVE" or self.version != 1:
            raise ImmutableRecordError("Association creation must begin ACTIVE at version one")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Association history cannot be deleted")
