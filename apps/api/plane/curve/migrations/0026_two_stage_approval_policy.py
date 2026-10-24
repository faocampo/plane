# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Two-stage policy successor; retains all predecessor policy evidence and seals."""

import hashlib
from importlib import import_module
from pathlib import Path

from django.db import migrations, models

PREDECESSOR_DIGEST = "sha256:29f2864ec4f3670da8798ba5154d8591aecd8b7897de862e724a2901e67cbd13"
BASELINE_CATALOG_DIGEST = "sha256:4d33761d55c0f0cb509af13a729cdb6a7479c7b8ca662fc843f856bce33adb08"
CURRENT_CATALOG_DIGEST = "sha256:fb8f201929aac3461836becdecdde3b29996e52e6aea6ed48c2be6035c1083ef"
GUARD_SQL = "CREATE TABLE curve_two_stage_v2_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);\nCREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$\nDECLARE expected text; actual text;\nBEGIN\n IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage\n  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7')\n  OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v2_coverage\n  WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2' AND catalog_digest='sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;\n IF (SELECT count(*) FROM curve_manual_gate2_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_gate2_v2_coverage WHERE edition='CURVE_MANUAL_GATE2_RECONSTRUCTION_V2' AND catalog_digest='sha256:4d33761d55c0f0cb509af13a729cdb6a7479c7b8ca662fc843f856bce33adb08') THEN\n RAISE EXCEPTION 'TWO_STAGE_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;\n SELECT catalog_digest INTO expected FROM curve_two_stage_v2_coverage WHERE edition='CURVE_TWO_STAGE_REVIEW_V2';\n actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');\n IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_two_stage_v2_coverage)<>1 THEN\n  RAISE EXCEPTION 'TWO_STAGE_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;\nEND $$;"
REVERSE_GUARD_SQL = "CREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$\nDECLARE expected text; actual text;\nBEGIN\n IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage\n  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7')\n  OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v2_coverage\n  WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2' AND catalog_digest='sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;\n SELECT catalog_digest INTO expected FROM curve_manual_gate2_v2_coverage WHERE edition='CURVE_MANUAL_GATE2_RECONSTRUCTION_V2';\n actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');\n IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_gate2_v2_coverage)<>1 THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;\nEND $$;\nDROP TABLE curve_two_stage_v2_coverage;"
SEAL_SQL = "CREATE TRIGGER curve_two_stage_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_two_stage_v2_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"


def _catalog(cursor):
    return import_module("plane.curve.migrations.0025_manual_gate2_reconstruction")._catalog(cursor)


def verify_predecessor(apps, schema_editor):
    predecessor = Path(__file__).with_name("0025_manual_gate2_reconstruction.py")
    if "sha256:" + hashlib.sha256(predecessor.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("TWO_STAGE_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("TWO_STAGE_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("TWO_STAGE_POSTGRESQL_QUALIFICATION_REQUIRED")


def install_seal(apps, schema_editor):
    require_qualification(apps, schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_two_stage_v2_coverage(edition,catalog_digest) VALUES (%s,%s)",
            ["CURVE_TWO_STAGE_REVIEW_V2", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("TWO_STAGE_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("LOCK TABLE curve_policy_decision, curve_initiative IN ACCESS EXCLUSIVE MODE")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key IN ('CURVE_INITIATIVE_POLICY','CURVE_PRD_POLICY') AND policy_version=2) OR EXISTS(SELECT 1 FROM curve_initiative WHERE schema_version='1.2')"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("TWO_STAGE_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0025_manual_gate2_reconstruction")]
    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    policy_key="CURVE_PROJECT_ASSOCIATION_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:0ea402f3db6a7fb0743a79a45644d79235a685781ad844d3c42230da2c548691",
                )
                | models.Q(
                    policy_key="CURVE_SCOPE_PROPOSAL_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:778bdbd6fb82f51482d791d22ae6cf884a8906e91613b07cdafc6b429d24e266",
                )
                | models.Q(
                    policy_key="CURVE_SCOPE_REOPENING_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:598e492b7dc23369eaf3029d7e208b4fd338d03d3e3388fcb10305e9c02b0094",
                )
                | models.Q(policy_key="CURVE_CORE_POLICY", policy_version__in=[1, 2])
                | models.Q(policy_key="CURVE_PRODUCT_POLICY", policy_version=1)
                | models.Q(policy_key="CURVE_INITIATIVE_POLICY", policy_version=1)
                | models.Q(
                    policy_key="CURVE_INITIATIVE_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:6172fa892cd46d0a869761d22f364e27a2bd019b8adf814b59e5df6a4a7f13cd",
                )
                | models.Q(
                    policy_key="CURVE_PRD_POLICY",
                    policy_version=2,
                    policy_manifest_digest="sha256:aa31f1fb698cdd806032c96f07631cfc03dc68011433ddcbc133cf11d0535e40",
                )
                | models.Q(
                    policy_key="CURVE_PRD_POLICY",
                    policy_version=1,
                    policy_manifest_digest="sha256:ad38408f0e4450c615025debdf3361965f3a7361ad392aaf9aeb4219b910cb4c",
                )
                | models.Q(
                    policy_key="CURVE_MANUAL_PLAN_DRAFT_POLICY_V2",
                    policy_version=2,
                    policy_manifest_digest="sha256:cd960f017b8209b5e4a26a624cfb3549577f946c5a9682c593dec5908d6ab2f0",
                )
                | models.Q(
                    policy_key="CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2",
                    policy_version=2,
                    policy_manifest_digest="sha256:b77e1c16465b9ebdea65ffa37915bee9239a616f667a72f8e6ad978df8833514",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(GUARD_SQL, REVERSE_GUARD_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(SEAL_SQL, "DROP TRIGGER curve_two_stage_coverage_immutable ON curve_two_stage_v2_coverage;"),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
