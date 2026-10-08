# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("curve", "0013_initiative_prd_lifecycle")]
    operations = [
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                name="curve_policy_identity_ck",
                condition=(
                    models.Q(policy_key="CURVE_CORE_POLICY", policy_version__in=[1, 2])
                    | models.Q(policy_key="CURVE_PRODUCT_POLICY", policy_version=1)
                    | models.Q(policy_key="CURVE_INITIATIVE_POLICY", policy_version=1)
                    | models.Q(
                        policy_key="CURVE_PRD_POLICY",
                        policy_version=1,
                        policy_manifest_digest="sha256:ad38408f0e4450c615025debdf3361965f3a7361ad392aaf9aeb4219b910cb4c",
                    )
                ),
            ),
        ),
        migrations.RunSQL(
            migrations.RunSQL.noop,
            """
            LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE;
            DO $$ BEGIN
             IF EXISTS (SELECT 1 FROM curve_policy_decision WHERE policy_key = 'CURVE_PRD_POLICY') THEN
              RAISE EXCEPTION 'Retained PRD policy decisions require a preservation migration';
             END IF;
            END $$;
        """,
        ),
    ]
