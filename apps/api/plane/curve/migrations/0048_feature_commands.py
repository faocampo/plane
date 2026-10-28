# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Feature-command policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:dcda7c3e47343807439ed6b3b7de50510bb77bcf6a74e19d62a7b499f376469c"
BASELINE_CATALOG_DIGEST = "sha256:4a8fee9e5ad38955807064e53668509319474c13812e1011a46ea00c1555d134"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:e67aa62a1c15ee94c0dffc0029646aff17a5a15c5037928beae5edb5886e044f"
POLICY_DIGEST = "sha256:ace52edc89c7c788a31c3665ff081fc026f2bf9fda242900a4b47d580812da98"
ROOT = Path(__file__).resolve().parents[1] / "features"
SQL_DIGESTS = {
    "command-coverage-reverse.sql": "sha256:6839c0d2f8a966e34ef5ad7e8139bc59898ef48a649476ccc13b1f699892403f",
    "command-coverage-forward.sql": "sha256:43b50b1ed8dab7a3c6c9fb018a47a4fa9837489c76f7d04572e4960a7802f8d3",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("FEATURE_COMMAND_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("FEATURE_COMMAND_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("FEATURE_COMMAND_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("FEATURE_COMMAND_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0047_feature_editor_commands.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("FEATURE_COMMAND_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("FEATURE_COMMAND_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_feature_command_coverage VALUES (%s,%s)",
            ["CURVE_FEATURE_COMMAND_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("FEATURE_COMMAND_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_FEATURE_COMMAND_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("FEATURE_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0047_feature_editor_commands")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0047_feature_editor_commands")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_FEATURE_COMMAND_POLICY", policy_version=1, policy_manifest_digest=POLICY_DIGEST
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("command-coverage-forward.sql"), _sql("command-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_feature_command_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_feature_command_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_feature_command_coverage_immutable ON curve_feature_command_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
