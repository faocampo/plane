# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("curve", "0007_initiative_gateassignment")]

    operations = [
        migrations.AlterField(
            model_name="initiative",
            name="schema_version",
            field=models.CharField(default="1.1", editable=False, max_length=20),
        ),
        migrations.AddField(
            model_name="initiative",
            name="business_intent",
            field=models.CharField(
                blank=True,
                choices=[
                    ("STRATEGIC", "Strategic"),
                    ("CUSTOMER_COMMITMENT", "Customer commitment"),
                    ("BUSINESS_IMPROVEMENT", "Business improvement"),
                    ("MANDATORY", "Mandatory"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="initiative",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("business_intent__isnull", True))
                    | models.Q(
                        (
                            "business_intent__in",
                            ["STRATEGIC", "CUSTOMER_COMMITMENT", "BUSINESS_IMPROVEMENT", "MANDATORY"],
                        )
                    )
                ),
                name="curve_init_business_intent_ck",
            ),
        ),
    ]
