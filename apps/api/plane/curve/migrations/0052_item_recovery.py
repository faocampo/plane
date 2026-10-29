# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Item recovery policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:7bc2177e1c6d7b6a9a49545e45912cf73eb434377eab5e21b8770ce09014e5a3"
BASELINE_CATALOG_DIGEST = "sha256:5961483b36ffaecec9778afb77e64232b11ebb8763886f9dd9d1107e527382fe"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:562e9f0cff0dbb816ef5869f2c2ae8c0369554d601187acb03e2860524e00a4a"
POLICY_DIGEST = "sha256:25446da54a7142beba837842006c182b27f76fcdf02ed35c5999863af18e16ff"
ROOT = Path(__file__).resolve().parents[1] / "items"
SQL_DIGESTS = {
    "recovery-coverage-reverse.sql": "sha256:19e80cc2fdb0e980c0a3d6478e8aad9f8150e2a06b7f5acb95016ca4dab8046e",
    "recovery-coverage-forward.sql": "sha256:54a0b12f39b69fa70d55c18cbabe2e767fd88148251caf5e7c00778ff0956be9",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("ITEM_RECOVERY_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("ITEM_RECOVERY_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ITEM_RECOVERY_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("ITEM_RECOVERY_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0051_item_scope.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ITEM_RECOVERY_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ITEM_RECOVERY_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_item_recovery_coverage VALUES (%s,%s)",
            ["CURVE_ITEM_RECOVERY_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ITEM_RECOVERY_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_ITEM_RECOVERY_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ITEM_RECOVERY_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0051_item_scope")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0051_item_scope")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_ITEM_RECOVERY_POLICY",
                    policy_version=1,
                    policy_manifest_digest=POLICY_DIGEST,
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("recovery-coverage-forward.sql"), _sql("recovery-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_item_recovery_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_item_recovery_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_item_recovery_coverage_immutable ON curve_item_recovery_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
