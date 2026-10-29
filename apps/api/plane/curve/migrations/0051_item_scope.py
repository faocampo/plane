# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Item-scope preparation policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:5961483b36ffaecec9778afb77e64232b11ebb8763886f9dd9d1107e527382fe"
BASELINE_CATALOG_DIGEST = "sha256:c84fca16d4636516d613189efc569b1ed1c091b4cb9749570924c551d2ca72b0"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:5cf8b99c900bd818b87ef2b4250034fab293e5e36dba3ecd4ec99e399b65d8c7"
POLICY_DIGEST = "sha256:581156a46abc16e9591007d9695f2627405778c2338a8e119d406fe0b8a0320a"
ROOT = Path(__file__).resolve().parents[1] / "items"
SQL_DIGESTS = {
    "scope-coverage-reverse.sql": "sha256:3d1db903af0c54d25f417337727a075874a08eb1331c2e8fdf6e9a7a1c3d132c",
    "scope-coverage-forward.sql": "sha256:a894cae6f965901e89acae3959c2664f16e95670e109fdb8be39f3daa592197d",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("ITEM_SCOPE_PREPARATION_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("ITEM_SCOPE_PREPARATION_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ITEM_SCOPE_PREPARATION_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("ITEM_SCOPE_PREPARATION_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0050_item_read.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ITEM_SCOPE_PREPARATION_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ITEM_SCOPE_PREPARATION_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_item_scope_coverage VALUES (%s,%s)",
            ["CURVE_ITEM_SCOPE_PREPARATION_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ITEM_SCOPE_PREPARATION_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_ITEM_SCOPE_PREPARATION_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ITEM_SCOPE_PREPARATION_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0050_item_read")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0050_item_read")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_ITEM_SCOPE_PREPARATION_POLICY",
                    policy_version=1,
                    policy_manifest_digest=POLICY_DIGEST,
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("scope-coverage-forward.sql"), _sql("scope-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_item_scope_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_item_scope_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_item_scope_coverage_immutable ON curve_item_scope_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
