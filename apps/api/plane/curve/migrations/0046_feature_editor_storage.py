# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Add scoped Feature editor storage without enabling new command writers."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations

CURRENT_CATALOG_DIGEST = "sha256:0180f41f0af33c6da885bba573793f5b19d927464c857977dd70579a7a78ee22"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
BASELINE_CATALOG_DIGEST = "sha256:bc85b48c76b9d83462078cd09e57f9c2e27434d4bd338c42935503c55ef40c59"
PREDECESSOR_DIGEST = "sha256:1a8fe5f0d98ff5a82483bced46ad78ed1a7a31e1c24ca5936470151ef560b841"
ROOT = Path(__file__).resolve().parents[1] / "feature_editors"
SQL_DIGESTS = {
    "membership-lifetime.sql": "sha256:921cea70e40e136ad545659dd591c410501dd9586a56b6d430b07b8ae35c1638",
    "grants.sql": "sha256:44b0a8f4cdde1cc6cf24c19cafd524e756477fffdea6510cc61c2486965e76a4",
    "external-catalog.sql": "sha256:af75f9658d28f7b95fee9e12f046bb5e3e6b070d668eea9c441195b9519d1427",
    "coverage-forward.sql": "sha256:39ee86c774ee30544561161022fde8afe6778a03c54b6d34496bf54896e81404",
    "coverage-reverse.sql": "sha256:444b6574258bf8d79e4fcac8745af7e1ccc59c983f0a84adcdac91ecc49e22ea",
    "storage-reverse.sql": "sha256:cc4471ec6da7da916f300520580ec68df1fd1698b65b5f06a150bf13caaf9309",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("FEATURE_EDITOR_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("FEATURE_EDITOR_SQL_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = "\n".join(
    _sql(name) for name in ("membership-lifetime.sql", "grants.sql", "external-catalog.sql", "coverage-forward.sql")
)
REVERSE_SQL = _sql("coverage-reverse.sql") + "\n" + _sql("storage-reverse.sql")
SEAL_SQL = (
    "CREATE TRIGGER curve_feature_editor_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_feature_editor_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0045_roadmap_hierarchy_commands")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None or EXTERNAL_CATALOG_DIGEST is None:
        raise RuntimeError("FEATURE_EDITOR_POSTGRESQL_QUALIFICATION_REQUIRED")


def verify_predecessor(apps, schema_editor):
    previous = Path(__file__).with_name("0045_roadmap_hierarchy_commands.py")
    if "sha256:" + hashlib.sha256(previous.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("FEATURE_EDITOR_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("FEATURE_EDITOR_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_feature_editor_coverage VALUES (%s,%s,%s)",
            ["CURVE_FEATURE_EDITOR_STORAGE_V1", CURRENT_CATALOG_DIGEST, EXTERNAL_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("FEATURE_EDITOR_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE workspace_members IN ACCESS EXCLUSIVE MODE")
        cursor.execute("LOCK TABLE curve_feature_membership_lifetime IN ACCESS EXCLUSIVE MODE")
        cursor.execute("LOCK TABLE curve_feature_editor_grant IN ACCESS EXCLUSIVE MODE")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM curve_feature_editor_grant)")
        if cursor.fetchone()[0]:
            raise RuntimeError("FEATURE_EDITOR_RETAINED_GRANTS_PREVENT_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0045_roadmap_hierarchy_commands")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        # Cover backfill and trigger installation with one membership write barrier.
        migrations.RunSQL("LOCK TABLE workspace_members IN SHARE ROW EXCLUSIVE MODE", migrations.RunSQL.noop),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_feature_editor_coverage_immutable ON curve_feature_editor_coverage;"
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
