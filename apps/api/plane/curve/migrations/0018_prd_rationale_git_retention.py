# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("curve", "0017_prd_git_retention")]
    operations = [
        migrations.AddField(
            model_name="prdreviewdecision",
            name="metadata_schema_version",
            field=models.CharField(max_length=32, default="1.0-candidate", db_default="1.0-candidate", editable=False),
        ),
        migrations.AlterField(
            model_name="prdreviewdecision",
            name="rationale_retention_policy_version_id",
            field=models.CharField(max_length=40, editable=False),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        metadata_schema_version="1.0-candidate",
                        rationale_retention_policy_version_id__regex=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    )
                    | models.Q(
                        metadata_schema_version="2.0-candidate",
                        rationale_retention_policy_version_id__regex=r"^[0-9a-f]{40}$",
                    )
                ),
                name="curve_prd_rationale_edition_ck",
            ),
        ),
        migrations.RunSQL(
            migrations.RunSQL.noop,
            """
            LOCK TABLE curve_prd_review_decision IN ACCESS EXCLUSIVE MODE;
            DO $$ BEGIN
              IF EXISTS(SELECT 1 FROM curve_prd_review_decision
                        WHERE metadata_schema_version <> '1.0-candidate') THEN
                RAISE EXCEPTION 'Retained Git rationale records require a preservation migration';
              END IF;
            END $$;
            """,
        ),
    ]
