# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.db.models.lookups import Exact, GreaterThan
from django.utils import timezone


DIGEST_MAX_LENGTH = 71


class ImmutableRecordError(ValueError):
    """Raised when application code attempts to rewrite immutable Curve history."""


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError(f"{self.model.__name__} records are append-only")

    def delete(self):
        raise ImmutableRecordError(f"{self.model.__name__} records are append-only")


class ImmutableRecordModel(models.Model):
    objects = models.Manager.from_queryset(ImmutableQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(f"{type(self).__name__} records are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError(f"{type(self).__name__} records are append-only")


class WorkspaceScopedModel(models.Model):
    """Abstract base for mutable Curve aggregate roots.

    Plane remains authoritative for workspace identity and membership. Curve
    stores the Plane workspace UUID as an opaque scope value without a hard
    foreign key, which keeps Curve lifecycle and migrations additive.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    created_by = models.JSONField(editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)
    updated_by = models.JSONField(editable=False)
    tombstoned_at = models.DateTimeField(null=True, blank=True, editable=False)
    tombstoned_by = models.JSONField(null=True, blank=True, editable=False)
    tombstone_reason = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        abstract = True


class WorkspaceScopedQuerySetMixin:
    """Workspace-first repository helpers for Curve-owned records."""

    def for_workspace(self, workspace_id):
        if workspace_id is None:
            raise ValueError("workspace_id is required")
        return self.filter(workspace_id=workspace_id)

    def find_by_id(self, *, workspace_id, record_id, for_update=False):
        queryset = self.for_workspace(workspace_id)
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.filter(id=record_id).first()


class ProviderConnectionQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    _REFERENCE_FIELDS = frozenset({"workspace_id", "current_capability", "current_capability_id"})

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("ProviderConnection bulk creation bypasses workspace reference validation")

    def bulk_update(self, objs, fields, *args, **kwargs):
        if self._REFERENCE_FIELDS.intersection(fields):
            raise ImmutableRecordError("ProviderConnection references require locked instance updates")
        return super().bulk_update(objs, fields, *args, **kwargs)

    def update(self, **kwargs):
        if self._REFERENCE_FIELDS.intersection(kwargs):
            raise ImmutableRecordError("ProviderConnection references require locked instance updates")
        return super().update(**kwargs)


class ProviderCapabilityQuerySet(WorkspaceScopedQuerySetMixin, ImmutableQuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("ProviderCapability creation requires the workspace-scoped repository")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("ProviderCapability records are append-only")


class ProductQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    """Workspace-first Product access that forbids policy-bypassing bulk writes."""

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("Product creation requires the workspace-scoped command service")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("Product changes require the workspace-scoped command service")

    def update(self, **kwargs):
        raise ImmutableRecordError("Product changes require the workspace-scoped command service")


class InitiativeQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    """Workspace-first Initiative access that forbids command bypasses."""

    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("Initiative creation requires the workspace-scoped command service")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("Initiative changes require the workspace-scoped command service")

    def update(self, **kwargs):
        raise ImmutableRecordError("Initiative changes require the workspace-scoped command service")


class GateAssignmentQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("GateAssignment creation requires the Initiative command service")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("GateAssignment records are immutable in M1-01A")

    def update(self, **kwargs):
        raise ImmutableRecordError("GateAssignment records are immutable in M1-01A")


class DataClassification(models.TextChoices):
    INTERNAL = "INTERNAL", "Internal"
    CONFIDENTIAL = "CONFIDENTIAL", "Confidential"
    RESTRICTED = "RESTRICTED", "Restricted"


class ProviderType(models.TextChoices):
    FAKE_LOCAL = "FAKE_LOCAL", "Fake local"
    ONYX = "ONYX", "Onyx"
    MCP = "MCP", "MCP"
    ORCA_HUMAN_ASSISTANCE = "ORCA_HUMAN_ASSISTANCE", "Orca human assistance"
    MODEL_GATEWAY = "MODEL_GATEWAY", "Model gateway"
    OPENHANDS = "OPENHANDS", "OpenHands"
    GITHUB = "GITHUB", "GitHub"
    GITLAB = "GITLAB", "GitLab"
    QUALITY = "QUALITY", "Quality"
    FEATURE_FLAG = "FEATURE_FLAG", "Feature flag"
    DOCUMENTATION = "DOCUMENTATION", "Documentation"
    MONITORING = "MONITORING", "Monitoring"
    PROTOTYPE = "PROTOTYPE", "Prototype"


class ProviderEnvironment(models.TextChoices):
    LOCAL = "LOCAL", "Local"
    STAGING = "STAGING", "Staging"
    PRODUCTION = "PRODUCTION", "Production"


class ProviderConnectionStatus(models.TextChoices):
    PENDING_VALIDATION = "PENDING_VALIDATION", "Pending validation"
    ACTIVE = "ACTIVE", "Active"
    DEGRADED = "DEGRADED", "Degraded"
    DISABLED = "DISABLED", "Disabled"
    REVOKED = "REVOKED", "Revoked"


class ProviderCapabilityRisk(models.TextChoices):
    READ = "READ", "Read"
    WORKFLOW_WRITE = "WORKFLOW_WRITE", "Workflow write"
    EXTERNAL_MUTATION = "EXTERNAL_MUTATION", "External mutation"


class OperationType(models.TextChoices):
    FOUNDATION_PROBE = "FOUNDATION_PROBE", "Foundation probe"
    WORKFLOW_COMMAND = "WORKFLOW_COMMAND", "Workflow command"
    PROVIDER_RECONCILIATION = "PROVIDER_RECONCILIATION", "Provider reconciliation"


class OperationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    QUEUED = "QUEUED", "Queued"
    RUNNING = "RUNNING", "Running"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN", "Waiting for human"
    CANCEL_REQUESTED = "CANCEL_REQUESTED", "Cancel requested"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class Operation(WorkspaceScopedModel):
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    operation_type = models.CharField(max_length=32, choices=OperationType.choices)
    status = models.CharField(max_length=32, choices=OperationStatus.choices, default=OperationStatus.PENDING)
    command_type = models.CharField(max_length=100)
    target = models.JSONField()
    idempotency_key_digest = models.CharField(max_length=DIGEST_MAX_LENGTH)
    causation_id = models.CharField(max_length=255, null=True, blank=True)
    workflow_id = models.CharField(max_length=1000, null=True, blank=True)
    policy_version_ref = models.JSONField(null=True, blank=True)
    progress_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    progress_summary = models.CharField(max_length=2000, null=True, blank=True)
    result_ref = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    effective_principal = models.JSONField(null=True, blank=True)
    correlation_id = models.CharField(max_length=255)

    class Meta:
        db_table = "curve_operation"
        indexes = [
            models.Index(fields=["workspace_id", "status"], name="curve_op_workspace_state_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status__in=[
                            OperationStatus.SUCCEEDED,
                            OperationStatus.FAILED,
                            OperationStatus.CANCELLED,
                        ]
                    )
                    | models.Q(completed_at__isnull=False)
                ),
                name="curve_op_terminal_completed_ck",
            ),
            models.CheckConstraint(
                condition=(~models.Q(status=OperationStatus.FAILED) | models.Q(error__isnull=False)),
                name="curve_op_failed_error_ck",
            ),
            models.CheckConstraint(
                condition=(models.Q(progress_percent__isnull=True) | models.Q(progress_percent__lte=100)),
                name="curve_op_progress_range_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gte=1),
                name="curve_op_version_positive_ck",
            ),
        ]


class ProductState(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    ARCHIVED = "ARCHIVED", "Archived"


class Product(models.Model):
    """Minimum workspace-scoped Product aggregate for Curve M1."""

    objects = models.Manager.from_queryset(ProductQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    key = models.CharField(max_length=50, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    timezone = models.CharField(max_length=255)
    state = models.CharField(max_length=16, choices=ProductState.choices, default=ProductState.ACTIVE)
    owner_user_id = models.UUIDField()
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)
    created_by = models.JSONField(editable=False)
    updated_by = models.JSONField(editable=False)
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    archived_by = models.JSONField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "curve_product"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "key"],
                name="curve_product_workspace_key_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(key__regex=r"^[a-z0-9][a-z0-9-]{0,49}$"),
                name="curve_product_key_format_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="curve_product_name_nonempty_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=ProductState.values),
                name="curve_product_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="curve_product_version_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state=ProductState.ACTIVE,
                        archived_at__isnull=True,
                        archived_by__isnull=True,
                    )
                    | models.Q(
                        state=ProductState.ARCHIVED,
                        archived_at__isnull=False,
                        archived_by__isnull=False,
                    )
                ),
                name="curve_product_archival_fields_ck",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values("workspace_id", "key").first()
            if original is None:
                raise ImmutableRecordError("Product update target no longer exists")
            if original["workspace_id"] != self.workspace_id or original["key"] != self.key:
                raise ImmutableRecordError("Product workspace and key are immutable")
        return super().save(*args, **kwargs)


class InitiativeMode(models.TextChoices):
    ROADMAP = "ROADMAP", "Roadmap"
    STANDALONE = "STANDALONE", "Standalone"


class InitiativeRiskTier(models.TextChoices):
    LOW = "LOW", "Low"
    STANDARD = "STANDARD", "Standard"
    HIGH = "HIGH", "High"


class InitiativeBusinessIntent(models.TextChoices):
    STRATEGIC = "STRATEGIC", "Strategic"
    CUSTOMER_COMMITMENT = "CUSTOMER_COMMITMENT", "Customer commitment"
    BUSINESS_IMPROVEMENT = "BUSINESS_IMPROVEMENT", "Business improvement"
    MANDATORY = "MANDATORY", "Mandatory"


class InitiativeState(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ALIGNING = "ALIGNING", "Aligning"
    PRD_REVIEW = "PRD_REVIEW", "PRD review"
    PLANNING = "PLANNING", "Planning"
    PLAN_REVIEW = "PLAN_REVIEW", "Plan review"
    EXECUTING = "EXECUTING", "Executing"
    CODE_READINESS_REVIEW = "CODE_READINESS_REVIEW", "Code readiness review"
    READY_FOR_REPOSITORY_REVIEW = "READY_FOR_REPOSITORY_REVIEW", "Ready for repository review"
    PAUSED = "PAUSED", "Paused"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


class GateType(models.TextChoices):
    PRD_APPROVAL = "PRD_APPROVAL", "PRD approval"
    PLAN_APPROVAL = "PLAN_APPROVAL", "Plan approval"
    CODE_READINESS = "CODE_READINESS", "Code readiness"


class Initiative(models.Model):
    """Local manual-first Initiative aggregate for Curve M1-01A."""

    objects = models.Manager.from_queryset(InitiativeQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.1", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    product_id = models.UUIDField(db_index=True, editable=False)
    mode = models.CharField(max_length=16, choices=InitiativeMode.choices)
    roadmap_item_id = models.UUIDField(null=True, blank=True, editable=False)
    keyword = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    description = models.JSONField()
    risk_tier = models.CharField(max_length=16, choices=InitiativeRiskTier.choices)
    business_intent = models.CharField(
        max_length=32,
        choices=InitiativeBusinessIntent.choices,
        null=True,
        blank=True,
    )
    state = models.CharField(max_length=40, choices=InitiativeState.choices, default=InitiativeState.DRAFT)
    paused_from_state = models.CharField(max_length=40, choices=InitiativeState.choices, null=True, blank=True)
    workflow_version_id = models.UUIDField(null=True, blank=True, editable=False)
    creator_user_id = models.UUIDField(editable=False)
    first_external_resource_at = models.DateTimeField(null=True, blank=True, editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)
    created_by = models.JSONField(editable=False)
    updated_by = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_initiative"
        indexes = [
            models.Index(fields=["workspace_id", "state", "created_at"], name="curve_init_ws_state_idx"),
            models.Index(fields=["workspace_id", "product_id", "state"], name="curve_init_ws_product_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_init_ws_id_uq"),
            models.UniqueConstraint(
                models.F("workspace_id"),
                Lower("keyword"),
                name="curve_init_workspace_keyword_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(keyword__regex=r"^[A-Za-z0-9][A-Za-z0-9-]{0,49}$"),
                name="curve_init_keyword_format_ck",
            ),
            models.CheckConstraint(condition=~models.Q(title=""), name="curve_init_title_nonempty_ck"),
            models.CheckConstraint(
                condition=models.Q(mode__in=InitiativeMode.values),
                name="curve_init_mode_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(mode=InitiativeMode.STANDALONE, roadmap_item_id__isnull=True)
                    | models.Q(mode=InitiativeMode.ROADMAP, roadmap_item_id__isnull=False)
                ),
                name="curve_init_roadmap_mode_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(risk_tier__in=InitiativeRiskTier.values),
                name="curve_init_risk_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(business_intent__isnull=True)
                    | models.Q(business_intent__in=InitiativeBusinessIntent.values)
                ),
                name="curve_init_business_intent_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=InitiativeState.values),
                name="curve_init_state_ck",
            ),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="curve_init_version_ck"),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state=InitiativeState.PAUSED,
                        paused_from_state__in=[InitiativeState.DRAFT, InitiativeState.ALIGNING],
                    )
                    | (~models.Q(state=InitiativeState.PAUSED) & models.Q(paused_from_state__isnull=True))
                ),
                name="curve_init_paused_from_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state=InitiativeState.DRAFT, workflow_version_id__isnull=True)
                    | models.Q(state=InitiativeState.ALIGNING, workflow_version_id__isnull=False)
                    | models.Q(
                        state=InitiativeState.PAUSED,
                        paused_from_state=InitiativeState.DRAFT,
                        workflow_version_id__isnull=True,
                    )
                    | models.Q(
                        state=InitiativeState.PAUSED,
                        paused_from_state=InitiativeState.ALIGNING,
                        workflow_version_id__isnull=False,
                    )
                    | models.Q(state=InitiativeState.CANCELLED)
                ),
                name="curve_init_workflow_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(first_external_resource_at__isnull=True),
                name="curve_init_external_resource_ck",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(
                    "workspace_id",
                    "product_id",
                    "mode",
                    "creator_user_id",
                    "keyword",
                    "state",
                    "first_external_resource_at",
                )
                .first()
            )
            if original is None:
                raise ImmutableRecordError("Initiative update target no longer exists")
            immutable = ("workspace_id", "product_id", "mode", "creator_user_id")
            if any(original[field] != getattr(self, field) for field in immutable):
                raise ImmutableRecordError("Initiative workspace, Product, mode, and creator are immutable")
            if original["keyword"] != self.keyword and (
                original["state"] != InitiativeState.DRAFT or original["first_external_resource_at"] is not None
            ):
                raise ImmutableRecordError("Initiative keyword is immutable after draft/external-resource boundary")
        return super().save(*args, **kwargs)


class GateAssignment(models.Model):
    """Initial human gate assignment; replacement is deferred beyond M1-01A."""

    objects = models.Manager.from_queryset(GateAssignmentQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    initiative = models.ForeignKey(Initiative, on_delete=models.PROTECT, related_name="gate_assignments")
    gate_type = models.CharField(max_length=32, choices=GateType.choices)
    approver_user_id = models.UUIDField()
    valid_from = models.DateTimeField(default=timezone.now, editable=False)
    valid_until = models.DateTimeField(null=True, blank=True, editable=False)
    delegation_reason = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "curve_gate_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "gate_type"],
                name="curve_gate_ws_init_type_uq",
            ),
            models.CheckConstraint(condition=models.Q(gate_type__in=GateType.values), name="curve_gate_type_ck"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("GateAssignment records are immutable in M1-01A")
        if self.initiative_id and self.workspace_id != self.initiative.workspace_id:
            raise ValidationError("GateAssignment and Initiative workspace must match")
        return super().save(*args, **kwargs)


class ProviderConnection(WorkspaceScopedModel):
    """Mutable workspace-scoped configuration for one provider adapter."""

    objects = models.Manager.from_queryset(ProviderConnectionQuerySet)()

    schema_version = models.CharField(max_length=20, default="2.0", editable=False)
    provider_type = models.CharField(max_length=32, choices=ProviderType.choices)
    adapter_key = models.CharField(max_length=100)
    adapter_version = models.CharField(max_length=100)
    environment = models.CharField(max_length=20, choices=ProviderEnvironment.choices)
    display_name = models.CharField(max_length=255)
    external_tenant_ref = models.CharField(max_length=1000, null=True, blank=True)
    configuration_ref = models.JSONField(null=True, blank=True)
    configuration_digest = models.CharField(max_length=DIGEST_MAX_LENGTH)
    secret_reference = models.CharField(max_length=1000, null=True, blank=True)
    current_capability = models.ForeignKey(
        "ProviderCapability",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_connections",
    )
    allowed_classifications = models.JSONField(default=list)
    status = models.CharField(
        max_length=32,
        choices=ProviderConnectionStatus.choices,
        default=ProviderConnectionStatus.PENDING_VALIDATION,
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    validation_result_ref = models.JSONField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    next_reconcile_at = models.DateTimeField(null=True, blank=True)
    last_error = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "curve_provider_connection"
        indexes = [
            models.Index(
                fields=["workspace_id", "status", "next_reconcile_at"],
                name="curve_pconn_ws_state_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_pconn_ws_id_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "environment", "adapter_key"],
                name="curve_pconn_ws_env_adapter_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gte=1),
                name="curve_pconn_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version="2.0"),
                name="curve_pconn_schema_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(configuration_digest__regex=r"^sha256:[0-9a-f]{64}$"),
                name="curve_pconn_digest_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ProviderConnectionStatus.values),
                name="curve_pconn_status_ck",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(models.F("allowed_classifications"), function="jsonb_typeof"),
                    models.Value("array"),
                ),
                name="curve_pconn_class_type_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(provider_type=ProviderType.FAKE_LOCAL)
                    & models.Q(adapter_key="curve.fake-local")
                    & models.Q(environment=ProviderEnvironment.LOCAL)
                    & models.Q(external_tenant_ref__isnull=True)
                    & models.Q(configuration_ref__isnull=True)
                    & models.Q(secret_reference__isnull=True)
                    & models.Q(allowed_classifications=[DataClassification.INTERNAL])
                ),
                name="curve_pconn_fake_local_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status__in=[
                            ProviderConnectionStatus.ACTIVE,
                            ProviderConnectionStatus.DEGRADED,
                        ]
                    )
                    | models.Q(
                        current_capability__isnull=False,
                        validated_at__isnull=False,
                        validation_result_ref__isnull=False,
                        last_reconciled_at__isnull=False,
                    )
                ),
                name="curve_pconn_live_refs_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=ProviderConnectionStatus.ACTIVE) | models.Q(next_reconcile_at__isnull=False)
                ),
                name="curve_pconn_active_next_ck",
            ),
            models.CheckConstraint(
                condition=(~models.Q(status=ProviderConnectionStatus.DEGRADED) | models.Q(last_error__isnull=False)),
                name="curve_pconn_degraded_err_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status__in=[
                            ProviderConnectionStatus.DISABLED,
                            ProviderConnectionStatus.REVOKED,
                        ]
                    )
                    | models.Q(next_reconcile_at__isnull=True)
                ),
                name="curve_pconn_stopped_next_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(validation_result_ref__isnull=True)
                    | Exact(
                        models.Func(models.F("validation_result_ref"), function="jsonb_typeof"),
                        models.Value("object"),
                    )
                ),
                name="curve_pconn_result_type_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(last_error__isnull=True)
                    | Exact(
                        models.Func(models.F("last_error"), function="jsonb_typeof"),
                        models.Value("object"),
                    )
                ),
                name="curve_pconn_error_type_ck",
            ),
        ]

    def _validate_current_capability_scope(self):
        if self.current_capability_id is None:
            return
        capability = self.current_capability
        if capability.workspace_id != self.workspace_id or capability.connection_id != self.id:
            raise ValidationError("current capability must belong to this workspace-scoped connection")
        if (
            capability.provider_type != self.provider_type
            or capability.adapter_key != self.adapter_key
            or capability.adapter_version != self.adapter_version
        ):
            raise ValidationError("current capability must match the connection adapter coordinates")

    def save(self, *args, **kwargs):
        self._validate_current_capability_scope()
        return super().save(*args, **kwargs)


class DocumentSynchronizationStatus(models.TextChoices):
    CURRENT = "CURRENT", "Current"
    CHANGED_SINCE_SUBMISSION = "CHANGED_SINCE_SUBMISSION", "Changed since submission"
    CHANGED_SINCE_APPROVAL = "CHANGED_SINCE_APPROVAL", "Changed since approval"
    ACCESS_REVOKED = "ACCESS_REVOKED", "Access revoked"
    MOVED_OUTSIDE_POLICY = "MOVED_OUTSIDE_POLICY", "Moved outside policy"
    DELETED = "DELETED", "Deleted"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE", "Provider unavailable"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED", "Reconciliation required"


class DocumentAccessStatus(models.TextChoices):
    ALLOWED = "ALLOWED", "Allowed"
    DENIED = "DENIED", "Denied"
    UNKNOWN = "UNKNOWN", "Unknown"


class ExternalDocumentBindingQuerySet(WorkspaceScopedQuerySetMixin, models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        raise ImmutableRecordError("Document binding creation requires scoped instance validation")

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise ImmutableRecordError("Document binding changes require versioned instance updates")

    def update(self, **kwargs):
        raise ImmutableRecordError("Document binding changes require versioned instance updates")

    def delete(self):
        raise ImmutableRecordError("Document binding deletion requires a governed successor policy")


class ExternalDocumentBinding(models.Model):
    """External PRD identity and observation metadata; no content or live transport.

    The consuming command must authenticate, authorize, and audit before using
    this persistence primitive. Stored access status is a projection, never a
    permission grant. Composite tenant FKs and identity/version triggers are
    installed by the migration, including for writes outside the ORM.
    """

    objects = models.Manager.from_queryset(ExternalDocumentBindingQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    initiative = models.ForeignKey(Initiative, on_delete=models.PROTECT, related_name="document_bindings")
    artifact_kind = models.CharField(max_length=16, default="PRD", editable=False)
    provider_connection = models.ForeignKey(
        ProviderConnection, on_delete=models.PROTECT, related_name="document_bindings"
    )
    provider_file_id = models.CharField(max_length=512, editable=False)
    provider_container_id = models.CharField(max_length=512)
    canonical_url = models.URLField(max_length=2048)
    current_provider_version = models.CharField(max_length=512)
    current_revision_id = models.CharField(max_length=512, null=True, blank=True)
    current_modified_at = models.DateTimeField()
    synchronization_status = models.CharField(
        max_length=32,
        choices=DocumentSynchronizationStatus.choices,
        default=DocumentSynchronizationStatus.RECONCILIATION_REQUIRED,
    )
    access_status = models.CharField(
        max_length=16, choices=DocumentAccessStatus.choices, default=DocumentAccessStatus.UNKNOWN
    )
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.JSONField(editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_external_document_binding"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_doc_ws_id_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "initiative", "artifact_kind"], name="curve_doc_ws_init_kind_uq"
            ),
            models.CheckConstraint(condition=models.Q(schema_version="1.0"), name="curve_doc_schema_ck"),
            models.CheckConstraint(condition=models.Q(artifact_kind="PRD"), name="curve_doc_kind_ck"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="curve_doc_version_ck"),
            models.CheckConstraint(
                condition=models.Q(synchronization_status__in=DocumentSynchronizationStatus.values),
                name="curve_doc_sync_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(access_status__in=DocumentAccessStatus.values), name="curve_doc_access_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(canonical_url__regex=r"^https://[^[:space:]]+$"), name="curve_doc_url_ck"
            ),
            *[
                models.CheckConstraint(condition=models.Q(**{f"{field}__regex": r"^[A-Za-z0-9._~-]+$"}), name=name)
                for field, name in (
                    ("provider_file_id", "curve_doc_file_ck"),
                    ("provider_container_id", "curve_doc_container_ck"),
                    ("current_provider_version", "curve_doc_provider_version_ck"),
                    ("current_revision_id", "curve_doc_revision_ck"),
                )
            ],
        ]

    def as_record(self):
        from .prd_metadata_validation import instant

        return {
            "schema_version": self.schema_version,
            "id": str(self.id),
            "workspace_id": str(self.workspace_id),
            "initiative_id": str(self.initiative_id),
            "artifact_kind": self.artifact_kind,
            "provider_connection_id": str(self.provider_connection_id),
            "provider_file_id": self.provider_file_id,
            "provider_container_id": self.provider_container_id,
            "canonical_url": self.canonical_url,
            "current_provider_version": self.current_provider_version,
            "current_revision_id": self.current_revision_id,
            "current_modified_at": instant(self.current_modified_at),
            "synchronization_status": self.synchronization_status,
            "access_status": self.access_status,
            "last_reconciled_at": instant(self.last_reconciled_at) if self.last_reconciled_at else None,
            "version": self.version,
            "created_by": dict(self.created_by),
            "created_at": instant(self.created_at),
        }

    def save(self, *args, **kwargs):
        # Scope before loading referenced metadata. The DB repeats these checks
        # with composite FKs, so concurrent parent changes cannot cross tenants.
        if not Initiative.objects.filter(id=self.initiative_id, workspace_id=self.workspace_id).exists():
            raise ValidationError("Document binding Initiative must belong to its workspace")
        if not ProviderConnection.objects.filter(
            id=self.provider_connection_id, workspace_id=self.workspace_id
        ).exists():
            raise ValidationError("Document binding connection must belong to its workspace")
        # Force insertion for new IDs: Django's update-then-insert fallback could
        # otherwise rewrite an existing binding supplied with a colliding UUID.
        if self._state.adding:
            kwargs["force_insert"] = True
        else:
            kwargs["force_update"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Document binding deletion requires a governed successor policy")


class ProviderCapability(ImmutableRecordModel):
    """Append-only workspace-scoped provider capability observation."""

    objects = models.Manager.from_queryset(ProviderCapabilityQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="2.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    connection = models.ForeignKey(
        ProviderConnection,
        on_delete=models.PROTECT,
        related_name="capability_history",
    )
    connection_version = models.PositiveBigIntegerField(editable=False)
    capability_version = models.PositiveBigIntegerField(editable=False)
    provider_type = models.CharField(max_length=32, choices=ProviderType.choices, editable=False)
    adapter_key = models.CharField(max_length=100, editable=False)
    adapter_version = models.CharField(max_length=100, editable=False)
    protocol_versions = models.JSONField(editable=False)
    capabilities = models.JSONField(editable=False)
    allowed_classifications = models.JSONField(editable=False)
    observed_at = models.DateTimeField(editable=False)
    validated_at = models.DateTimeField(editable=False)
    expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        db_table = "curve_provider_capability"
        indexes = [
            models.Index(
                fields=["workspace_id", "-validated_at"],
                name="curve_pcap_ws_valid_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "connection", "capability_version"],
                name="curve_pcap_ws_conn_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(connection_version__gte=1),
                name="curve_pcap_conn_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(capability_version__gte=1),
                name="curve_pcap_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version="2.0"),
                name="curve_pcap_schema_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(provider_type=ProviderType.FAKE_LOCAL)
                    & models.Q(adapter_key="curve.fake-local")
                    & models.Q(protocol_versions=["curve.fake-local/v1"])
                    & models.Q(allowed_classifications=[DataClassification.INTERNAL])
                ),
                name="curve_pcap_fake_local_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Exact(
                        models.Func(models.F("protocol_versions"), function="jsonb_typeof"),
                        models.Value("array"),
                    )
                    & GreaterThan(
                        models.Func(
                            models.F("protocol_versions"),
                            function="jsonb_array_length",
                            output_field=models.IntegerField(),
                        ),
                        models.Value(0),
                    )
                ),
                name="curve_pcap_protocols_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Exact(
                        models.Func(models.F("capabilities"), function="jsonb_typeof"),
                        models.Value("array"),
                    )
                    & GreaterThan(
                        models.Func(
                            models.F("capabilities"),
                            function="jsonb_array_length",
                            output_field=models.IntegerField(),
                        ),
                        models.Value(0),
                    )
                ),
                name="curve_pcap_capabilities_ck",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(models.F("allowed_classifications"), function="jsonb_typeof"),
                    models.Value("array"),
                ),
                name="curve_pcap_class_type_ck",
            ),
        ]

    def _validate_connection_scope(self):
        if self.connection_id is None:
            raise ValidationError("connection is required")
        connection = self.connection
        if connection.workspace_id != self.workspace_id:
            raise ValidationError("capability must belong to the connection workspace")
        if (
            connection.provider_type != self.provider_type
            or connection.adapter_key != self.adapter_key
            or connection.adapter_version != self.adapter_version
        ):
            raise ValidationError("capability must match the connection adapter coordinates")
        if not set(self.allowed_classifications).issubset(set(connection.allowed_classifications)):
            raise ValidationError("capability classification exceeds the connection ceiling")

    def _validate_fake_capabilities(self):
        if not isinstance(self.capabilities, list) or not self.capabilities:
            raise ValidationError("capabilities must be a non-empty array")
        normalized = set()
        for capability in self.capabilities:
            if not isinstance(capability, dict):
                raise ValidationError("each capability must be an object")
            if not {"name", "risk", "enabled"}.issubset(capability):
                raise ValidationError("capability fields name, risk, and enabled are required")
            if set(capability) - {"name", "risk", "enabled", "schema_uri"}:
                raise ValidationError("capability contains an unknown field")
            if capability["risk"] != ProviderCapabilityRisk.READ:
                raise ValidationError("the local fake permits READ capabilities only")
            if not isinstance(capability["enabled"], bool):
                raise ValidationError("capability enabled must be boolean")
            encoded = json.dumps(capability, sort_keys=True, separators=(",", ":"))
            if encoded in normalized:
                raise ValidationError("capabilities must be unique")
            normalized.add(encoded)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self._validate_connection_scope()
            self._validate_fake_capabilities()
        return super().save(*args, **kwargs)


class DomainEvent(ImmutableRecordModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    event_type = models.CharField(max_length=255)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    aggregate_type = models.CharField(max_length=100)
    aggregate_id = models.UUIDField()
    aggregate_version = models.PositiveBigIntegerField()
    sequence = models.PositiveBigIntegerField()
    initiative_id = models.UUIDField(null=True, blank=True)
    workflow_version_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)
    actor = models.JSONField(editable=False)
    effective_principal = models.JSONField(null=True, blank=True, editable=False)
    correlation_id = models.CharField(max_length=255, editable=False)
    causation_id = models.CharField(max_length=255, null=True, blank=True, editable=False)
    idempotency_key_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, null=True, blank=True, editable=False)
    classification = models.CharField(
        max_length=20, choices=DataClassification.choices, default=DataClassification.INTERNAL
    )
    payload_schema = models.CharField(max_length=1000)
    payload = models.JSONField()

    class Meta:
        db_table = "curve_domain_event"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "aggregate_type", "aggregate_id", "sequence"],
                name="curve_event_workspace_aggregate_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="curve_event_sequence_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(aggregate_version__gte=1),
                name="curve_event_version_positive_ck",
            ),
        ]


class OutboxState(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CLAIMED = "CLAIMED", "Claimed"
    DELIVERED = "DELIVERED", "Delivered"
    RETRY_SCHEDULED = "RETRY_SCHEDULED", "Retry scheduled"
    DEAD_LETTER = "DEAD_LETTER", "Dead letter"


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    event_id = models.UUIDField(editable=False)
    destination = models.CharField(max_length=128)
    state = models.CharField(max_length=32, choices=OutboxState.choices, default=OutboxState.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=255, null=True, blank=True)
    claimed_until = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        db_table = "curve_outbox_event"
        indexes = [
            models.Index(
                fields=["workspace_id", "state", "next_attempt_at", "created_at"],
                name="curve_outbox_due_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "event_id", "destination"],
                name="curve_outbox_workspace_event_dest_uq",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state=OutboxState.CLAIMED)
                    | (
                        models.Q(claimed_by__isnull=False)
                        & ~models.Q(claimed_by="")
                        & models.Q(claimed_until__isnull=False)
                    )
                ),
                name="curve_outbox_claim_fields_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state=OutboxState.RETRY_SCHEDULED)
                    | (models.Q(next_attempt_at__isnull=False) & models.Q(last_error__isnull=False))
                ),
                name="curve_outbox_retry_fields_ck",
            ),
            models.CheckConstraint(
                condition=(~models.Q(state=OutboxState.DELIVERED) | models.Q(delivered_at__isnull=False)),
                name="curve_outbox_delivered_at_ck",
            ),
            models.CheckConstraint(
                condition=(~models.Q(state=OutboxState.DEAD_LETTER) | models.Q(last_error__isnull=False)),
                name="curve_outbox_dead_error_ck",
            ),
        ]


class InboxState(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    PROCESSING = "PROCESSING", "Processing"
    PROCESSED = "PROCESSED", "Processed"
    FAILED_TERMINAL = "FAILED_TERMINAL", "Failed terminal"


class InboxMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    consumer_id = models.CharField(max_length=255)
    event_id = models.UUIDField()
    state = models.CharField(max_length=32, choices=InboxState.choices, default=InboxState.RECEIVED)
    received_at = models.DateTimeField(auto_now_add=True, editable=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    result_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, null=True, blank=True)
    last_error = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "curve_inbox_message"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "consumer_id", "event_id"],
                name="curve_inbox_workspace_consumer_event_uq",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state=InboxState.PROCESSED)
                    | (models.Q(processed_at__isnull=False) & models.Q(result_digest__isnull=False))
                ),
                name="curve_inbox_processed_fields_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state=InboxState.FAILED_TERMINAL)
                    | (models.Q(processed_at__isnull=False) & models.Q(last_error__isnull=False))
                ),
                name="curve_inbox_failed_fields_ck",
            ),
        ]


class IdempotencyState(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    FAILED_TERMINAL = "FAILED_TERMINAL", "Failed terminal"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED", "Reconciliation required"


class IdempotencyRecordQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError("IdempotencyRecord changes require a locked instance and terminal-state validation")

    def delete(self):
        raise ImmutableRecordError("IdempotencyRecord deletion requires a governed retention operation")


class IdempotencyRecord(models.Model):
    TERMINAL_STATES = frozenset({IdempotencyState.COMPLETED, IdempotencyState.FAILED_TERMINAL})

    objects = models.Manager.from_queryset(IdempotencyRecordQuerySet)()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    principal_scope = models.CharField(max_length=500)
    command_scope = models.CharField(max_length=500)
    key_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, editable=False)
    request_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, editable=False)
    state = models.CharField(max_length=32, choices=IdempotencyState.choices, default=IdempotencyState.IN_PROGRESS)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, null=True, blank=True)
    response_resource_ref = models.JSONField(null=True, blank=True)
    external_effect_refs = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "curve_idempotency_record"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "principal_scope", "command_scope", "key_digest"],
                name="curve_idem_workspace_principal_cmd_key_uq",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state__in=[IdempotencyState.COMPLETED, IdempotencyState.FAILED_TERMINAL])
                    | (
                        models.Q(response_status__isnull=False)
                        & models.Q(response_digest__isnull=False)
                        & models.Q(response_resource_ref__isnull=False)
                        & models.Q(completed_at__isnull=False)
                    )
                ),
                name="curve_idem_terminal_fields_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(response_status__isnull=True)
                    | (models.Q(response_status__gte=100) & models.Q(response_status__lte=599))
                ),
                name="curve_idem_response_status_ck",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            existing_state = type(self).objects.filter(pk=self.pk).values_list("state", flat=True).first()
            if existing_state in self.TERMINAL_STATES:
                raise ImmutableRecordError("terminal IdempotencyRecord records are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("IdempotencyRecord deletion requires a governed retention operation")


class AuditOutcome(models.TextChoices):
    ALLOWED = "ALLOWED", "Allowed"
    DENIED = "DENIED", "Denied"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    NO_EFFECT = "NO_EFFECT", "No effect"


class PolicyEffect(models.TextChoices):
    ALLOW = "ALLOW", "Allow"
    DENY = "DENY", "Deny"
    REQUIRE_HUMAN_CONFIRMATION = (
        "REQUIRE_HUMAN_CONFIRMATION",
        "Require human confirmation",
    )


class PolicyDecision(ImmutableRecordModel):
    """Append-only, workspace-scoped authorization evidence."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    sequence = models.PositiveBigIntegerField(editable=False)
    action = models.CharField(max_length=128, editable=False)
    resource_type = models.CharField(max_length=100, editable=False)
    resource_id = models.UUIDField(editable=False)
    resource_version = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    subject = models.JSONField(editable=False)
    effective_principal = models.JSONField(editable=False)
    effect = models.CharField(max_length=32, choices=PolicyEffect.choices, editable=False)
    reason_codes = models.JSONField(editable=False)
    policy_key = models.CharField(max_length=100, default="CURVE_CORE_POLICY", editable=False)
    policy_version = models.PositiveIntegerField(default=1, editable=False)
    policy_manifest_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, editable=False)
    input_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, editable=False)
    normalized_classification = models.CharField(
        max_length=20,
        choices=DataClassification.choices,
        editable=False,
    )
    permitted_projection = models.JSONField(default=list, editable=False)
    correlation_id = models.CharField(max_length=255, editable=False)
    evaluated_at = models.DateTimeField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    recorded_by = models.JSONField(editable=False)

    class Meta:
        db_table = "curve_policy_decision"
        indexes = [
            models.Index(
                fields=["workspace_id", "-evaluated_at"],
                name="curve_policy_ws_eval_idx",
            ),
            models.Index(
                fields=["workspace_id", "resource_type", "resource_id", "-evaluated_at"],
                name="curve_policy_res_eval_idx",
            ),
            models.Index(
                fields=["workspace_id", "effect", "-evaluated_at"],
                name="curve_policy_effect_eval_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "resource_type", "resource_id", "sequence"],
                name="curve_policy_ws_res_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="curve_policy_seq_pos_ck",
            ),
            models.CheckConstraint(
                condition=(models.Q(resource_version__isnull=True) | models.Q(resource_version__gte=1)),
                name="curve_policy_res_ver_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(effect=PolicyEffect.ALLOW) & ~models.Q(permitted_projection=[])
                    | ~models.Q(effect=PolicyEffect.ALLOW) & models.Q(permitted_projection=[])
                ),
                name="curve_policy_proj_effect_ck",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(models.F("permitted_projection"), function="jsonb_typeof"),
                    models.Value("array"),
                ),
                name="curve_policy_proj_type_ck",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(models.F("reason_codes"), function="jsonb_typeof"),
                    models.Value("array"),
                )
                & GreaterThan(
                    models.Func(
                        models.F("reason_codes"),
                        function="jsonb_array_length",
                        output_field=models.IntegerField(),
                    ),
                    models.Value(0),
                ),
                name="curve_policy_reasons_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(policy_manifest_digest__regex=r"^sha256:[0-9a-f]{64}$"),
                name="curve_policy_manifest_sha_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(input_digest__regex=r"^sha256:[0-9a-f]{64}$"),
                name="curve_policy_input_sha_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version="1.0"),
                name="curve_policy_schema_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(policy_key="CURVE_CORE_POLICY", policy_version__in=[1, 2])
                    | models.Q(policy_key="CURVE_PRODUCT_POLICY", policy_version=1)
                    | models.Q(policy_key="CURVE_INITIATIVE_POLICY", policy_version=1)
                ),
                name="curve_policy_identity_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_by__actor_type__in=["SERVICE", "SYSTEM"]),
                name="curve_policy_recorder_type_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("evaluated_at")),
                name="curve_policy_recorded_time_ck",
            ),
        ]


class AuditEvent(ImmutableRecordModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.CharField(max_length=20, default="1.0", editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    sequence = models.PositiveBigIntegerField()
    action = models.CharField(max_length=128)
    target_type = models.CharField(max_length=100, editable=False)
    target_id = models.UUIDField(editable=False)
    target_ref = models.JSONField(editable=False)
    outcome = models.CharField(max_length=20, choices=AuditOutcome.choices)
    actor = models.JSONField(editable=False)
    effective_principal = models.JSONField(null=True, blank=True, editable=False)
    policy_decision_ref = models.JSONField(null=True, blank=True, editable=False)
    before_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, null=True, blank=True, editable=False)
    after_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, null=True, blank=True, editable=False)
    details_ref = models.JSONField(null=True, blank=True, editable=False)
    classification = models.CharField(
        max_length=20, choices=DataClassification.choices, default=DataClassification.INTERNAL
    )
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)
    recorded_at = models.DateTimeField(auto_now_add=True, editable=False)
    correlation_id = models.CharField(max_length=255, editable=False)
    causation_id = models.CharField(max_length=255, null=True, blank=True, editable=False)
    idempotency_key_digest = models.CharField(max_length=DIGEST_MAX_LENGTH, null=True, blank=True, editable=False)

    class Meta:
        db_table = "curve_audit_event"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace_id", "target_type", "target_id", "sequence"],
                name="curve_audit_workspace_target_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="curve_audit_sequence_positive_ck",
            ),
        ]


# Register the additive PRD model module after the shared bases are defined.
from .prd_models import (  # noqa: E402,F401
    PrdArtifact,
    PrdArtifactVersion,
    PrdEvidenceItemVersion,
    PrdEvidenceSnapshot,
)
from .prd_checkpoint_models import DocumentCheckpoint  # noqa: E402,F401
