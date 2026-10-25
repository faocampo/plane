# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Authorize Roadmap hierarchy policy while preserving all previous identities."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:bc85b48c76b9d83462078cd09e57f9c2e27434d4bd338c42935503c55ef40c59"
BASELINE_CATALOG_DIGEST = "sha256:01e1603846bd63784c524007ad530d64f9fc5d251081411eb10c959288bc2cca"
PREDECESSOR_DIGEST = "sha256:49fcbaaf4e25677a057570b430b49f170938524d1fffffd141bf2a6dd7e85ef3"
ROOT = Path(__file__).resolve().parents[1] / "roadmap_domain"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("ROADMAP_HIERARCHY_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "command-coverage-forward.sql", "sha256:e66da781d44387cbfc2a329900651173378401731fae4ed42d03e5f91636caec"
)
REVERSE_SQL = _sql(
    "command-coverage-reverse.sql", "sha256:18c36605e4430de2ea85db161d35cf16928dbc158f9a7af9ccc692e4385cb0a0"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_roadmap_command_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_roadmap_command_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0042_local_new_work_review")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ROADMAP_HIERARCHY_POSTGRESQL_QUALIFICATION_REQUIRED")


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0044_roadmap_metadata_history.py")
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ROADMAP_HIERARCHY_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_HIERARCHY_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_roadmap_command_coverage VALUES (%s,%s)",
            ["CURVE_ROADMAP_HIERARCHY_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_HIERARCHY_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_ROADMAP_HIERARCHY_POLICY')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ROADMAP_HIERARCHY_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0044_roadmap_metadata_history")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0042_local_new_work_review")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_ROADMAP_HIERARCHY_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:c2eec4116b63c49b40d1bacad0985fedc850f243c5da1ef1b5bfa7bdaca98598",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_roadmap_command_coverage_immutable ON curve_roadmap_command_coverage;"
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
