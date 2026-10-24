# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:1b1eb9d04e5b9a4460b0789d624811e6698d6ea73e00e35d04ebef5619379f3d"
BASELINE_CATALOG_DIGEST = "sha256:72373212877c9f6510b8fec3fa9881d1f9167e5f703ade011a54d81a8b6c519c"
CURRENT_CATALOG_DIGEST = "sha256:686647dc47a2fe04fbc427615338a69f2b6574d6d3c3566450022357006b371a"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-lifecycle-forward.sql", "sha256:fd0e41940e8a9f824697ae087241ace703b7015d26d0a1b8e727b8aa2dc74b1c"
)
REVERSE_SQL = _sql(
    "local-prd-lifecycle-reverse.sql", "sha256:0837a55a0ccf6124eb85105fc6bc6df77e3d3d02a4537394e9f434ca0da7fe67"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_prd_lifecycle_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_prd_lifecycle_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0032_local_prd_review")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0032_local_prd_review.py")
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
            "INSERT INTO curve_local_prd_lifecycle_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PRD_LIFECYCLE_V1", CURRENT_CATALOG_DIGEST],
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
        cursor.execute("LOCK TABLE curve_initiative IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_initiative WHERE current_local_prd_submission_id IS NOT NULL "
            "OR controlling_local_prd_decision_id IS NOT NULL)"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_LIFECYCLE_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0032_local_prd_review")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.AddField(
            model_name="initiative",
            name="current_local_prd_submission_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="initiative",
            name="controlling_local_prd_decision_id",
            field=models.UUIDField(null=True, blank=True, editable=False),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_local_prd_lifecycle_coverage_immutable ON curve_local_prd_lifecycle_coverage;"
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
