# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Persist the two-reviewer scoped PRD edition without rewriting historical rows."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

PREDECESSOR_DIGEST = "sha256:1b086dd119c3bd6580d3f560a27de2cfaca4fba7bcec8aaf8688f15f41c26768"
BASELINE_CATALOG_DIGEST = "sha256:fb8f201929aac3461836becdecdde3b29996e52e6aea6ed48c2be6035c1083ef"
CURRENT_CATALOG_DIGEST = "sha256:c14b6221600c6e6be301cc3a36d26cbeb4b3c85e3d904f42e6cbb5e39e67f207"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, expected):
    raw = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("SCOPED_V2_MIGRATION_BYTES_CHANGED")
    return raw.decode("utf-8")


FORWARD_SQL = _sql(
    "scoped-prd-v2-forward.sql", "sha256:b430d12e876f1d778d8be9ed6d518cd8c8d084057cd7354d580bab6e2042a167"
)
REVERSE_SQL = _sql(
    "scoped-prd-v2-reverse.sql", "sha256:3bf7e97054b2781699a0c06ae4392617ad446cab50bf50c60d57363d49c7d842"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_scoped_v2_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_scoped_v2_coverage FOR EACH STATEMENT EXECUTE FUNCTION "
    "curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0025_manual_gate2_reconstruction")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    raw = Path(__file__).with_name("0026_two_stage_approval_policy.py").read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("SCOPED_V2_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("SCOPED_V2_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("SCOPED_V2_POSTGRESQL_QUALIFICATION_REQUIRED")


def install_seal(apps, schema_editor):
    require_qualification(apps, schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_scoped_v2_coverage(edition,catalog_digest) VALUES (%s,%s)",
            ["CURVE_SCOPED_PRD_V2", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("SCOPED_V2_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE curve_scoped_prd_observation, curve_scoped_prd_readiness, "
            "curve_scoped_prd_subject, curve_scoped_prd_decision, curve_scoped_prd_accepted_command, "
            "curve_operation, curve_domain_event, curve_idempotency_record IN ACCESS EXCLUSIVE MODE"
        )
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_scoped_prd_observation WHERE "
            "payload->>'schema_version'='curve.scoped-prd/v2-candidate') OR EXISTS(SELECT 1 FROM "
            "curve_scoped_prd_readiness WHERE "
            "payload->>'schema_version'='curve.scoped-prd/v2-candidate') OR EXISTS(SELECT 1 FROM "
            "curve_scoped_prd_subject WHERE "
            "payload->>'schema_version'='curve.scoped-prd/v2-candidate') OR EXISTS(SELECT 1 FROM "
            "curve_scoped_prd_decision WHERE "
            "payload->>'schema_version'='curve.scoped-prd/v2-candidate') OR EXISTS(SELECT 1 FROM "
            "curve_scoped_prd_accepted_command WHERE edition='curve.scoped-prd/v2-candidate') OR "
            "EXISTS(SELECT 1 FROM curve_operation WHERE command_type LIKE 'SCOPED_PRD_V2_%') OR "
            "EXISTS(SELECT 1 FROM curve_domain_event WHERE "
            "payload->>'schema_version'='curve.scoped-prd/v2-candidate') OR EXISTS(SELECT 1 FROM "
            "curve_idempotency_record WHERE command_scope LIKE 'SCOPED_PRD_V2_%')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("SCOPED_V2_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0026_two_stage_approval_policy")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="scopedprdacceptedcommand", name="curve_sprd_cmd_edition_ck"),
        migrations.AddConstraint(
            model_name="scopedprdacceptedcommand",
            constraint=models.CheckConstraint(
                condition=models.Q(edition__in=["curve.scoped-prd/v1-candidate", "curve.scoped-prd/v2-candidate"]),
                name="curve_sprd_cmd_edition_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(SEAL_SQL, "DROP TRIGGER curve_scoped_v2_coverage_immutable ON curve_scoped_v2_coverage;"),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
