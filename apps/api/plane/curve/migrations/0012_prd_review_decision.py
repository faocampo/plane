# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import django.db.models.deletion
import uuid
from django.db import migrations, models


FORWARD_GUARDS = """
ALTER TABLE curve_prd_review_decision ADD CONSTRAINT curve_prd_decision_init_fk
 FOREIGN KEY (workspace_id, initiative_id) REFERENCES curve_initiative(workspace_id, id);
ALTER TABLE curve_prd_review_decision ADD CONSTRAINT curve_prd_decision_gate_fk
 FOREIGN KEY (workspace_id, initiative_id, gate_assignment_id)
 REFERENCES curve_gate_assignment(workspace_id, initiative_id, id);
ALTER TABLE curve_prd_review_decision ADD CONSTRAINT curve_prd_decision_checkpoint_fk
 FOREIGN KEY (workspace_id, initiative_id, checkpoint_id)
 REFERENCES curve_document_checkpoint(workspace_id, initiative_id, id);
ALTER TABLE curve_prd_review_decision ADD CONSTRAINT curve_prd_decision_version_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_version_id)
 REFERENCES curve_prd_artifact_version(workspace_id, initiative_id, id);
ALTER TABLE curve_prd_review_decision ADD CONSTRAINT curve_prd_decision_snapshot_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_version_id, evidence_snapshot_id)
 REFERENCES curve_prd_evidence_snapshot(workspace_id, initiative_id, artifact_version_id, id);

CREATE TRIGGER curve_prd_decision_immutable BEFORE UPDATE OR DELETE ON curve_prd_review_decision
 FOR EACH ROW EXECUTE FUNCTION curve_prd_immutable();

CREATE FUNCTION curve_prd_decision_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE initiative_record curve_initiative; checkpoint_record curve_document_checkpoint;
 binding_record curve_external_document_binding; artifact_record curve_prd_artifact;
 assignment_record curve_gate_assignment; gate_count integer; human_count integer;
 policy_count integer; policy_unique_count integer; policy_item jsonb;
BEGIN
 SELECT * INTO initiative_record FROM curve_initiative
  WHERE workspace_id = NEW.workspace_id AND id = NEW.initiative_id FOR UPDATE;
 IF NOT FOUND OR NEW.confirmed_risk_tier <> initiative_record.risk_tier THEN
  RAISE EXCEPTION 'PRD_REVIEW_SCOPE_OR_RISK_INVALID' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO checkpoint_record FROM curve_document_checkpoint
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id AND id = NEW.checkpoint_id;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'PRD_REVIEW_SUBJECT_MISMATCH' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO binding_record FROM curve_external_document_binding
  WHERE workspace_id = NEW.workspace_id AND id = checkpoint_record.external_document_binding_id FOR UPDATE;
 SELECT * INTO artifact_record FROM curve_prd_artifact
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id FOR UPDATE;
 IF NOT FOUND OR artifact_record.current_version_id IS DISTINCT FROM NEW.artifact_version_id OR
    EXISTS (SELECT 1 FROM curve_document_checkpoint WHERE workspace_id = NEW.workspace_id
      AND external_document_binding_id = binding_record.id AND checkpoint_number > checkpoint_record.checkpoint_number)
    OR ROW(NEW.artifact_version_id, NEW.evidence_snapshot_id, NEW.content_digest, NEW.provider_version)
       IS DISTINCT FROM ROW(checkpoint_record.artifact_version_id, checkpoint_record.evidence_snapshot_id,
                            checkpoint_record.content_digest, checkpoint_record.provider_version) THEN
  RAISE EXCEPTION 'PRD_REVIEW_SUBJECT_MISMATCH' USING ERRCODE = '23514';
 END IF;
 IF NEW.state = 'APPROVED' AND binding_record.current_provider_version <> NEW.provider_version THEN
  RAISE EXCEPTION 'PRD_REVIEW_SOURCE_CHANGED' USING ERRCODE = '23514';
 END IF;
 IF NOT isfinite(NEW.decided_at) OR NOT isfinite(NEW.provider_validation_cutoff) OR
    checkpoint_record.recorded_at > NEW.provider_validation_cutoff OR
    NEW.provider_validation_cutoff > NEW.decided_at THEN
  RAISE EXCEPTION 'PRD_REVIEW_CHRONOLOGY_INVALID' USING ERRCODE = '23514';
 END IF;
 PERFORM 1 FROM curve_gate_assignment
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id FOR SHARE;
 SELECT count(*), count(DISTINCT approver_user_id) INTO gate_count, human_count FROM curve_gate_assignment
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id
   AND valid_from <= NEW.provider_validation_cutoff AND (valid_until IS NULL OR valid_until > NEW.decided_at);
 IF gate_count <> 3 OR (NEW.confirmed_risk_tier IN ('STANDARD', 'HIGH') AND human_count <> 3) THEN
  RAISE EXCEPTION 'PRD_REVIEW_GATES_INVALID' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO assignment_record FROM curve_gate_assignment
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id AND id = NEW.gate_assignment_id;
 IF NOT FOUND OR assignment_record.gate_type <> 'PRD_APPROVAL' OR
    NOT curve_prd_closed_keys(NEW.decided_by, ARRAY['actor_type', 'actor_id']) OR
    NEW.decided_by->>'actor_type' IS DISTINCT FROM 'HUMAN' OR
    NEW.decided_by->>'actor_id' IS DISTINCT FROM assignment_record.approver_user_id::text THEN
  RAISE EXCEPTION 'PRD_REVIEW_PRODUCT_APPROVER_REQUIRED' USING ERRCODE = '23514';
 END IF;
 IF jsonb_typeof(NEW.policy_version_ids) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'PRD_REVIEW_POLICY_IDS_INVALID' USING ERRCODE = '23514';
 END IF;
 SELECT count(*), count(DISTINCT value) INTO policy_count, policy_unique_count
  FROM jsonb_array_elements(NEW.policy_version_ids);
 IF policy_count = 0 OR policy_count <> policy_unique_count THEN
  RAISE EXCEPTION 'PRD_REVIEW_POLICY_IDS_INVALID' USING ERRCODE = '23514';
 END IF;
 FOR policy_item IN SELECT value FROM jsonb_array_elements(NEW.policy_version_ids) LOOP
  IF jsonb_typeof(policy_item) <> 'string' OR
     (policy_item #>> '{}') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
   RAISE EXCEPTION 'PRD_REVIEW_POLICY_IDS_INVALID' USING ERRCODE = '23514';
  END IF;
 END LOOP;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_prd_decision_insert_guard BEFORE INSERT ON curve_prd_review_decision
 FOR EACH ROW EXECUTE FUNCTION curve_prd_decision_insert_guard();

CREATE FUNCTION curve_prd_reviewed_gates_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM curve_initiative WHERE workspace_id = OLD.workspace_id AND id = OLD.initiative_id FOR UPDATE;
 IF EXISTS (SELECT 1 FROM curve_prd_review_decision
     WHERE workspace_id = OLD.workspace_id AND initiative_id = OLD.initiative_id) THEN
  RAISE EXCEPTION 'PRD_REVIEW_GATE_HISTORY_RETAINED' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_prd_reviewed_gates_guard BEFORE UPDATE OR DELETE ON curve_gate_assignment
 FOR EACH ROW EXECUTE FUNCTION curve_prd_reviewed_gates_guard();
"""

REVERSE_GUARDS = """
LOCK TABLE curve_prd_review_decision IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM curve_prd_review_decision) THEN
  RAISE EXCEPTION 'Nonempty PRD review decisions require a preservation migration';
 END IF;
END $$;
DROP TRIGGER curve_prd_reviewed_gates_guard ON curve_gate_assignment;
DROP FUNCTION curve_prd_reviewed_gates_guard();
DROP TRIGGER curve_prd_decision_insert_guard ON curve_prd_review_decision;
DROP FUNCTION curve_prd_decision_insert_guard();
DROP TRIGGER curve_prd_decision_immutable ON curve_prd_review_decision;
ALTER TABLE curve_prd_review_decision DROP CONSTRAINT curve_prd_decision_snapshot_fk;
ALTER TABLE curve_prd_review_decision DROP CONSTRAINT curve_prd_decision_version_fk;
ALTER TABLE curve_prd_review_decision DROP CONSTRAINT curve_prd_decision_checkpoint_fk;
ALTER TABLE curve_prd_review_decision DROP CONSTRAINT curve_prd_decision_gate_fk;
ALTER TABLE curve_prd_review_decision DROP CONSTRAINT curve_prd_decision_init_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("curve", "0011_document_checkpoint"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrdReviewDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("content_digest", models.CharField(editable=False, max_length=71)),
                ("provider_version", models.CharField(editable=False, max_length=512)),
                ("access_evaluation_id", models.UUIDField(editable=False)),
                ("policy_version_ids", models.JSONField(editable=False)),
                ("confirmed_risk_tier", models.CharField(editable=False, max_length=16)),
                ("state", models.CharField(editable=False, max_length=32)),
                ("decided_by", models.JSONField(editable=False)),
                ("decided_at", models.DateTimeField(editable=False)),
                ("provider_validation_cutoff", models.DateTimeField(editable=False)),
                ("rationale_object_id", models.UUIDField(editable=False)),
                ("rationale_digest", models.CharField(editable=False, max_length=71)),
                ("rationale_size_bytes", models.PositiveIntegerField(editable=False)),
                ("rationale_access_envelope_id", models.UUIDField(editable=False)),
                ("rationale_retention_policy_version_id", models.UUIDField(editable=False)),
            ],
            options={
                "db_table": "curve_prd_review_decision",
            },
        ),
        migrations.AddConstraint(
            model_name="gateassignment",
            constraint=models.UniqueConstraint(fields=("workspace_id", "initiative", "id"), name="curve_gate_scope_uq"),
        ),
        migrations.AddField(
            model_name="prdreviewdecision",
            name="artifact_version",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.prdartifactversion"),
        ),
        migrations.AddField(
            model_name="prdreviewdecision",
            name="checkpoint",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.documentcheckpoint"),
        ),
        migrations.AddField(
            model_name="prdreviewdecision",
            name="evidence_snapshot",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.prdevidencesnapshot"),
        ),
        migrations.AddField(
            model_name="prdreviewdecision",
            name="gate_assignment",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.gateassignment"),
        ),
        migrations.AddField(
            model_name="prdreviewdecision",
            name="initiative",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative"),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "id"), name="curve_prd_decision_scope_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.UniqueConstraint(fields=("workspace_id", "checkpoint"), name="curve_prd_decision_cp_uq"),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("state__in", ["APPROVED", "CHANGES_REQUESTED", "REJECTED"])),
                name="curve_prd_decision_state_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("confirmed_risk_tier__in", ["LOW", "STANDARD", "HIGH"])),
                name="curve_prd_decision_risk_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("rationale_size_bytes__gte", 1), ("rationale_size_bytes__lte", 8000)),
                name="curve_prd_decision_size_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("content_digest__regex", "^sha256:[0-9a-f]{64}$")),
                name="curve_prd_decision_digest_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("rationale_digest__regex", "^sha256:[0-9a-f]{64}$")),
                name="curve_prd_rationale_digest_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdreviewdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider_version__regex", "^[A-Za-z0-9._~-]+$")),
                name="curve_prd_decision_source_ck",
            ),
        ),
        migrations.RunSQL(FORWARD_GUARDS, REVERSE_GUARDS),
    ]
