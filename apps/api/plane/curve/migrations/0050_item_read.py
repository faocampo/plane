# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Item-read policy successor with independently verified database catalog."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:c84fca16d4636516d613189efc569b1ed1c091b4cb9749570924c551d2ca72b0"
BASELINE_CATALOG_DIGEST = "sha256:83018280344e20ff40ad57927bdb3001c4e5252f3086e61dc27dbdc69d07de9d"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:cebb825cc3a676c913f34c4880e06ab29182b9862979d7bd32b7d3ad71791d72"
POLICY_DIGEST = "sha256:81e01d779aa6b6fe5a5fce8633a35b7a2d8f9f1ab2cbc7ca0a4af5ac971c3937"
ROOT = Path(__file__).resolve().parents[1] / "items"
SQL_DIGESTS = {
    "read-coverage-reverse.sql": "sha256:4281e64c5c80df7cf1c781d6e68e223b3af56ddc6d72c18155f42b3531204853",
    "read-coverage-forward.sql": "sha256:511c4e260c231c2c808366356a3c55ceb9541ab304f9d39da2115cd48af07432",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("ITEM_READ_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("ITEM_READ_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ITEM_READ_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("ITEM_READ_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0049_item_creation.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ITEM_READ_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ITEM_READ_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_item_read_coverage VALUES (%s,%s)",
            ["CURVE_ITEM_READ_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ITEM_READ_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_ITEM_READ_POLICY')")
        if cursor.fetchone()[0]:
            raise RuntimeError("ITEM_READ_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0049_item_creation")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0049_item_creation")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(policy_key="CURVE_ITEM_READ_POLICY", policy_version=1, policy_manifest_digest=POLICY_DIGEST),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(_sql("read-coverage-forward.sql"), _sql("read-coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_item_read_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_item_read_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_item_read_coverage_immutable ON curve_item_read_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
