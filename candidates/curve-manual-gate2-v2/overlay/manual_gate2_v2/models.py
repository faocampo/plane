"""Retained control ledger with one exclusive head per stable native task identity."""

import uuid
from django.db import models
from django.utils import timezone

MAX_INTEGER = 9007199254740991


class Gate2WriteDenied(PermissionError):
    pass


class GuardedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise Gate2WriteDenied("Use the exact manual Gate 2 command")

    def bulk_create(self, *args, **kwargs):
        raise Gate2WriteDenied("Use the exact manual Gate 2 command")

    def bulk_update(self, *args, **kwargs):
        raise Gate2WriteDenied("Use the exact manual Gate 2 command")

    def delete(self):
        raise Gate2WriteDenied("Manual control history is retained")


class GuardedRecord(models.Model):
    objects = models.Manager.from_queryset(GuardedQuerySet)()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)

    class Meta:
        abstract = True
        app_label = "curve"

    def save(self, *args, **kwargs):
        from .repository import assert_exact_write

        assert_exact_write(self)
        if not self._state.adding and type(self) not in {
            ManualGate2ControlV2,
            ManualTaskClaimV2,
        }:
            raise Gate2WriteDenied("Manual control evidence is immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise Gate2WriteDenied("Manual control history is retained")


class ManualGate2ControlV2(GuardedRecord):
    product_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(editable=False)
    current_record_id = models.UUIDField(editable=False)
    subject_id = models.UUIDField(editable=False)
    state = models.CharField(max_length=24, editable=False)
    approved_record_id = models.UUIDField(null=True, editable=False)

    class Meta:
        app_label = "curve"
        db_table = "curve_manual_gate2_control_v2"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_mg2c_ws_id_uq"),
            models.UniqueConstraint(fields=["workspace_id", "initiative_id"], name="curve_mg2c_init_uq"),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=MAX_INTEGER),
                name="curve_mg2c_ver_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=[
                        "PLAN_REVIEW",
                        "CHANGES_REQUESTED",
                        "MANUAL_APPROVED",
                        "RELEASED",
                    ]
                ),
                name="curve_mg2c_state_ck",
            ),
        ]


class ManualGate2RecordV2(GuardedRecord):
    product_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(db_index=True, editable=False)
    control_id = models.UUIDField(editable=False)
    version = models.PositiveBigIntegerField(editable=False)
    initiative_version = models.PositiveBigIntegerField(editable=False)
    predecessor_id = models.UUIDField(null=True, editable=False)
    action = models.CharField(max_length=24, editable=False)
    subject_id = models.UUIDField(editable=False)
    subject_digest = models.CharField(max_length=71, editable=False)
    draft_revision_id = models.UUIDField(editable=False)
    digest = models.CharField(max_length=71, editable=False)
    payload = models.JSONField(editable=False)
    request_payload = models.JSONField(editable=False)
    request_digest = models.CharField(max_length=71, editable=False)
    policy_decision_id = models.UUIDField(editable=False)
    command_receipt_id = models.UUIDField(editable=False)
    created_by = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        app_label = "curve"
        db_table = "curve_manual_gate2_record_v2"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_mg2r_ws_id_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "control_id", "version"],
                name="curve_mg2r_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "command_receipt_id"],
                name="curve_mg2r_event_uq",
            ),
            models.UniqueConstraint(
                fields=["workspace_id", "policy_decision_id"],
                name="curve_mg2r_policy_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1, version__lte=MAX_INTEGER),
                name="curve_mg2r_ver_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(initiative_version__gte=2, initiative_version__lte=MAX_INTEGER),
                name="curve_mg2r_init_ver_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action__in=[
                        "PREPARE",
                        "APPROVE",
                        "REQUEST_CHANGES",
                        "RECONCILE",
                        "RELEASE",
                    ]
                ),
                name="curve_mg2r_action_ck",
            ),
            *[
                models.CheckConstraint(
                    condition=models.Q(**{field + "__regex": r"^sha256:[0-9a-f]{64}$"}),
                    name=name,
                )
                for field, name in [
                    ("digest", "curve_mg2r_digest_ck"),
                    ("subject_digest", "curve_mg2r_subject_ck"),
                    ("request_digest", "curve_mg2r_request_ck"),
                ]
            ],
        ]

    def as_record(self):
        from .contracts import verify_record

        return verify_record(self)


class ManualTaskClaimV2(GuardedRecord):
    installation_id = models.UUIDField(editable=False)
    issue_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(db_index=True, editable=False)
    subject_id = models.UUIDField(editable=False)
    generation = models.PositiveBigIntegerField(editable=False)
    state = models.CharField(max_length=16, editable=False)
    current_record_id = models.UUIDField(editable=False)
    current_history_id = models.UUIDField(editable=False)

    class Meta:
        app_label = "curve"
        db_table = "curve_manual_task_claim_v2"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_mtc2_ws_id_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "installation_id", "issue_id"],
                name="curve_mtc2_task_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gte=1, generation__lte=MAX_INTEGER),
                name="curve_mtc2_gen_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["ACTIVE", "RELEASED"]),
                name="curve_mtc2_state_ck",
            ),
        ]


class ManualTaskClaimHistoryV2(GuardedRecord):
    claim_id = models.UUIDField(editable=False)
    record_id = models.UUIDField(editable=False)
    initiative_id = models.UUIDField(db_index=True, editable=False)
    generation = models.PositiveBigIntegerField(editable=False)
    state = models.CharField(max_length=16, editable=False)
    payload = models.JSONField(editable=False)

    class Meta:
        app_label = "curve"
        db_table = "curve_manual_task_claim_history_v2"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "id"], name="curve_mtch2_ws_id_uq"),
            models.UniqueConstraint(
                fields=["workspace_id", "claim_id", "record_id"],
                name="curve_mtch2_event_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gte=1, generation__lte=MAX_INTEGER),
                name="curve_mtch2_gen_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["ACTIVE", "RELEASED"]),
                name="curve_mtch2_state_ck",
            ),
        ]
