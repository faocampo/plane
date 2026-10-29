# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Item-creation policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:83018280344e20ff40ad57927bdb3001c4e5252f3086e61dc27dbdc69d07de9d"
BASELINE_CATALOG_DIGEST = "sha256:dcda7c3e47343807439ed6b3b7de50510bb77bcf6a74e19d62a7b499f376469c"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:d5ec77bbc002f2b9598a5c66cf81b8bce5d6c2e0b02a345a3d9f2fe9743ee26e"
POLICY_DIGEST = "sha256:c2818ca8b74dcd89c4ae8ae91acb0195d8dce9714a17ab2248477637bd7b2adc"
ROOT = Path(__file__).resolve().parents[1] / "items"
SQL_DIGESTS = {
    "creation-coverage-reverse.sql": "sha256:405efdd857155d8126ecc227b2415c0f6822b53795e37cc6d150fecfd14fb1f2",
    "creation-coverage-forward.sql": "sha256:ff82e66cec434b18aea8f81e688ae27a8d9fdffd86c7dfd0743f3f46647032d1",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("ITEM_CREATION_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("ITEM_CREATION_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ITEM_CREATION_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("ITEM_CREATION_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0048_feature_commands.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ITEM_CREATION_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ITEM_CREATION_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_item_creation_coverage VALUES (%s,%s)",
            ["CURVE_ITEM_CREATION_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ITEM_CREATION_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_ITEM_CREATION_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ITEM_CREATION_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0048_feature_commands")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0048_feature_commands")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_ITEM_CREATION_POLICY", policy_version=1, policy_manifest_digest=POLICY_DIGEST
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("creation-coverage-forward.sql"), _sql("creation-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_item_creation_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_item_creation_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_item_creation_coverage_immutable ON curve_item_creation_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
