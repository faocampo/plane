# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations, models


FORWARD = """
ALTER TABLE curve_initiative ADD CONSTRAINT curve_init_prd_checkpoint_fk
 FOREIGN KEY (workspace_id, id, current_prd_checkpoint_id)
 REFERENCES curve_document_checkpoint(workspace_id, initiative_id, id);
ALTER TABLE curve_initiative ADD CONSTRAINT curve_init_prd_decision_fk
 FOREIGN KEY (workspace_id, id, controlling_prd_decision_id)
 REFERENCES curve_prd_review_decision(workspace_id, initiative_id, id);

CREATE FUNCTION curve_init_prd_lifecycle_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE checkpoint_record curve_document_checkpoint; decision_record curve_prd_review_decision;
 effective_state text; checkpoint_changed boolean; decision_changed boolean;
BEGIN
 effective_state := CASE WHEN NEW.state = 'PAUSED' THEN NEW.paused_from_state ELSE NEW.state END;
 IF NEW.current_prd_checkpoint_id IS NULL THEN
  IF NEW.controlling_prd_decision_id IS NOT NULL OR effective_state IN ('PRD_REVIEW', 'PLANNING') THEN
   RAISE EXCEPTION 'PRD_SUBMITTED_CHECKPOINT_REQUIRED' USING ERRCODE = '23514';
  END IF;
 ELSE
  SELECT * INTO checkpoint_record FROM curve_document_checkpoint
   WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.id AND id = NEW.current_prd_checkpoint_id;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'PRD_CURRENT_CHECKPOINT_SCOPE_INVALID' USING ERRCODE = '23514';
  END IF;
  IF effective_state = 'DRAFT' THEN
   RAISE EXCEPTION 'PRD_DRAFT_CANNOT_HAVE_SUBMISSION' USING ERRCODE = '23514';
  END IF;
  IF NEW.controlling_prd_decision_id IS NOT NULL THEN
   SELECT * INTO decision_record FROM curve_prd_review_decision
    WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.id AND id = NEW.controlling_prd_decision_id;
   IF NOT FOUND OR decision_record.checkpoint_id <> NEW.current_prd_checkpoint_id THEN
    RAISE EXCEPTION 'PRD_CONTROLLING_DECISION_SUBJECT_INVALID' USING ERRCODE = '23514';
   END IF;
  END IF;
  IF effective_state = 'PRD_REVIEW' AND NEW.controlling_prd_decision_id IS NOT NULL THEN
   RAISE EXCEPTION 'PRD_REVIEW_REQUIRES_UNDECIDED_SUBMISSION' USING ERRCODE = '23514';
  END IF;
  IF effective_state = 'PLANNING' AND
     (NEW.controlling_prd_decision_id IS NULL OR decision_record.state IS DISTINCT FROM 'APPROVED') THEN
   RAISE EXCEPTION 'PRD_PLANNING_REQUIRES_APPROVAL' USING ERRCODE = '23514';
  END IF;
  IF effective_state = 'ALIGNING' AND
     (NEW.controlling_prd_decision_id IS NULL OR decision_record.state NOT IN ('CHANGES_REQUESTED', 'REJECTED')) THEN
   RAISE EXCEPTION 'PRD_ALIGNMENT_REQUIRES_REVIEW_RETURN' USING ERRCODE = '23514';
  END IF;
 END IF;
 IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
 checkpoint_changed := NEW.current_prd_checkpoint_id IS DISTINCT FROM OLD.current_prd_checkpoint_id;
 decision_changed := NEW.controlling_prd_decision_id IS DISTINCT FROM OLD.controlling_prd_decision_id;
 IF OLD.current_prd_checkpoint_id IS NULL AND NOT checkpoint_changed AND NOT decision_changed THEN RETURN NEW; END IF;
 IF NEW.current_prd_checkpoint_id IS NULL THEN
  RAISE EXCEPTION 'PRD_SUBMISSION_HISTORY_RETAINED' USING ERRCODE = '23514';
 END IF;
 IF checkpoint_changed OR decision_changed OR
    ROW(NEW.state, NEW.paused_from_state) IS DISTINCT FROM ROW(OLD.state, OLD.paused_from_state) THEN
  IF NEW.version <> OLD.version + 1 THEN
   RAISE EXCEPTION 'PRD_TRANSITION_VERSION_INVALID' USING ERRCODE = '23514';
  END IF;
  IF checkpoint_changed THEN
   IF OLD.state NOT IN ('ALIGNING', 'PRD_REVIEW') OR NEW.state <> 'PRD_REVIEW' OR
      NEW.controlling_prd_decision_id IS NOT NULL OR
      checkpoint_record.predecessor_id IS DISTINCT FROM OLD.current_prd_checkpoint_id OR
      NEW.updated_by->>'actor_type' IS DISTINCT FROM 'HUMAN' OR
      NEW.updated_by IS DISTINCT FROM checkpoint_record.submitted_or_approved_by OR
      EXISTS (SELECT 1 FROM curve_document_checkpoint
       WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.id
        AND checkpoint_number > checkpoint_record.checkpoint_number) THEN
    RAISE EXCEPTION 'PRD_SUBMISSION_TRANSITION_INVALID' USING ERRCODE = '23514';
   END IF;
  ELSIF decision_changed THEN
   IF OLD.state <> 'PRD_REVIEW' OR NEW.controlling_prd_decision_id IS NULL OR
      OLD.controlling_prd_decision_id IS NOT NULL OR
      NEW.updated_by IS DISTINCT FROM decision_record.decided_by OR
      NEW.state IS DISTINCT FROM
       (CASE WHEN decision_record.state = 'APPROVED' THEN 'PLANNING' ELSE 'ALIGNING' END) THEN
    RAISE EXCEPTION 'PRD_DECISION_TRANSITION_INVALID' USING ERRCODE = '23514';
   END IF;
  ELSIF NOT (
    (OLD.state IN ('ALIGNING', 'PRD_REVIEW', 'PLANNING') AND NEW.state = 'PAUSED'
      AND NEW.paused_from_state = OLD.state) OR
    (OLD.state = 'PAUSED' AND NEW.state = OLD.paused_from_state) OR
    (OLD.state IN ('ALIGNING', 'PRD_REVIEW', 'PLANNING', 'PAUSED') AND NEW.state = 'CANCELLED')
  ) THEN
   RAISE EXCEPTION 'PRD_LIFECYCLE_TRANSITION_INVALID' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_init_prd_lifecycle_guard BEFORE INSERT OR UPDATE ON curve_initiative
 FOR EACH ROW EXECUTE FUNCTION curve_init_prd_lifecycle_guard();
"""

REVERSE = """
LOCK TABLE curve_initiative IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM curve_initiative WHERE current_prd_checkpoint_id IS NOT NULL
  OR controlling_prd_decision_id IS NOT NULL OR state IN ('PRD_REVIEW', 'PLANNING')
  OR paused_from_state IN ('PRD_REVIEW', 'PLANNING')) THEN
  RAISE EXCEPTION 'Retained PRD lifecycle requires a preservation migration';
 END IF;
END $$;
DROP TRIGGER curve_init_prd_lifecycle_guard ON curve_initiative;
DROP FUNCTION curve_init_prd_lifecycle_guard();
ALTER TABLE curve_initiative DROP CONSTRAINT curve_init_prd_decision_fk;
ALTER TABLE curve_initiative DROP CONSTRAINT curve_init_prd_checkpoint_fk;
"""


class Migration(migrations.Migration):
    dependencies = [("curve", "0012_prd_review_decision")]

    operations = [
        migrations.RemoveConstraint(model_name="initiative", name="curve_init_paused_from_ck"),
        migrations.RemoveConstraint(model_name="initiative", name="curve_init_workflow_state_ck"),
        migrations.AddField(
            model_name="initiative",
            name="controlling_prd_decision_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="initiative",
            name="current_prd_checkpoint_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddConstraint(
            model_name="initiative",
            constraint=models.CheckConstraint(
                name="curve_init_paused_from_ck",
                condition=(
                    models.Q(state="PAUSED", paused_from_state__in=["DRAFT", "ALIGNING", "PRD_REVIEW", "PLANNING"])
                    | (~models.Q(state="PAUSED") & models.Q(paused_from_state__isnull=True))
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="initiative",
            constraint=models.CheckConstraint(
                name="curve_init_workflow_state_ck",
                condition=(
                    models.Q(state="DRAFT", workflow_version_id__isnull=True)
                    | models.Q(state__in=["ALIGNING", "PRD_REVIEW", "PLANNING"], workflow_version_id__isnull=False)
                    | models.Q(state="PAUSED", paused_from_state="DRAFT", workflow_version_id__isnull=True)
                    | models.Q(
                        state="PAUSED",
                        paused_from_state__in=["ALIGNING", "PRD_REVIEW", "PLANNING"],
                        workflow_version_id__isnull=False,
                    )
                    | models.Q(state="CANCELLED")
                ),
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
