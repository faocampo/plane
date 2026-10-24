# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:5050ef5b4970e28ec4e98fe95c73108fbf40c29ca09c0ea2cbb6dc0f70fef9ed"
BASELINE_CATALOG_DIGEST = "sha256:d6fc20764bb94c03248733d050de7cf9a65688ae7589d05c5dd98a7a25e26122"
CURRENT_CATALOG_DIGEST = "sha256:ee2a07a279b1f5a6f1c3346dc716644015e4469e3db5938a51e37995c372487c"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-plan-upload-forward.sql", "sha256:ebbea7bc8b66e6958267c2da568ef37c7bd4806a05ab7ed5152bd3c48bb253cf"
)
REVERSE_SQL = _sql(
    "local-plan-upload-reverse.sql", "sha256:9d370456f999adc2ff0f348effa3d75166e8eb3eca589b7f0277a89e3b24c6d4"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_plan_upload_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_plan_upload_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0035_local_plan_revision")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0035_local_plan_revision.py")
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
            "INSERT INTO curve_local_plan_upload_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PLAN_UPLOAD_V1", CURRENT_CATALOG_DIGEST],
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
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_LOCAL_PLAN_UPLOAD_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_REVIEW_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0035_local_plan_revision")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0034_local_review_commands")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_LOCAL_PLAN_UPLOAD_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:7bbfdcb956071376e58dd18870613470d1e4a4e75c3ef18d4153400480231937",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_local_plan_upload_coverage_immutable ON curve_local_plan_upload_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
