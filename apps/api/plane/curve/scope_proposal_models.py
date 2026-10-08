# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Local non-controlling scope heads and immutable, explicit revision history."""

import uuid

from django.db import models
from django.utils import timezone

from .models import ImmutableRecordError, WorkspaceScopedQuerySetMixin

POLICY_EDITION = "EXPLICIT_EXISTING_WORK_SCOPE_PROPOSAL_V1"


class ScopePurpose(models.TextChoices):
    CONTEXT_EVIDENCE = "CONTEXT_EVIDENCE", "Context evidence"
    PROPOSED_DELIVERY = "PROPOSED_DELIVERY", "Proposed delivery"


class ScopeQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("Scope changes require the guarded command")

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("Scope creation requires the guarded command")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("Scope changes require the guarded command")

    def delete(self):
        raise ImmutableRecordError("Scope history cannot be deleted")


class ScopeRecord(models.Model):
    objects = models.Manager.from_queryset(ScopeQuerySet)()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from .scope_proposal_policy import assert_scope_write

        from .scope_reopening_repository import reopening_write_active, assert_reopening_write

        if reopening_write_active():
            assert_reopening_write(self)
        else:
            assert_scope_write(self)
        if not self._state.adding and not isinstance(self, ScopeProposal):
            raise ImmutableRecordError("Scope revision and member history is immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Scope history cannot be deleted")


class ScopeProposal(ScopeRecord):
    initiative_id = models.UUIDField(editable=False)
    product_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    current_revision_id = models.UUIDField(editable=False)

    class Meta:
        db_table = "curve_scope_proposal"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_scope_ws_id_uq"),
            models.UniqueConstraint(fields=["workspace_id", "initiative_id"], name="curve_scope_init_uq"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="curve_scope_version_ck"),
        ]


class ScopeProposalRevision(ScopeRecord):
    proposal_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(editable=False)
    product_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(editable=False)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    predecessor_id = models.UUIDField(null=True, editable=False)
    item_count = models.PositiveSmallIntegerField(editable=False)
    delivery_count = models.PositiveSmallIntegerField(editable=False)
    membership_digest = models.CharField(max_length=71, editable=False)
    created_by = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    policy_edition = models.CharField(max_length=64, default=POLICY_EDITION, editable=False)
    command_receipt_id = models.UUIDField(editable=False)

    class Meta:
        db_table = "curve_scope_proposal_revision"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_scope_rev_ws_id_uq"),
            models.UniqueConstraint(fields=["workspace_id", "proposal_id", "version"], name="curve_scope_rev_seq_uq"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="curve_scope_rev_version_ck"),
            models.CheckConstraint(condition=models.Q(initiative_version__gte=2), name="curve_scope_init_version_ck"),
            models.CheckConstraint(condition=models.Q(item_count__lte=100), name="curve_scope_item_count_ck"),
            models.CheckConstraint(
                condition=models.Q(delivery_count__lte=models.F("item_count")), name="curve_scope_delivery_count_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(membership_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_scope_digest_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(policy_edition__in=[POLICY_EDITION, "REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1"]),
                name="curve_scope_policy_ck",
            ),
        ]


class ScopeProposalItem(ScopeRecord):
    revision_id = models.UUIDField(editable=False)
    association_id = models.UUIDField(editable=False)
    association_version = models.PositiveBigIntegerField(editable=False)
    provider_installation_id = models.UUIDField(editable=False)
    source_project_id = models.UUIDField(editable=False)
    source_issue_id = models.UUIDField(editable=False)
    purpose = models.CharField(max_length=32, choices=ScopePurpose.choices, editable=False)
    source_observed_at = models.DateTimeField(editable=False)
    source_version = models.CharField(max_length=64, editable=False)
    source_fingerprint = models.CharField(max_length=71, editable=False)

    class Meta:
        db_table = "curve_scope_proposal_item"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "revision_id", "source_issue_id"], name="curve_scope_item_identity_uq"
            ),
            models.CheckConstraint(condition=models.Q(association_version__gte=1), name="curve_scope_assoc_version_ck"),
            models.CheckConstraint(condition=models.Q(purpose__in=ScopePurpose.values), name="curve_scope_purpose_ck"),
            models.CheckConstraint(condition=~models.Q(source_version=""), name="curve_scope_source_version_ck"),
            models.CheckConstraint(
                condition=models.Q(source_fingerprint__regex=r"^sha256:[0-9a-f]{64}$"),
                name="curve_scope_source_digest_ck",
            ),
        ]
