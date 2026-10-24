# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
from django.db import migrations, models


PREDECESSOR_DIGEST = "sha256:cdef0720c30e9f7cdad41b0a4ebe24797f031ea55f9b8b87c7f1f9f74fdcc3fe"
BASELINE_CATALOG_DIGEST = "sha256:f02d946e27d8c8a78d54d21748ce82d4ecf82a109973fb805af92c1f767a174b"
CURRENT_CATALOG_DIGEST = "sha256:cdece150a736e7643602f0c1f1ee2492bf43721b1a879171383d80d9a5be54a9"
ROOT = Path(__file__).resolve().parents[1] / "two_stage_review"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("LOCAL_PRD_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql(
    "local-new-work-forward.sql", "sha256:9345718e6d7a7a27dcaa3abfdd639378436ae83229930e1de27d2fb53d53e5e6"
)
REVERSE_SQL = _sql(
    "local-new-work-reverse.sql", "sha256:be6a522aca427dd147a82b145afa0beb08c16ddaa827c0b7a1aa8db553e4fb8f"
)
SEAL_SQL = (
    "CREATE TRIGGER curve_local_new_work_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_local_new_work_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def _catalog(cursor):
    return import_module("plane.curve.migrations.0041_local_prd_reopening_command")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0041_local_prd_reopening_command.py")
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
            "INSERT INTO curve_local_new_work_coverage VALUES (%s,%s)",
            ["CURVE_LOCAL_NEW_WORK_V2", CURRENT_CATALOG_DIGEST],
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
        cursor.execute("LOCK TABLE curve_policy_decision, curve_local_prd_submission IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_local_prd_submission WHERE "
            "payload->>'schema_version'='curve.local-prd-submission/v2-candidate') OR EXISTS(SELECT 1 FROM "
            "curve_policy_decision WHERE policy_key IN ('CURVE_LOCAL_PRD_POLICY','CURVE_LOCAL_PRD_REVIEW_POLICY',"
            "'CURVE_LOCAL_PLAN_UPLOAD_POLICY','CURVE_LOCAL_PLAN_REVIEW_POLICY','CURVE_LOCAL_PRD_REOPENING_POLICY') "
            "AND policy_version=2)"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("LOCAL_REVIEW_COMMAND_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0041_local_prd_reopening_command")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=import_module("plane.curve.migrations.0041_local_prd_reopening_command")
                .Migration.operations[3]
                .constraint.condition
                | models.Q(
                    policy_key="CURVE_LOCAL_PRD_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:ca91f9a19b2203245c6a70d99305b2a6db3697af13f98c7aeaf6f648a3a97be9",
                )
                | models.Q(
                    policy_key="CURVE_LOCAL_PRD_REVIEW_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:f5a26189960ebb3a5657cb5a7857f4060f44eff3e217e598bb500273718f0c4a",
                )
                | models.Q(
                    policy_key="CURVE_LOCAL_PLAN_UPLOAD_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:5d661c02789d1ecc761adc3864ef670e868aa6cef77f0c7dc9202d64a9df9ae3",
                )
                | models.Q(
                    policy_key="CURVE_LOCAL_PLAN_REVIEW_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:e98a45e07f35cb297a6f7766b05ecea5bd67c2ad91facab2a8f4a37197194b3b",
                )
                | models.Q(
                    policy_key="CURVE_LOCAL_PRD_REOPENING_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:f2021762aef38835aa7e9807cef415293f3ee2cb79705f6a7dc9033d02eee354",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_local_new_work_coverage_immutable ON curve_local_new_work_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
