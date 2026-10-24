# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
import django.db.models.deletion
import uuid
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:0f7ffa4584b70178c16745d7713f9d3e1b64ebff395ecec328fcea9c712651ba"
BASELINE_CATALOG_DIGEST = "sha256:ee2a07a279b1f5a6f1c3346dc716644015e4469e3db5938a51e37995c372487c"
CURRENT_CATALOG_DIGEST = "sha256:918031fe6e522af5cc8b5f292079555e0cf1540c8fffb8a1e98d7fab952ea308"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-plan-review-forward.sql", "sha256:96dc08236a7cd20ed17acada022c3794621960544974c0b4906af8530b7cf17d"
)
REVERSE_SQL = _sql(
    "local-plan-review-reverse.sql", "sha256:b42601c5f3c08ca4822026e2034240bb0684469c0928ac96ee53ecb1d470f0f8"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_plan_review_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_plan_review_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0036_local_plan_upload")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0036_local_plan_upload.py")
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
            "INSERT INTO curve_local_plan_review_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PLAN_REVIEW_V1", CURRENT_CATALOG_DIGEST],
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
        cursor.execute("LOCK TABLE curve_local_plan_submission, curve_local_plan_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_local_plan_submission) "
            "OR EXISTS(SELECT 1 FROM curve_local_plan_decision)"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_PLAN_REVIEW_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0036_local_plan_upload")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.CreateModel(
            name="LocalPlanSubmission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "plan_revision",
                    models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="curve.localplanrevision"),
                ),
            ],
            options={
                "db_table": "curve_local_plan_submission",
            },
        ),
        migrations.CreateModel(
            name="LocalPlanDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("state", models.CharField(editable=False, max_length=32)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "plan_submission",
                    models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="curve.localplansubmission"),
                ),
            ],
            options={
                "db_table": "curve_local_plan_decision",
            },
        ),
        migrations.AddConstraint(
            model_name="localplansubmission",
            constraint=models.UniqueConstraint(fields=("workspace_id", "initiative", "id"), name="curve_lpls_scope_uq"),
        ),
        migrations.AddConstraint(
            model_name="localplansubmission",
            constraint=models.CheckConstraint(
                condition=models.Q(("initiative_version__gte", 1), ("initiative_version__lte", 9007199254740991)),
                name="curve_lpls_version_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="localplansubmission",
            constraint=models.CheckConstraint(
                condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_lpls_digest_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="localplandecision",
            constraint=models.UniqueConstraint(fields=("workspace_id", "initiative", "id"), name="curve_lpld_scope_uq"),
        ),
        migrations.AddConstraint(
            model_name="localplandecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("initiative_version__gte", 1), ("initiative_version__lte", 9007199254740991)),
                name="curve_lpld_version_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="localplandecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("state__in", ["APPROVED", "CHANGES_REQUESTED"])), name="curve_lpld_state_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="localplandecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_lpld_digest_ck"
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_local_plan_review_coverage_immutable ON curve_local_plan_review_coverage;"
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
