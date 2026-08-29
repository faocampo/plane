# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curve", "0006_product"),
    ]

    operations = [
        migrations.CreateModel(
            name="Initiative",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("schema_version", models.CharField(default="1.0", editable=False, max_length=20)),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("product_id", models.UUIDField(db_index=True, editable=False)),
                (
                    "mode",
                    models.CharField(choices=[("ROADMAP", "Roadmap"), ("STANDALONE", "Standalone")], max_length=16),
                ),
                ("roadmap_item_id", models.UUIDField(blank=True, editable=False, null=True)),
                ("keyword", models.CharField(max_length=50)),
                ("title", models.CharField(max_length=255)),
                ("description", models.JSONField()),
                (
                    "risk_tier",
                    models.CharField(
                        choices=[("LOW", "Low"), ("STANDARD", "Standard"), ("HIGH", "High")],
                        max_length=16,
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("ALIGNING", "Aligning"),
                            ("PRD_REVIEW", "PRD review"),
                            ("PLANNING", "Planning"),
                            ("PLAN_REVIEW", "Plan review"),
                            ("EXECUTING", "Executing"),
                            ("CODE_READINESS_REVIEW", "Code readiness review"),
                            ("READY_FOR_REPOSITORY_REVIEW", "Ready for repository review"),
                            ("PAUSED", "Paused"),
                            ("FAILED", "Failed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        default="DRAFT",
                        max_length=40,
                    ),
                ),
                (
                    "paused_from_state",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("DRAFT", "Draft"),
                            ("ALIGNING", "Aligning"),
                            ("PRD_REVIEW", "PRD review"),
                            ("PLANNING", "Planning"),
                            ("PLAN_REVIEW", "Plan review"),
                            ("EXECUTING", "Executing"),
                            ("CODE_READINESS_REVIEW", "Code readiness review"),
                            ("READY_FOR_REPOSITORY_REVIEW", "Ready for repository review"),
                            ("PAUSED", "Paused"),
                            ("FAILED", "Failed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        max_length=40,
                        null=True,
                    ),
                ),
                ("workflow_version_id", models.UUIDField(blank=True, editable=False, null=True)),
                ("creator_user_id", models.UUIDField(editable=False)),
                ("first_external_resource_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True, editable=False)),
                ("created_by", models.JSONField(editable=False)),
                ("updated_by", models.JSONField(editable=False)),
            ],
            options={
                "db_table": "curve_initiative",
                "indexes": [
                    models.Index(fields=["workspace_id", "state", "created_at"], name="curve_init_ws_state_idx"),
                    models.Index(fields=["workspace_id", "product_id", "state"], name="curve_init_ws_product_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        models.F("workspace_id"),
                        django.db.models.functions.text.Lower("keyword"),
                        name="curve_init_workspace_keyword_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("keyword__regex", "^[A-Za-z0-9][A-Za-z0-9-]{0,49}$")),
                        name="curve_init_keyword_format_ck",
                    ),
                    models.CheckConstraint(condition=~models.Q(("title", "")), name="curve_init_title_nonempty_ck"),
                    models.CheckConstraint(
                        condition=models.Q(("mode__in", ["ROADMAP", "STANDALONE"])),
                        name="curve_init_mode_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("mode", "STANDALONE"), ("roadmap_item_id__isnull", True))
                            | models.Q(("mode", "ROADMAP"), ("roadmap_item_id__isnull", False))
                        ),
                        name="curve_init_roadmap_mode_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("risk_tier__in", ["LOW", "STANDARD", "HIGH"])),
                        name="curve_init_risk_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "state__in",
                                [
                                    "DRAFT",
                                    "ALIGNING",
                                    "PRD_REVIEW",
                                    "PLANNING",
                                    "PLAN_REVIEW",
                                    "EXECUTING",
                                    "CODE_READINESS_REVIEW",
                                    "READY_FOR_REPOSITORY_REVIEW",
                                    "PAUSED",
                                    "FAILED",
                                    "CANCELLED",
                                ],
                            )
                        ),
                        name="curve_init_state_ck",
                    ),
                    models.CheckConstraint(condition=models.Q(("version__gte", 1)), name="curve_init_version_ck"),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("paused_from_state__in", ["DRAFT", "ALIGNING"]), ("state", "PAUSED"))
                            | (~models.Q(("state", "PAUSED")) & models.Q(("paused_from_state__isnull", True)))
                        ),
                        name="curve_init_paused_from_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("state", "DRAFT"), ("workflow_version_id__isnull", True))
                            | models.Q(("state", "ALIGNING"), ("workflow_version_id__isnull", False))
                            | models.Q(
                                ("paused_from_state", "DRAFT"),
                                ("state", "PAUSED"),
                                ("workflow_version_id__isnull", True),
                            )
                            | models.Q(
                                ("paused_from_state", "ALIGNING"),
                                ("state", "PAUSED"),
                                ("workflow_version_id__isnull", False),
                            )
                            | models.Q(("state", "CANCELLED"))
                        ),
                        name="curve_init_workflow_state_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("first_external_resource_at__isnull", True)),
                        name="curve_init_external_resource_ck",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GateAssignment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                (
                    "gate_type",
                    models.CharField(
                        choices=[
                            ("PRD_APPROVAL", "PRD approval"),
                            ("PLAN_APPROVAL", "Plan approval"),
                            ("CODE_READINESS", "Code readiness"),
                        ],
                        max_length=32,
                    ),
                ),
                ("approver_user_id", models.UUIDField()),
                ("valid_from", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("valid_until", models.DateTimeField(blank=True, editable=False, null=True)),
                ("delegation_reason", models.TextField(blank=True, editable=False, null=True)),
                (
                    "initiative",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="gate_assignments",
                        to="curve.initiative",
                    ),
                ),
            ],
            options={
                "db_table": "curve_gate_assignment",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "initiative", "gate_type"),
                        name="curve_gate_ws_init_type_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("gate_type__in", ["PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"])),
                        name="curve_gate_type_ck",
                    ),
                ],
            },
        ),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("policy_key", "CURVE_CORE_POLICY"), ("policy_version__in", [1, 2]))
                    | models.Q(("policy_key", "CURVE_PRODUCT_POLICY"), ("policy_version", 1))
                    | models.Q(("policy_key", "CURVE_INITIATIVE_POLICY"), ("policy_version", 1))
                ),
                name="curve_policy_identity_ck",
            ),
        ),
    ]
