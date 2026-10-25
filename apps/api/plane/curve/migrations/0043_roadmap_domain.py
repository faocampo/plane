# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import hashlib
from importlib import import_module
from pathlib import Path
import django.db.models.constraints
import django.db.models.expressions
import uuid
from django.db import migrations, models


# Catalog measured with native PostgreSQL 15.7; runtime requires its exact successor proof.
CURRENT_CATALOG_DIGEST = "sha256:f55186f9b065cf1d5685abdc4e1f93921d9789417b12723f75743c4e14edcb0e"
BASELINE_CATALOG_DIGEST = "sha256:cdece150a736e7643602f0c1f1ee2492bf43721b1a879171383d80d9a5be54a9"
PREDECESSOR_DIGEST = "sha256:257ba16d2a65f0dddfa443e2b0ff599d6e510dc14f77119bb44c4c0c07c9719a"
ROOT = Path(__file__).resolve().parents[1] / "roadmap_domain"


def _sql(name, digest):
    value = (ROOT / name).read_bytes()
    if "sha256:" + hashlib.sha256(value).hexdigest() != digest:
        raise RuntimeError("ROADMAP_MIGRATION_BYTES_CHANGED")
    return value.decode()


FORWARD_SQL = _sql("relationships-forward.sql", "sha256:228a3f52922831ffb8375e156140804397b49f544ef176af99afa13062134788")
REVERSE_SQL = _sql("relationships-reverse.sql", "sha256:5e9003336641b34db0bae357da6f8a1389a7c7a67fb6508082929cb519cc3df1")


COVERAGE_FORWARD_SQL = _sql("coverage-forward.sql", "sha256:c1750f8c3019a3bc1a09f196ed67bd874a8d0398e23a7374200aa998fd4dee47")
COVERAGE_REVERSE_SQL = _sql("coverage-reverse.sql", "sha256:7c5edbc8441020af9e81230d3a19d7e6e24be472fa7ebd427cd4f73d22c4a967")
SEAL_SQL = (
    "CREATE TRIGGER curve_roadmap_domain_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR "
    "TRUNCATE ON curve_roadmap_domain_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"
)


def install_seal(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("INSERT INTO curve_roadmap_domain_coverage VALUES (%s,%s)",
                       ["CURVE_ROADMAP_DOMAIN_V1", CURRENT_CATALOG_DIGEST])


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        previous = import_module("plane.curve.migrations.0042_local_new_work_review")
        if previous._catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_qualification(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("ROADMAP_POSTGRESQL_QUALIFICATION_REQUIRED")


def verify_predecessor(apps, schema_editor):
    path = Path(__file__).with_name("0042_local_new_work_review.py")
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != PREDECESSOR_DIGEST:
        raise RuntimeError("ROADMAP_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        previous = import_module("plane.curve.migrations.0042_local_new_work_review")
        if previous._catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("ROADMAP_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        tables = ("curve_roadmap", "curve_milestone", "curve_feature", "curve_roadmap_item", "curve_roadmap_item_history")
        cursor.execute("LOCK TABLE " + ", ".join(tables) + " IN ACCESS EXCLUSIVE MODE")
        for table in tables:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM " + table + ")")
            if cursor.fetchone()[0]:
                raise RuntimeError("ROADMAP_RETAINED_EVIDENCE_PREVENTS_REVERSE")


class Migration(migrations.Migration):

    atomic = True

    dependencies = [
        ('curve', '0042_local_new_work_review'),
    ]

    operations = [
        migrations.RunPython(require_qualification, migrations.RunPython.noop),
        migrations.RunPython(verify_predecessor, migrations.RunPython.noop),
        migrations.CreateModel(
            name='Feature',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('schema_version', models.CharField(default='1.0', editable=False, max_length=20)),
                ('workspace_id', models.UUIDField(editable=False)),
                ('product_id', models.UUIDField(editable=False)),
                ('version', models.PositiveBigIntegerField(default=1, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.JSONField(editable=False)),
                ('updated_by', models.JSONField(editable=False)),
                ('tombstoned_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('tombstoned_by', models.JSONField(blank=True, editable=False, null=True)),
                ('tombstone_reason', models.TextField(blank=True, editable=False, null=True)),
                ('name', models.CharField(max_length=255)),
                ('description', models.JSONField(blank=True, null=True)),
            ],
            options={
                'db_table': 'curve_feature',
            },
        ),
        migrations.CreateModel(
            name='Milestone',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('schema_version', models.CharField(default='1.0', editable=False, max_length=20)),
                ('workspace_id', models.UUIDField(editable=False)),
                ('product_id', models.UUIDField(editable=False)),
                ('version', models.PositiveBigIntegerField(default=1, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.JSONField(editable=False)),
                ('updated_by', models.JSONField(editable=False)),
                ('tombstoned_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('tombstoned_by', models.JSONField(blank=True, editable=False, null=True)),
                ('tombstone_reason', models.TextField(blank=True, editable=False, null=True)),
                ('roadmap_id', models.UUIDField(editable=False)),
                ('name', models.CharField(max_length=255)),
                ('type', models.CharField(choices=[('RELEASE_VERSION', 'Release or version'), ('CALENDAR_PERIOD', 'Calendar period'), ('PRODUCT_OUTCOME', 'Product outcome'), ('INTERNAL_DEVELOPMENT_PHASE', 'Internal development phase')], max_length=32)),
                ('position', models.PositiveBigIntegerField()),
                ('target_start', models.DateField(blank=True, null=True)),
                ('target_end', models.DateField(blank=True, null=True)),
            ],
            options={
                'db_table': 'curve_milestone',
            },
        ),
        migrations.CreateModel(
            name='Roadmap',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('schema_version', models.CharField(default='1.0', editable=False, max_length=20)),
                ('workspace_id', models.UUIDField(editable=False)),
                ('product_id', models.UUIDField(editable=False)),
                ('version', models.PositiveBigIntegerField(default=1, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.JSONField(editable=False)),
                ('updated_by', models.JSONField(editable=False)),
                ('tombstoned_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('tombstoned_by', models.JSONField(blank=True, editable=False, null=True)),
                ('tombstone_reason', models.TextField(blank=True, editable=False, null=True)),
                ('name', models.CharField(max_length=255)),
                ('owner_user_id', models.UUIDField()),
                ('horizon_start', models.DateField(blank=True, null=True)),
                ('horizon_end', models.DateField(blank=True, null=True)),
            ],
            options={
                'db_table': 'curve_roadmap',
            },
        ),
        migrations.CreateModel(
            name='RoadmapItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('schema_version', models.CharField(default='1.0', editable=False, max_length=20)),
                ('workspace_id', models.UUIDField(editable=False)),
                ('product_id', models.UUIDField(editable=False)),
                ('version', models.PositiveBigIntegerField(default=1, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.JSONField(editable=False)),
                ('updated_by', models.JSONField(editable=False)),
                ('tombstoned_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('tombstoned_by', models.JSONField(blank=True, editable=False, null=True)),
                ('tombstone_reason', models.TextField(blank=True, editable=False, null=True)),
                ('roadmap_id', models.UUIDField(editable=False)),
                ('milestone_id', models.UUIDField()),
                ('feature_id', models.UUIDField(editable=False)),
                ('defining_initiative_id', models.UUIDField(editable=False)),
                ('owner_user_id', models.UUIDField()),
                ('scope_body', models.JSONField()),
                ('status', models.CharField(choices=[('PROPOSED', 'Proposed'), ('COMMITTED', 'Committed'), ('IN_PROGRESS', 'In progress'), ('PAUSED', 'Paused'), ('DELIVERED', 'Delivered'), ('CANCELLED', 'Cancelled')], default='PROPOSED', max_length=16)),
                ('priority', models.CharField(max_length=8)),
                ('confidence', models.CharField(max_length=6)),
                ('health', models.CharField(max_length=9)),
                ('planned_start', models.DateField(blank=True, null=True)),
                ('planned_end', models.DateField(blank=True, null=True)),
                ('declared_progress', models.PositiveSmallIntegerField(default=0)),
                ('progress_note', models.TextField(default='')),
                ('approved_prd_version_id', models.UUIDField(blank=True, null=True)),
            ],
            options={
                'db_table': 'curve_roadmap_item',
            },
        ),
        migrations.CreateModel(
            name='RoadmapItemHistory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('workspace_id', models.UUIDField(editable=False)),
                ('product_id', models.UUIDField(editable=False)),
                ('roadmap_item_id', models.UUIDField(editable=False)),
                ('sequence', models.PositiveBigIntegerField(editable=False)),
                ('recorded_at', models.DateTimeField(editable=False)),
                ('recorded_by', models.JSONField(editable=False)),
                ('change_type', models.CharField(editable=False, max_length=32)),
                ('before_version', models.PositiveBigIntegerField(editable=False)),
                ('after_version', models.PositiveBigIntegerField(editable=False)),
                ('payload', models.JSONField(editable=False)),
            ],
            options={
                'db_table': 'curve_roadmap_item_history',
            },
        ),
        migrations.AddConstraint(
            model_name='initiative',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'id', 'roadmap_item_id'), name='curve_init_roadmap_pair_uq'),
        ),
        migrations.AddConstraint(
            model_name='feature',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'id'), name='curve_feature_scope_uq'),
        ),
        migrations.AddConstraint(
            model_name='feature',
            constraint=models.CheckConstraint(condition=models.Q(('version__gte', 1)), name='curve_feature_version_ck'),
        ),
        migrations.AddConstraint(
            model_name='feature',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('tombstone_reason__isnull', True), ('tombstoned_at__isnull', True), ('tombstoned_by__isnull', True)), models.Q(('tombstone_reason__isnull', False), ('tombstone_reason__regex', '\\S'), ('tombstoned_at__isnull', False), ('tombstoned_by__isnull', False)), _connector='OR'), name='curve_feature_tombstone_ck'),
        ),
        migrations.AddConstraint(
            model_name='feature',
            constraint=models.CheckConstraint(condition=models.Q(('name__regex', '\\S')), name='curve_feature_name_ck'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'id'), name='curve_mstone_scope_uq'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.CheckConstraint(condition=models.Q(('version__gte', 1)), name='curve_mstone_version_ck'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('tombstone_reason__isnull', True), ('tombstoned_at__isnull', True), ('tombstoned_by__isnull', True)), models.Q(('tombstone_reason__isnull', False), ('tombstone_reason__regex', '\\S'), ('tombstoned_at__isnull', False), ('tombstoned_by__isnull', False)), _connector='OR'), name='curve_mstone_tombstone_ck'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'roadmap_id', 'id'), name='curve_mstone_rmap_scope_uq'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.UniqueConstraint(deferrable=django.db.models.constraints.Deferrable['DEFERRED'], fields=('workspace_id', 'roadmap_id', 'position'), name='curve_mstone_position_uq'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.CheckConstraint(condition=models.Q(('name__regex', '\\S')), name='curve_mstone_name_ck'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.CheckConstraint(condition=models.Q(('type__in', ['RELEASE_VERSION', 'CALENDAR_PERIOD', 'PRODUCT_OUTCOME', 'INTERNAL_DEVELOPMENT_PHASE'])), name='curve_mstone_type_ck'),
        ),
        migrations.AddConstraint(
            model_name='milestone',
            constraint=models.CheckConstraint(condition=models.Q(('target_start__isnull', True), ('target_end__isnull', True), ('target_start__lte', models.F('target_end')), _connector='OR'), name='curve_mstone_target_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmap',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'id'), name='curve_rmap_scope_uq'),
        ),
        migrations.AddConstraint(
            model_name='roadmap',
            constraint=models.CheckConstraint(condition=models.Q(('version__gte', 1)), name='curve_rmap_version_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmap',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('tombstone_reason__isnull', True), ('tombstoned_at__isnull', True), ('tombstoned_by__isnull', True)), models.Q(('tombstone_reason__isnull', False), ('tombstone_reason__regex', '\\S'), ('tombstoned_at__isnull', False), ('tombstoned_by__isnull', False)), _connector='OR'), name='curve_rmap_tombstone_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmap',
            constraint=models.CheckConstraint(condition=models.Q(('name__regex', '\\S')), name='curve_rmap_name_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmap',
            constraint=models.CheckConstraint(condition=models.Q(('horizon_start__isnull', True), ('horizon_end__isnull', True), ('horizon_start__lte', models.F('horizon_end')), _connector='OR'), name='curve_rmap_horizon_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'id'), name='curve_ritem_scope_uq'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(('version__gte', 1)), name='curve_ritem_version_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('tombstone_reason__isnull', True), ('tombstoned_at__isnull', True), ('tombstoned_by__isnull', True)), models.Q(('tombstone_reason__isnull', False), ('tombstone_reason__regex', '\\S'), ('tombstoned_at__isnull', False), ('tombstoned_by__isnull', False)), _connector='OR'), name='curve_ritem_tombstone_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'product_id', 'defining_initiative_id', 'id'), name='curve_ritem_pair_uq'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'defining_initiative_id'), name='curve_ritem_initiative_uq'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'milestone_id', 'feature_id'), name='curve_ritem_placement_uq'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(('status__in', ['PROPOSED', 'COMMITTED', 'IN_PROGRESS', 'PAUSED', 'DELIVERED', 'CANCELLED'])), name='curve_ritem_status_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(('priority__in', ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'])), name='curve_ritem_priority_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(('confidence__in', ['HIGH', 'MEDIUM', 'LOW'])), name='curve_ritem_confidence_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(('health__in', ['ON_TRACK', 'AT_RISK', 'OFF_TRACK', 'UNKNOWN'])), name='curve_ritem_health_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(('declared_progress__gte', 0), ('declared_progress__lte', 100)), name='curve_ritem_progress_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('planned_end__isnull', True), ('planned_start__isnull', True), ('status', 'PROPOSED')), models.Q(('planned_end__isnull', False), ('planned_start__isnull', False), ('planned_start__lte', models.F('planned_end'))), _connector='OR'), name='curve_ritem_schedule_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('status', 'COMMITTED'), _negated=True), ('approved_prd_version_id__isnull', False), _connector='OR'), name='curve_ritem_prd_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitemhistory',
            constraint=models.UniqueConstraint(fields=('workspace_id', 'roadmap_item_id', 'sequence'), name='curve_rihist_sequence_uq'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitemhistory',
            constraint=models.CheckConstraint(condition=models.Q(('sequence__gte', 1)), name='curve_rihist_sequence_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitemhistory',
            constraint=models.CheckConstraint(condition=models.Q(('after_version', django.db.models.expressions.CombinedExpression(models.F('before_version'), '+', models.Value(1))), ('before_version__gte', 1)), name='curve_rihist_version_ck'),
        ),
        migrations.AddConstraint(
            model_name='roadmapitemhistory',
            constraint=models.CheckConstraint(condition=models.Q(('change_type__in', ['PROGRESS_CHANGED', 'MILESTONE_MOVED'])), name='curve_rihist_type_ck'),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunSQL(COVERAGE_FORWARD_SQL, COVERAGE_REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(SEAL_SQL, "DROP TRIGGER curve_roadmap_domain_coverage_immutable ON curve_roadmap_domain_coverage;"),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
