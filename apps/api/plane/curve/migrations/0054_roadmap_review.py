# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Roadmap document approval successor preserving historical submission editions."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations

CURRENT_CATALOG_DIGEST = "sha256:03ff9bcb3f59e4767fca837cea1a5499e3a67c0649cf2ffe7858aba8d4ba96fb"
BASELINE_CATALOG_DIGEST = "sha256:16de58e10fd25809de012e328db46086993a88800c12189d3600ef2666b10e57"
EXTERNAL_CATALOG_DIGEST = "sha256:1a6ad37d77588a211aed0eddd2c023e8b0fe8380af30456138fb27520a8146ae"
PREDECESSOR_DIGEST = "sha256:fa8d079de77de79a35886cb8f29d8f45f1b4950f0820634a654a5894ef52d7f1"
ROOT = Path(__file__).resolve().parents[1] / "roadmap_review"
SQL_DIGESTS = {
    "context.sql": "sha256:04e801bc6714890061a02a229013ca6599840206ed64600dc180e71974dd6256",
    "coverage-forward.sql": "sha256:1ce439d5eae9574eed63b07444fdff089d2ef129c27bd0c738dd452fcf08ae0d",
    "coverage-reverse.sql": "sha256:6c2907e571340a4449f5331b2a0c8ae3ba23f2ae317c249a0932291d26400572",
    "guards-forward.sql": "sha256:710c928702a82d62b9112bb68d848c039507227585fbe1617c2ea0ace003d04f",
    "guards-reverse.sql": "sha256:a0e708a48750de7a5a18a228af3ba056d101411ba182945db23df0debf8b5470",
    "shape.sql": "sha256:1d77c2daef0aed57395cdc3d20e0e14769d116f0be1c84e7b3631bd811171500",
}


def _sql(name):
    path = ROOT / name
    if path.is_symlink():
        raise RuntimeError("ROADMAP_REVIEW_SQL_LINK_UNAVAILABLE")
    value = path.read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != SQL_DIGESTS[name]:
        raise RuntimeError("ROADMAP_REVIEW_SQL_BYTES_CHANGED")
    return value.decode()


def _catalog(cursor):
    return import_module("plane.curve.migrations.0046_feature_editor_storage")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ROADMAP_REVIEW_DATABASE_QUALIFICATION_REQUIRED")


def _verify_external(cursor):
    # Execute the pinned projection independently: the installed function is
    # itself part of the catalog being checked and cannot supply its own proof.
    predecessor = import_module("plane.curve.migrations.0046_feature_editor_storage")
    query = predecessor._sql("external-catalog.sql").split("$catalog$")[1].strip().rstrip(";")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + query + ")::text,'UTF8')),'hex')")
    if cursor.fetchone()[0] != EXTERNAL_CATALOG_DIGEST:
        raise RuntimeError("ROADMAP_REVIEW_EXTERNAL_CATALOG_CHANGED")


def verify_predecessor(apps, schema_editor):
    source = Path(__file__).with_name("0053_item_cancellation.py")
    if "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ROADMAP_REVIEW_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_REVIEW_PREDECESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_roadmap_review_coverage VALUES (%s,%s)",
            ["CURVE_ROADMAP_REVIEW_V3", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_REVIEW_SUCCESSOR_CATALOG_CHANGED")
        _verify_external(cursor)
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE curve_local_prd_source, curve_local_prd_submission, "
            "curve_local_plan_revision, curve_initiative IN ACCESS EXCLUSIVE MODE"
        )
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_local_prd_source s "
            "JOIN curve_initiative i ON i.workspace_id=s.workspace_id AND i.id=s.initiative_id "
            "WHERE i.mode='ROADMAP') OR EXISTS(SELECT 1 FROM curve_local_prd_submission "
            "WHERE payload->>'schema_version'='curve.local-prd-submission/v3-roadmap-candidate')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ROADMAP_REVIEW_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0053_item_cancellation")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RunSQL(_sql("context.sql"), "DROP FUNCTION curve_local_roadmap_review_context(jsonb,uuid,uuid);"),
        migrations.RunSQL(_sql("shape.sql"), "DROP FUNCTION curve_local_roadmap_review_shape(jsonb);"),
        migrations.RunSQL(_sql("guards-forward.sql"), _sql("guards-reverse.sql")),
        migrations.RunSQL(_sql("coverage-forward.sql"), _sql("coverage-reverse.sql")),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            "CREATE TRIGGER curve_roadmap_review_coverage_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_roadmap_review_coverage "
            "FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();",
            "DROP TRIGGER curve_roadmap_review_coverage_immutable ON curve_roadmap_review_coverage;",
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
