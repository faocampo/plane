# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
import django.db.models.deletion
import uuid
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:488b628fb0d86a12789bef356b305deb658e51379842aa1517edf08f1ad19a05"
BASELINE_CATALOG_DIGEST = "sha256:5a0d96f6556657552da753e3f81d79004c0b84622aad7f89789f1a7fa7e1202d"
CURRENT_CATALOG_DIGEST = "sha256:72373212877c9f6510b8fec3fa9881d1f9167e5f703ade011a54d81a8b6c519c"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-review-forward.sql", "sha256:716f43012badcc51099f930bd84ca60476f2924da3fce513b14b00e4f5e0b22b"
)
REVERSE_SQL = _sql(
    "local-prd-review-reverse.sql", "sha256:9018cd1bdaeb9fa222feca1a2bedaad9a0fcdda1dd48b6b70bbb9a8a51e15888"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_prd_review_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_prd_review_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0031_local_prd_command")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0031_local_prd_command.py")
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
            "INSERT INTO curve_local_prd_review_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PRD_REVIEW_V1", CURRENT_CATALOG_DIGEST],
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
        cursor.execute("LOCK TABLE curve_local_prd_submission, curve_local_prd_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_local_prd_submission) OR EXISTS(SELECT 1 FROM curve_local_prd_decision)"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_REVIEW_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("curve", "0031_local_prd_command"),
    ]

    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.CreateModel(
            name="LocalPrdSubmission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.localprdsource")),
            ],
            options={
                "db_table": "curve_local_prd_submission",
            },
        ),
        migrations.CreateModel(
            name="LocalPrdDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("state", models.CharField(editable=False, max_length=32)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "submission",
                    models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="curve.localprdsubmission"),
                ),
            ],
            options={
                "db_table": "curve_local_prd_decision",
            },
        ),
        migrations.AddConstraint(
            model_name="localprdsubmission",
            constraint=models.UniqueConstraint(fields=("workspace_id", "initiative", "id"), name="curve_lprs_scope_uq"),
        ),
        migrations.AddConstraint(
            model_name="localprdsubmission",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "initiative_version"), name="curve_lprs_version_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="localprdsubmission",
            constraint=models.CheckConstraint(
                condition=models.Q(("initiative_version__gte", 1), ("initiative_version__lte", 9007199254740991)),
                name="curve_lprs_version_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="localprdsubmission",
            constraint=models.CheckConstraint(
                condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_lprs_digest_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="localprddecision",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "id"), name="curve_lprd_dec_scope_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="localprddecision",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "initiative_version"), name="curve_lprd_dec_version_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="localprddecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("initiative_version__gte", 1), ("initiative_version__lte", 9007199254740991)),
                name="curve_lprd_dec_version_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="localprddecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("state__in", ["APPROVED", "CHANGES_REQUESTED"])), name="curve_lprd_dec_state_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="localprddecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_lprd_dec_digest_ck"
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_local_prd_review_coverage_immutable ON curve_local_prd_review_coverage;"
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
