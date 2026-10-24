# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Add immutable local-upload source identity alongside external document bindings."""

import hashlib
from importlib import import_module
from pathlib import Path
import uuid

from django.db import migrations, models
import django.db.models.deletion

PREDECESSOR_DIGEST = "sha256:0bc9cc2a1e07c9d2f348679452aeae63c86215860ce208fcd4bea4e03e8ba7e3"
BASELINE_CATALOG_DIGEST = "sha256:8b846ec66b306ffc5c95b52818c5bb03acadadde679df7b678da4f3afedc0e64"
CURRENT_CATALOG_DIGEST = "sha256:493f45a0eadfd45263212043ec835fd996ac1968ad2bdeb6e25d23b0657590d3"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-source-forward.sql", "sha256:252c8615002ffe2e76efb4274410d96b560a116f9e382682c246cb3925e81381"
)
REVERSE_SQL = _sql(
    "local-prd-source-reverse.sql", "sha256:76a41d0cdf1cf50f393d55e1a8634d6d9ff05441c3c992eee8aa3586ac079e16"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_prd_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_prd_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0029_technical_review_two_stage")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0029_technical_review_two_stage.py")
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
            "INSERT INTO curve_local_prd_coverage VALUES (%s,%s)", ["CURVE_LOCAL_PRD_SOURCE_V1", CURRENT_CATALOG_DIGEST]
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
        cursor.execute("LOCK TABLE curve_local_prd_source IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM curve_local_prd_source)")
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_PRD_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0029_technical_review_two_stage")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.CreateModel(
            name="LocalPrdSource",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(editable=False)),
                ("uploaded_by", models.UUIDField(editable=False)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "predecessor",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="curve.localprdsource"
                    ),
                ),
            ],
            options={
                "db_table": "curve_local_prd_source",
                "constraints": [
                    models.UniqueConstraint(fields=("workspace_id", "initiative", "id"), name="curve_lprd_scope_uq"),
                    models.UniqueConstraint(
                        fields=("workspace_id", "initiative", "version"), name="curve_lprd_version_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(version__gte=1, version__lte=9007199254740991), name="curve_lprd_version_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lprd_digest_ck"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(SEAL_SQL, "DROP TRIGGER curve_local_prd_coverage_immutable ON curve_local_prd_coverage;"),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
