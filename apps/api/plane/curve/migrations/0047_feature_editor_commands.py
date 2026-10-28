# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Editor-command policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:4a8fee9e5ad38955807064e53668509319474c13812e1011a46ea00c1555d134"
BASELINE_CATALOG_DIGEST = "sha256:0180f41f0af33c6da885bba573793f5b19d927464c857977dd70579a7a78ee22"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:a66ac68096efa168782377d78f03a0ad59bb7fb1f6bea2e099030d27e27e8342"
POLICY_DIGEST = "sha256:aba8328b6eca11c095b1529faed962c96708a79c03e69c6db020a54bd7d2bf4e"
ROOT = Path(__file__).resolve().parents[1] / "feature_editors"
SQL_DIGESTS = {
    "command-coverage-reverse.sql": "sha256:a8f11f6946f0c477f5bb6067c937553b8d54afb822d3028b1115c766592329d1",
    "command-coverage-forward.sql": "sha256:5669ad92501780faedde460b46a9e9451a99db82a7519c8639586b675be239ff",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("FEATURE_EDITOR_COMMAND_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("FEATURE_EDITOR_COMMAND_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("FEATURE_EDITOR_COMMAND_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("FEATURE_EDITOR_COMMAND_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0046_feature_editor_storage.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("FEATURE_EDITOR_COMMAND_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("FEATURE_EDITOR_COMMAND_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_feature_editor_command_coverage VALUES (%s,%s)",
            ["CURVE_FEATURE_EDITOR_COMMAND_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("FEATURE_EDITOR_COMMAND_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_FEATURE_EDITOR_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("FEATURE_EDITOR_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0046_feature_editor_storage")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0045_roadmap_hierarchy_commands")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_FEATURE_EDITOR_POLICY", policy_version=1, policy_manifest_digest=POLICY_DIGEST
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("command-coverage-forward.sql"), _sql("command-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_feature_editor_command_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_feature_editor_command_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_feature_editor_command_coverage_immutable ON curve_feature_editor_command_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
