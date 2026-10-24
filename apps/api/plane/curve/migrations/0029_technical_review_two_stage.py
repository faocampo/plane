# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Add two-stage Technical decisions without replacing historical migrations."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

PREDECESSOR_DIGEST = "sha256:550670929184f67dbd32d6aeb41ef54b1dc8f58c5f0a3dc5a67527a5ac0a25ea"
BASELINE_CATALOG_DIGEST = "sha256:1e67c1cedc9bd5529f060b3b6a726291163cc2e5d8634fe2e11b3fe33c2d7866"
CURRENT_CATALOG_DIGEST = "sha256:8b846ec66b306ffc5c95b52818c5bb03acadadde679df7b678da4f3afedc0e64"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, expected):
    raw = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("TECHNICAL_V3_MIGRATION_BYTES_CHANGED")
    return raw.decode("utf-8")


FORWARD_SQL = _sql(
    "technical-review-v3-forward.sql", "sha256:8d99b22e37b57add9ff7fbb4c8fdb85e946fe0522f12595cc2f0899c92251248"
)
REVERSE_SQL = _sql(
    "technical-review-v3-reverse.sql", "sha256:59856694bc099989dd7c557c2d7012373af714e9316009267fee3603d7d6cf18"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_manual_gate2_v3_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_manual_gate2_v3_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0025_manual_gate2_reconstruction")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    raw = Path(__file__).with_name("0028_manual_plan_two_stage.py").read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("TECHNICAL_V3_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("TECHNICAL_V3_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("TECHNICAL_V3_POSTGRESQL_QUALIFICATION_REQUIRED")


def install_seal(apps, schema_editor):
    require_qualification(apps, schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_manual_gate2_v3_coverage(edition,catalog_digest) VALUES (%s,%s)",
            ["CURVE_MANUAL_GATE2_V3", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("TECHNICAL_V3_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE curve_manual_gate2_record_v2, curve_manual_gate2_control_v2, "
            "curve_manual_task_claim_v2, curve_manual_task_claim_history_v2, curve_policy_decision, "
            "curve_domain_event, curve_idempotency_record, curve_audit_event, curve_outbox_event "
            "IN ACCESS EXCLUSIVE MODE"
        )
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_manual_gate2_record_v2 WHERE "
            "payload->>'schema_version'='curve.manual-gate2.record/v3-candidate')"
            " OR EXISTS(SELECT 1 FROM curve_policy_decision WHERE "
            "policy_key='CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V3')"
            " OR EXISTS(SELECT 1 FROM curve_domain_event WHERE event_type='CURVE.MANUAL_GATE2_RECORDED_V3')"
            " OR EXISTS(SELECT 1 FROM curve_audit_event WHERE action LIKE 'CURVE.MANUAL_GATE2.%_V3')"
            " OR EXISTS(SELECT 1 FROM curve_outbox_event WHERE destination='curve-local-manual-gate2-v3')"
            " OR EXISTS(SELECT 1 FROM curve_idempotency_record WHERE command_scope LIKE 'CURVE.MANUAL_GATE2.%_V3:%')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("TECHNICAL_V3_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0028_manual_plan_two_stage")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0028_manual_plan_two_stage")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V3",
                    policy_version=3,
                    policy_manifest_digest="sha256:16d6a552f604f7b8ce4711e2b0521de7155d0542da3d8eaec7cea6f3e60c337b",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_manual_gate2_v3_coverage_immutable ON curve_manual_gate2_v3_coverage;"
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
