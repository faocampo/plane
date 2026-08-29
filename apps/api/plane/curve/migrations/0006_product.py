# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("curve", "0005_providerconnection_providercapability"),
    ]

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("schema_version", models.CharField(default="1.0", editable=False, max_length=20)),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("key", models.CharField(editable=False, max_length=50)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, null=True)),
                ("timezone", models.CharField(max_length=255)),
                (
                    "state",
                    models.CharField(
                        choices=[("ACTIVE", "Active"), ("ARCHIVED", "Archived")],
                        default="ACTIVE",
                        max_length=16,
                    ),
                ),
                ("owner_user_id", models.UUIDField()),
                ("version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True, editable=False)),
                ("created_by", models.JSONField(editable=False)),
                ("updated_by", models.JSONField(editable=False)),
                ("archived_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("archived_by", models.JSONField(blank=True, editable=False, null=True)),
            ],
            options={
                "db_table": "curve_product",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "key"),
                        name="curve_product_workspace_key_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("key__regex", "^[a-z0-9][a-z0-9-]{0,49}$")),
                        name="curve_product_key_format_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("name", ""), _negated=True),
                        name="curve_product_name_nonempty_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("state__in", ["ACTIVE", "ARCHIVED"])),
                        name="curve_product_state_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("version__gte", 1)),
                        name="curve_product_version_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("archived_at__isnull", True),
                                ("archived_by__isnull", True),
                                ("state", "ACTIVE"),
                            ),
                            models.Q(
                                ("archived_at__isnull", False),
                                ("archived_by__isnull", False),
                                ("state", "ARCHIVED"),
                            ),
                            _connector="OR",
                        ),
                        name="curve_product_archival_fields_ck",
                    ),
                ],
            },
        ),
        migrations.RemoveConstraint(
            model_name="policydecision",
            name="curve_policy_identity_ck",
        ),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("policy_key", "CURVE_CORE_POLICY"), ("policy_version__in", [1, 2])),
                    models.Q(("policy_key", "CURVE_PRODUCT_POLICY"), ("policy_version", 1)),
                    _connector="OR",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX curve_product_workspace_state_key_idx "
                "ON curve_product (workspace_id, state, key)"
            ),
            reverse_sql="DROP INDEX IF EXISTS curve_product_workspace_state_key_idx",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX curve_product_workspace_owner_state_idx "
                "ON curve_product (workspace_id, owner_user_id, state)"
            ),
            reverse_sql="DROP INDEX IF EXISTS curve_product_workspace_owner_state_idx",
        ),
    ]
