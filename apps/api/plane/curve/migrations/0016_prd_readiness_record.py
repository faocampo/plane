# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


# Frozen migration vocabulary; later profiles require an additive migration.
PRD_SECTIONS = (
    "executive_summary problem_context goals non_goals personas workflow requirements gates integrations "
    "data_security quality rollout kpis acceptance risks assumptions open_questions"
).split()
BRIEF_SECTIONS = (
    "problem affected_users desired_outcomes non_goals constraints assumptions contradictions blockers unknowns".split()
)
REASONS = [
    f"{prefix}_SECTION_{mode}:{section}"
    for prefix, sections in (("PRD", PRD_SECTIONS), ("IDEA_BRIEF", BRIEF_SECTIONS))
    for mode in ("MISSING", "EMPTY", "DUPLICATE")
    for section in sections
] + [
    "PRD_REQUIREMENT_ID_REQUIRED",
    "PRD_REQUIREMENT_DUPLICATE",
    "PRD_REQUIREMENT_EMPTY",
    "PRD_ACCEPTANCE_ID_REQUIRED",
    "PRD_ACCEPTANCE_DUPLICATE",
    "PRD_ACCEPTANCE_EMPTY",
    "PRD_ACCEPTANCE_TRACE_REQUIRED",
    "PRD_ACCEPTANCE_UNKNOWN_REQUIREMENT",
    "PRD_REQUIREMENT_UNCOVERED",
    "READINESS_INVENTORY_STALE",
    "READINESS_INVENTORY_INVALID",
    "BLOCKERS_UNRESOLVED",
    "ASSUMPTION_PLAN_REQUIRED",
]
REASON_SQL = ",".join("'" + reason + "'" for reason in REASONS)

GUARDS = """
ALTER TABLE curve_prd_readiness_record ADD CONSTRAINT curve_readiness_init_fk
 FOREIGN KEY (workspace_id, initiative_id) REFERENCES curve_initiative(workspace_id, id);
ALTER TABLE curve_prd_readiness_record ADD CONSTRAINT curve_readiness_binding_fk
 FOREIGN KEY (workspace_id, binding_id) REFERENCES curve_external_document_binding(workspace_id, id);
CREATE TRIGGER curve_readiness_immutable BEFORE UPDATE OR DELETE ON curve_prd_readiness_record
 FOR EACH ROW EXECUTE FUNCTION curve_prd_immutable();
CREATE FUNCTION curve_readiness_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE init curve_initiative%ROWTYPE; binding curve_external_document_binding%ROWTYPE;
 policy curve_policy_decision%ROWTYPE; p jsonb := NEW.payload; key text; checked timestamptz;
 fields text[] := ARRAY['id','workspace_id','initiative_id','initiative_version','prd_binding_id',
  'provider_file_id','provider_version','content_digest','idea_brief_version_id','idea_brief_digest',
  'evidence_snapshot_id','inventory_digest','checked_at','schema_version','profile_digest','status','reasons'];
BEGIN
 IF jsonb_typeof(p) IS DISTINCT FROM 'object' OR NOT p ?& fields OR p-fields <> '{}'::jsonb THEN
  RAISE EXCEPTION 'READINESS_RECORD_SHAPE_INVALID' USING ERRCODE='23514';
 END IF;
 FOREACH key IN ARRAY fields LOOP
  IF key NOT IN ('initiative_version','reasons') AND jsonb_typeof(p->key) IS DISTINCT FROM 'string' THEN
   RAISE EXCEPTION 'READINESS_RECORD_SHAPE_INVALID' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF jsonb_typeof(p->'initiative_version') IS DISTINCT FROM 'number'
  OR (p->>'initiative_version') !~ '^[1-9][0-9]*$'
  OR (p->>'initiative_version')::numeric > 9007199254740991
  OR p->>'schema_version' <> 'curve.prd-readiness/v1-candidate'
  OR p->>'profile_digest' <> 'sha256:893116c9ad148748d096e07017002bf405a0bc892b423e59675458fafb6789dc'
  OR p->>'status' NOT IN ('READY','BLOCKED') THEN
  RAISE EXCEPTION 'READINESS_RECORD_PROFILE_INVALID' USING ERRCODE='23514';
 END IF;
 FOREACH key IN ARRAY ARRAY['id','workspace_id','initiative_id','prd_binding_id',
  'idea_brief_version_id','evidence_snapshot_id'] LOOP
  IF (p->>key) !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
   RAISE EXCEPTION 'READINESS_RECORD_ID_INVALID' USING ERRCODE='23514';
  END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['content_digest','idea_brief_digest','inventory_digest'] LOOP
  IF (p->>key) !~ '^sha256:[0-9a-f]{64}$' THEN
   RAISE EXCEPTION 'READINESS_RECORD_DIGEST_INVALID' USING ERRCODE='23514';
  END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['provider_file_id','provider_version'] LOOP
  IF length(p->>key) > 512 OR (p->>key) !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]*$' THEN
   RAISE EXCEPTION 'READINESS_RECORD_SOURCE_INVALID' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF jsonb_typeof(p->'reasons') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'READINESS_RECORD_REASONS_INVALID' USING ERRCODE='23514';
 END IF;
 IF jsonb_array_length(p->'reasons') > 91
  OR (p->>'status'='READY') IS DISTINCT FROM (jsonb_array_length(p->'reasons')=0)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'reasons') reason WHERE jsonb_typeof(reason) <> 'string')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(p->'reasons') reason WHERE NOT reason = ANY(ARRAY[__REASONS__]))
  OR (SELECT count(*) <> count(DISTINCT reason) FROM jsonb_array_elements_text(p->'reasons') reason) THEN
  RAISE EXCEPTION 'READINESS_RECORD_REASONS_INVALID' USING ERRCODE='23514';
 END IF;
 IF p->>'id' <> NEW.id::text OR p->>'workspace_id' <> NEW.workspace_id::text
  OR p->>'initiative_id' <> NEW.initiative_id::text OR p->>'prd_binding_id' <> NEW.binding_id::text THEN
  RAISE EXCEPTION 'READINESS_RECORD_SCOPE_INVALID' USING ERRCODE='23514';
 END IF;
 SELECT * INTO init FROM curve_initiative WHERE workspace_id=NEW.workspace_id AND id=NEW.initiative_id FOR UPDATE;
 IF NOT FOUND OR init.version <> (p->>'initiative_version')::bigint OR init.state NOT IN ('ALIGNING','PRD_REVIEW') THEN
  RAISE EXCEPTION 'READINESS_RECORD_VERSION_CONFLICT' USING ERRCODE='23514';
 END IF;
 SELECT * INTO binding FROM curve_external_document_binding WHERE workspace_id=NEW.workspace_id AND id=NEW.binding_id;
 IF NOT FOUND OR binding.initiative_id <> NEW.initiative_id OR binding.provider_file_id <> p->>'provider_file_id' THEN
  RAISE EXCEPTION 'READINESS_RECORD_BINDING_MISMATCH' USING ERRCODE='23514';
 END IF;
 SELECT * INTO policy FROM curve_policy_decision WHERE workspace_id=NEW.workspace_id AND id=NEW.policy_decision_id;
 IF NOT FOUND OR policy.action <> 'CURVE.PRD.SUBMIT' OR policy.effect <> 'ALLOW'
  OR policy.policy_key <> 'CURVE_PRD_POLICY'
  OR policy.resource_type <> 'INITIATIVE' OR policy.resource_id <> NEW.initiative_id
  OR policy.resource_version IS DISTINCT FROM init.version OR policy.subject->>'actor_type' IS DISTINCT FROM 'HUMAN'
  OR policy.effective_principal IS DISTINCT FROM policy.subject THEN
  RAISE EXCEPTION 'READINESS_RECORD_POLICY_MISMATCH' USING ERRCODE='23514';
 END IF;
 IF (p->>'checked_at') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,3})?Z$' THEN
  RAISE EXCEPTION 'READINESS_RECORD_TIME_INVALID' USING ERRCODE='23514';
 END IF;
 checked := (p->>'checked_at')::timestamptz;
 IF NOT isfinite(checked) OR NOT isfinite(NEW.recorded_at) OR checked < init.created_at
  OR to_char(checked AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') <> left(p->>'checked_at',19)
  OR checked > NEW.recorded_at OR NEW.recorded_at > clock_timestamp() THEN
  RAISE EXCEPTION 'READINESS_RECORD_TIME_INVALID' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_readiness_guard BEFORE INSERT ON curve_prd_readiness_record
 FOR EACH ROW EXECUTE FUNCTION curve_readiness_guard();
""".replace("__REASONS__", REASON_SQL)

REVERSE_GUARDS = """
LOCK TABLE curve_prd_readiness_record IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM curve_prd_readiness_record) THEN
  RAISE EXCEPTION 'Retained readiness records require a preservation migration';
 END IF;
END $$;
DROP TRIGGER curve_readiness_guard ON curve_prd_readiness_record;
DROP FUNCTION curve_readiness_guard();
DROP TRIGGER curve_readiness_immutable ON curve_prd_readiness_record;
ALTER TABLE curve_prd_readiness_record DROP CONSTRAINT curve_readiness_binding_fk;
ALTER TABLE curve_prd_readiness_record DROP CONSTRAINT curve_readiness_init_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("curve", "0015_prd_accepted_command")]
    operations = [
        migrations.CreateModel(
            name="PrdReadinessRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("payload", models.JSONField(editable=False)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "binding",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.externaldocumentbinding"),
                ),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "policy_decision",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.policydecision"),
                ),
            ],
            options={
                "db_table": "curve_prd_readiness_record",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "initiative", "id"), name="curve_readiness_scope_uq"
                    )
                ],
            },
        ),
        migrations.RunSQL(GUARDS, REVERSE_GUARDS),
    ]
