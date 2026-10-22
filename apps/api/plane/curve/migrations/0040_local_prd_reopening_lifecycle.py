# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
from django.db import migrations


PREDECESSOR_DIGEST = "sha256:6ea756025b875177b40c2b706807b1ad90ccd04c3b7518b831a21d1ab4ebfb64"
BASELINE_CATALOG_DIGEST = "sha256:663c765011f3d9423704e1d3fb3758ee8ed8d6b589ea8dc2271d38f55bbbd3b6"
CURRENT_CATALOG_DIGEST = "sha256:1920e236fcbc4ddb00b75e3a6cd82aaebadb774b41b9eca3c23a008e6dabf118"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-reopening-lifecycle-forward.sql",
    "sha256:1f98acbb5465a01d340dd4fa24f800140fcb1db30e617572b8b94a256122a9a0",
)
REVERSE_SQL = _sql(
    "local-prd-reopening-lifecycle-reverse.sql",
    "sha256:2681bd004f2861ee001647bf5990685b90803ca94677e49a61dcafbdc012ec36",
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_prd_reopening_lifecycle_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_prd_reopening_lifecycle_coverage FOR EACH STATEMENT "
    "EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0039_local_prd_reopening")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0039_local_prd_reopening.py")
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
            "INSERT INTO curve_local_prd_reopening_lifecycle_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PRD_REOPENING_LIFECYCLE_V1", CURRENT_CATALOG_DIGEST],
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
    dependencies = [("curve", "0039_local_prd_reopening")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_local_prd_reopening_lifecycle_coverage_immutable "
            "ON curve_local_prd_reopening_lifecycle_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
