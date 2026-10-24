# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
COMMIT_PATTERN = r"^[0-9a-f]{40}$"


class Migration(migrations.Migration):
    dependencies = [("curve", "0016_prd_readiness_record")]
    operations = [
        migrations.AddField(
            model_name="prdartifactversion",
            name="metadata_schema_version",
            field=models.CharField(max_length=32, default="1.0-candidate", db_default="1.0-candidate", editable=False),
        ),
        migrations.AddField(
            model_name="documentcheckpoint",
            name="metadata_schema_version",
            field=models.CharField(max_length=32, default="1.0", db_default="1.0", editable=False),
        ),
        migrations.AlterField(
            model_name="prdartifactversion",
            name="retention_policy_version_id",
            field=models.CharField(max_length=40, editable=False),
        ),
        migrations.AlterField(
            model_name="documentcheckpoint",
            name="retention_policy_version_id",
            field=models.CharField(max_length=40, editable=False),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(metadata_schema_version="1.0-candidate", retention_policy_version_id__regex=UUID_PATTERN)
                    | models.Q(
                        metadata_schema_version="2.0-candidate", retention_policy_version_id__regex=COMMIT_PATTERN
                    )
                ),
                name="curve_prd_retention_ver_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="documentcheckpoint",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(metadata_schema_version="1.0", retention_policy_version_id__regex=UUID_PATTERN)
                    | models.Q(metadata_schema_version="2.0", retention_policy_version_id__regex=COMMIT_PATTERN)
                ),
                name="curve_cp_retention_edition_ck",
            ),
        ),
        migrations.RunSQL(
            migrations.RunSQL.noop,
            """
          LOCK TABLE curve_prd_artifact_version, curve_document_checkpoint IN ACCESS EXCLUSIVE MODE;
          DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM curve_prd_artifact_version WHERE metadata_schema_version <> '1.0-candidate')
              OR EXISTS(SELECT 1 FROM curve_document_checkpoint WHERE metadata_schema_version <> '1.0') THEN
              RAISE EXCEPTION 'Retained Git policy records require a preservation migration';
            END IF;
          END $$;
        """,
        ),
    ]
