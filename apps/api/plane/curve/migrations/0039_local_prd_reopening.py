# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
import uuid
import django.db.models.deletion
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:1257b88127f7ca951f7f957fc058bae76fb79749e593522041eed17e713edccf"
BASELINE_CATALOG_DIGEST = "sha256:bfb5d8f7e8a436454ed51d95c3d0f1fd1d6436c45e3bcb557b33857fb1d8e683"
CURRENT_CATALOG_DIGEST = "sha256:663c765011f3d9423704e1d3fb3758ee8ed8d6b589ea8dc2271d38f55bbbd3b6"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-reopening-forward.sql", "sha256:fa334cd7f3201d135638aea0708edb110027b9b630bda9f590517b36052775bf"
)
REVERSE_SQL = _sql(
    "local-prd-reopening-reverse.sql", "sha256:f44f1f9f8f578496626bc0951cb2456d3a864e873c59354e0575e64e82159a78"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_prd_reopening_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_prd_reopening_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0038_local_plan_review_commands")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0038_local_plan_review_commands.py")
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("LOCAL_PRD_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("LOCAL_PRD_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("LOCAL_PRD_POSTGRESQL_QUALIFICATION_REQUIRED")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_prd_reopening_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PRD_REOPENING_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("LOCAL_PRD_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_local_prd_reopening IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM curve_local_prd_reopening)")
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_REOPENING_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0038_local_plan_review_commands")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.CreateModel(
            name="LocalPrdReopening",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("digest", models.CharField(max_length=71, editable=False)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "submission",
                    models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="curve.localprdsubmission"),
                ),
                (
                    "decision",
                    models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="curve.localprddecision"),
                ),
            ],
            options={
                "db_table": "curve_local_prd_reopening",
                "constraints": [
                    models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lpro_scope_uq"),
                    models.UniqueConstraint(
                        fields=["workspace_id", "initiative", "initiative_version"], name="curve_lpro_version_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                        name="curve_lpro_version_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lpro_digest_ck"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_local_prd_reopening_coverage_immutable ON curve_local_prd_reopening_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
