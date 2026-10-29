# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Item cancellation policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:16de58e10fd25809de012e328db46086993a88800c12189d3600ef2666b10e57"
BASELINE_CATALOG_DIGEST = "sha256:7bc2177e1c6d7b6a9a49545e45912cf73eb434377eab5e21b8770ce09014e5a3"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:258c588dd431706e3748a04b419e86d13bbebd5fb4bc11e17c3d54f16ebb4656"
POLICY_DIGEST = "sha256:33ee9e2610ffde77961f8101099374ffe3617f758ad8cd5d5cde301d544d862c"
ROOT = Path(__file__).resolve().parents[1] / "items"
SQL_DIGESTS = {
    "cancellation-coverage-reverse.sql": "sha256:66f59336c5ab40866b7cb8c9d3428d03328862b0cff15e1428f5bb5f4441dc96",
    "cancellation-coverage-forward.sql": "sha256:7f4950b893e3955129a79373f3fcad24375cc6965894d72df5b0e905cc05f77f",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("ITEM_CANCELLATION_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("ITEM_CANCELLATION_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ITEM_CANCELLATION_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("ITEM_CANCELLATION_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0052_item_recovery.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ITEM_CANCELLATION_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ITEM_CANCELLATION_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_item_cancellation_coverage VALUES (%s,%s)",
            ["CURVE_ITEM_CANCELLATION_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ITEM_CANCELLATION_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_ITEM_CANCELLATION_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ITEM_CANCELLATION_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0052_item_recovery")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0052_item_recovery")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_ITEM_CANCELLATION_POLICY",
                    policy_version=1,
                    policy_manifest_digest=POLICY_DIGEST,
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("cancellation-coverage-forward.sql"), _sql("cancellation-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_item_cancellation_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_item_cancellation_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_item_cancellation_coverage_immutable ON curve_item_cancellation_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
