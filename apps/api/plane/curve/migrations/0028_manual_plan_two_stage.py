# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Persist two-reviewer implementation plans while retaining historical revisions."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

PREDECESSOR_DIGEST = "sha256:6385eea025cd4d579baae82b936aebeb64a8e9846c5ca7529073f9b3182263a5"
BASELINE_CATALOG_DIGEST = "sha256:c14b6221600c6e6be301cc3a36d26cbeb4b3c85e3d904f42e6cbb5e39e67f207"
CURRENT_CATALOG_DIGEST = "sha256:1e67c1cedc9bd5529f060b3b6a726291163cc2e5d8634fe2e11b3fe33c2d7866"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, expected):
    raw = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("MANUAL_V3_MIGRATION_BYTES_CHANGED")
    return raw.decode("utf-8")


FORWARD_SQL = _sql(
    "manual-plan-v3-forward.sql", "sha256:54285693d312a0e62c389d11ed68d3485046af26e688758ad75013b96acf23fb"
)
REVERSE_SQL = _sql(
    "manual-plan-v3-reverse.sql", "sha256:f495471a2f84c8bde094c7478a3615f3486ae6e9b2119af8a70c3b7faf7f8d2a"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_manual_plan_v3_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_manual_plan_v3_coverage FOR EACH STATEMENT EXECUTE FUNCTION "
    "curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0025_manual_gate2_reconstruction")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    raw = Path(__file__).with_name("0027_scoped_prd_two_stage.py").read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("MANUAL_V3_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_V3_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("MANUAL_V3_POSTGRESQL_QUALIFICATION_REQUIRED")


def install_seal(apps, schema_editor):
    require_qualification(apps, schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_manual_plan_v3_coverage(edition,catalog_digest) VALUES (%s,%s)",
            ["CURVE_MANUAL_PLAN_V3", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_V3_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE curve_manual_plan_revision_v2, curve_policy_decision, "
            "curve_domain_event, curve_idempotency_record, curve_audit_event, curve_outbox_event "
            "IN ACCESS EXCLUSIVE MODE"
        )
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_manual_plan_revision_v2 WHERE "
            "payload->>'schema_version'='curve.manual-plan-draft.revision/v3-candidate')"
            " OR EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_MANUAL_PLAN_DRAFT_POLICY_V3')"
            " OR EXISTS(SELECT 1 FROM curve_domain_event WHERE event_type='CURVE.MANUAL_PLAN_DRAFT_SAVED_V3')"
            " OR EXISTS(SELECT 1 FROM curve_audit_event WHERE action='CURVE.MANUAL_PLAN_DRAFT.SAVE_V3')"
            " OR EXISTS(SELECT 1 FROM curve_outbox_event WHERE destination='CURVE_MANUAL_PLAN_DRAFT_LOCAL_V3')"
            " OR EXISTS(SELECT 1 FROM curve_idempotency_record WHERE command_scope LIKE "
            "'CURVE.MANUAL_PLAN_DRAFT.SAVE_V3:%')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("MANUAL_V3_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0027_scoped_prd_two_stage")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0026_two_stage_approval_policy")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_MANUAL_PLAN_DRAFT_POLICY_V3",
                    policy_version=3,
                    policy_manifest_digest="sha256:84e831c2011a85b83acb8a2d414d586b0d948fbcf76fc666140459e04276f38f",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_manual_plan_v3_coverage_immutable ON curve_manual_plan_v3_coverage;"
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
