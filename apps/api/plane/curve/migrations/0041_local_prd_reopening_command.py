# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:b0a69ba15b6e95614346167d5943153d4dc64e61775e745c600a1b03eeeab2d3"
BASELINE_CATALOG_DIGEST = "sha256:1920e236fcbc4ddb00b75e3a6cd82aaebadb774b41b9eca3c23a008e6dabf118"
CURRENT_CATALOG_DIGEST = "sha256:f02d946e27d8c8a78d54d21748ce82d4ecf82a109973fb805af92c1f767a174b"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-reopening-command-forward.sql", "sha256:46d441d421966c7003d29100f197bdb535a1758799db8eb42fc06dd1cfba5907"
)
REVERSE_SQL = _sql(
    "local-prd-reopening-command-reverse.sql", "sha256:1273bb2b1f85125adbc783fa7ecacf93092240499636402dde0954065cf9ae6b"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_reopen_command_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_reopen_command_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0040_local_prd_reopening_lifecycle")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0040_local_prd_reopening_lifecycle.py")
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
            "INSERT INTO curve_local_reopen_command_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PRD_REOPENING_COMMAND_V1", CURRENT_CATALOG_DIGEST],
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
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_LOCAL_PRD_REOPENING_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_REVIEW_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0040_local_prd_reopening_lifecycle")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0038_local_plan_review_commands")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_LOCAL_PRD_REOPENING_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:ac4466f235b1f0baefe4ea35285f65cfe44e144ee7de3bbf89dda57af17a7616",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_local_reopen_command_coverage_immutable ON curve_local_reopen_command_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
