# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
import django.db.models.deletion
import uuid
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:a87b1b9198f07800eb026e468f01197d1c29694bf3674d4e20163ce213b6da09"
BASELINE_CATALOG_DIGEST = "sha256:61e61f1f432642210b96957bd10ae4c73b907db171c79978090c7f202c6c1b27"
CURRENT_CATALOG_DIGEST = "sha256:d6fc20764bb94c03248733d050de7cf9a65688ae7589d05c5dd98a7a25e26122"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-plan-revision-forward.sql", "sha256:6026ad6953b02a88677b92db645f03516421af7551e62979cc8993d277e0424d"
)
REVERSE_SQL = _sql(
    "local-plan-revision-reverse.sql", "sha256:49c1b7d222ef9ec36cd0e5429adef161e38504be75790020d6bc2a8a85148fcf"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_plan_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_plan_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0034_local_review_commands")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0034_local_review_commands.py")
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
            "INSERT INTO curve_local_plan_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PLAN_REVISION_V1", CURRENT_CATALOG_DIGEST],
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
        cursor.execute("LOCK TABLE curve_local_plan_revision IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM curve_local_plan_revision)")
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_PLAN_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0034_local_review_commands")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.CreateModel(
            name="LocalPlanRevision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "prd_submission",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.localprdsubmission"),
                ),
                (
                    "prd_decision",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.localprddecision"),
                ),
                (
                    "predecessor",
                    models.ForeignKey(
                        null=True, on_delete=django.db.models.deletion.PROTECT, to="curve.localplanrevision"
                    ),
                ),
            ],
            options={
                "db_table": "curve_local_plan_revision",
                "constraints": [
                    models.UniqueConstraint(fields=["workspace_id", "initiative", "id"], name="curve_lplan_scope_uq"),
                    models.UniqueConstraint(
                        fields=["workspace_id", "initiative", "version"], name="curve_lplan_version_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(version__gte=1, version__lte=9007199254740991), name="curve_lplan_version_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(initiative_version__gte=1, initiative_version__lte=9007199254740991),
                        name="curve_lplan_initversion_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_lplan_digest_ck"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(SEAL_SQL, "DROP TRIGGER curve_local_plan_coverage_immutable ON curve_local_plan_coverage;"),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
