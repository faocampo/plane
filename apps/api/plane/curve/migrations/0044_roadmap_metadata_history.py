# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Add metadata history types without rewriting retained history or prior seals."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

CURRENT_CATALOG_DIGEST = "sha256:01e1603846bd63784c524007ad530d64f9fc5d251081411eb10c959288bc2cca"
BASELINE_CATALOG_DIGEST = "sha256:f55186f9b065cf1d5685abdc4e1f93921d9789417b12723f75743c4e14edcb0e"
PREDECESSOR_DIGEST = "sha256:2f7be120d042942ae15a8f6f6498c26adeef20879334b17e2bee5064cf60a7cf"
ROOT = Path(__file__).resolve().parents[1] / "roadmap_domain"
HISTORY_TYPES = [
    "PROGRESS_CHANGED",
    "MILESTONE_MOVED",
    "PRIORITY_CHANGED",
    "HEALTH_CHANGED",
    "CONFIDENCE_CHANGED",
    "SCHEDULE_CHANGED",
]


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("ROADMAP_METADATA_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "metadata-coverage-forward.sql", "sha256:03099469c936faf944e81d03d1f7a843ba70a78400ede3deea583df4c088ea14"
)
REVERSE_SQL = _sql(
    "metadata-coverage-reverse.sql", "sha256:2c0cb4b3f5cf451b87b76e81959cddd635d0a2b3c84e72726ef03e71c600d3aa"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_roadmap_metadata_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_roadmap_metadata_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0042_local_new_work_review")._catalog(cursor)


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ROADMAP_METADATA_POSTGRESQL_QUALIFICATION_REQUIRED")


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0043_roadmap_domain.py")
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ROADMAP_METADATA_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_METADATA_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_roadmap_metadata_coverage VALUES (%s,%s)",
            ["CURVE_ROADMAP_METADATA_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_METADATA_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_compatible_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_roadmap_item_history IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_roadmap_item_history "
            "WHERE change_type NOT IN ('PROGRESS_CHANGED','MILESTONE_MOVED'))"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("ROADMAP_METADATA_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0043_roadmap_domain")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, verify_predecessor),
        migrations.RemoveConstraint(model_name="roadmapitemhistory", name="curve_rihist_type_ck"),
        migrations.AddConstraint(
            model_name="roadmapitemhistory",
            constraint=models.CheckConstraint(
                condition=models.Q(change_type__in=HISTORY_TYPES), name="curve_rihist_type_ck"
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_roadmap_metadata_coverage_immutable ON curve_roadmap_metadata_coverage;"
        ),
        migrations.RunPython(verify_successor, require_compatible_reverse),
    ]
