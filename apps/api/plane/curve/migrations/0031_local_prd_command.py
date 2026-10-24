# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Add exact local-upload policy identity and atomic command coverage."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

PREDECESSOR_DIGEST = "sha256:eaefcf64e22b58e9d5bffb6c614ed76fc34b80030801b34aef6c291ad2d175b0"
BASELINE_CATALOG_DIGEST = "sha256:493f45a0eadfd45263212043ec835fd996ac1968ad2bdeb6e25d23b0657590d3"
CURRENT_CATALOG_DIGEST = "sha256:5a0d96f6556657552da753e3f81d79004c0b84622aad7f89789f1a7fa7e1202d"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-prd-command-forward.sql", "sha256:89bc70a49cf47e175c9ffb3d53cb8d58bb4e00d9328970b43d1db231d7625e4c"
)
REVERSE_SQL = _sql(
    "local-prd-command-reverse.sql", "sha256:fa12297977a10f742a4b65f112b5a560d768c0170bc59b83eb8e4ed7bd720eb6"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_prd_command_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_prd_command_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0030_local_prd_source")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0030_local_prd_source.py")
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("LOCAL_PRD_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("LOCAL_PRD_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("LOCAL_PRD_POSTGRESQL_QUALIFICATION_REQUIRED")


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_local_prd_command_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_PRD_COMMAND_V1", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("LOCAL_PRD_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE curve_policy_decision, curve_audit_event, curve_domain_event, "
            "curve_outbox_event, curve_idempotency_record IN ACCESS EXCLUSIVE MODE"
        )
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_LOCAL_PRD_POLICY')"
            " OR EXISTS(SELECT 1 FROM curve_audit_event WHERE action LIKE 'CURVE.LOCAL_PRD.%')"
            " OR EXISTS(SELECT 1 FROM curve_domain_event WHERE event_type='CURVE.LOCAL_PRD.UPLOADED_V1')"
            " OR EXISTS(SELECT 1 FROM curve_idempotency_record WHERE command_scope LIKE 'CURVE.LOCAL_PRD.UPLOAD:%')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_PRD_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0030_local_prd_source")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0029_technical_review_two_stage")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_LOCAL_PRD_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:bfded3fd13b5dd90bb45aa7fc3681b9836b0adf63c7b64d6f7838e8d14ee9c30",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL, "DROP TRIGGER curve_local_prd_command_coverage_immutable ON curve_local_prd_command_coverage;"
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
