# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:912984476f3d194cb41d08963733eba16828b5bae7f3991d7d6793166d227dc2"
BASELINE_CATALOG_DIGEST = "sha256:686647dc47a2fe04fbc427615338a69f2b6574d6d3c3566450022357006b371a"
CURRENT_CATALOG_DIGEST = "sha256:61e61f1f432642210b96957bd10ae4c73b907db171c79978090c7f202c6c1b27"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-review-command-forward.sql", "sha256:b8ad66d06a1070901fadbe6a9a0aaa007c54815653b188843ad35120f3c79320"
)
REVERSE_SQL = _sql(
    "local-review-command-reverse.sql", "sha256:d41686d23907c7e0eb8a4564571b99d28fbfef6d81ad54ba70112b05a6ad7e5e"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_review_command_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_review_command_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0033_local_prd_lifecycle")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0033_local_prd_lifecycle.py")
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
            "INSERT INTO curve_local_review_command_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_REVIEW_COMMAND_V1", CURRENT_CATALOG_DIGEST],
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
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_LOCAL_PRD_REVIEW_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_REVIEW_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0033_local_prd_lifecycle")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0031_local_prd_command")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_LOCAL_PRD_REVIEW_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:94abe4a0334cd7c178bdfac348655bc768fbacf2fa8bb8bdec1b03998bd7296d",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_local_review_command_coverage_immutable ON curve_local_review_command_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
