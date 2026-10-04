# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Immutable reopening provenance, never a fabricated PRD gate decision."""

from copy import deepcopy
import uuid

from django.db import models
from django.utils import timezone

from .models import ImmutableRecordError, WorkspaceScopedQuerySetMixin


class ReopeningQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Scope reopening records are immutable")

    def delete(self):
        raise ImmutableRecordError("Scope reopening records are immutable")

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("Scope reopening requires its exact authorization receipt")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("Scope reopening records are immutable")


class ScopeReopening(models.Model):
    objects = models.Manager.from_queryset(ReopeningQuerySet)()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    product_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(db_index=True, editable=False)
    proposal_id = models.UUIDField(editable=False)
    scope_revision_id = models.UUIDField(unique=True, editable=False)
    predecessor_revision_id = models.UUIDField(editable=False)
    previous_initiative_version = models.PositiveBigIntegerField(editable=False)
    previous_state = models.CharField(max_length=40, editable=False)
    previous_checkpoint_id = models.UUIDField(null=True, editable=False)
    previous_decision_id = models.UUIDField(null=True, editable=False)
    previous_pending_reopening_id = models.UUIDField(null=True, editable=False)
    created_by = models.UUIDField(editable=False)
    reason_digest = models.CharField(max_length=71, editable=False)
    request_digest = models.CharField(max_length=71, editable=False)
    policy_decision_id = models.UUIDField(editable=False)
    command_receipt_id = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_scope_reopening"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative_id", "id"], name="curve_reopen_scope_uq"),
            models.CheckConstraint(
                condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_reopen_digest_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(reason_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_reopen_reason_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_reopen_request_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(previous_initiative_version__gte=1), name="curve_reopen_version_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(previous_state__in=["ALIGNING", "PRD_REVIEW", "PLANNING"]),
                name="curve_reopen_state_ck",
            ),
        ]

    def as_record(self):
        from .scope_reopening_contracts import validate_reopening_contract, metadata_digest

        data = deepcopy(self.payload)
        validate_reopening_contract("scope-reopening-receipt-v1", data)
        direct = (
            "id",
            "workspace_id",
            "product_id",
            "initiative_id",
            "created_by",
            "policy_decision_id",
            "command_receipt_id",
        )
        revision = data["revision"]
        if (
            any(data[key] != str(getattr(self, key)) for key in direct)
            or data["previous_initiative_version"] != self.previous_initiative_version
            or data["previous_state"] != self.previous_state
            or data["reason_digest"] != self.reason_digest
            or data["recorded_at"] != self.recorded_at.isoformat()
            or revision["id"] != str(self.scope_revision_id)
            or revision["proposal_id"] != str(self.proposal_id)
            or revision["predecessor_id"] != str(self.predecessor_revision_id)
            or data["historical_checkpoint_status"] != ("RETAINED_STALE" if self.previous_checkpoint_id else "NONE")
            or data["digest"] != self.digest
            or metadata_digest(data) != self.digest
        ):
            raise ImmutableRecordError("Scope reopening record integrity unavailable")
        return data

    def save(self, *args, **kwargs):
        from .scope_reopening_repository import assert_reopening_write

        assert_reopening_write(self)
        if not self._state.adding:
            raise ImmutableRecordError("Scope reopening records are immutable")
        self.as_record()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Scope reopening records are immutable")
