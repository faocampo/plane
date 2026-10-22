CREATE OR REPLACE FUNCTION public.curve_init_prd_lifecycle_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE local_subject curve_local_prd_submission; local_decision curve_local_prd_decision;
 local_subject_changed boolean; local_decision_changed boolean;
 checkpoint_record curve_document_checkpoint; decision_record curve_prd_review_decision;
 reopening curve_scope_reopening;
 effective_state text; checkpoint_changed boolean; decision_changed boolean;
BEGIN
 IF (TG_OP='INSERT' AND (NEW.current_local_prd_submission_id IS NOT NULL OR NEW.controlling_local_prd_decision_id IS NOT NULL)) THEN
  RAISE EXCEPTION 'LOCAL_REVIEW_EXISTING_INITIATIVE_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND (NEW.current_local_prd_submission_id IS NOT NULL OR NEW.controlling_local_prd_decision_id IS NOT NULL
  OR OLD.current_local_prd_submission_id IS NOT NULL OR OLD.controlling_local_prd_decision_id IS NOT NULL) THEN
  PERFORM curve_scope_reopening_verify_coverage();
  IF NEW.schema_version<>'1.2' OR NEW.mode<>'STANDALONE' OR NEW.current_prd_checkpoint_id IS NOT NULL
   OR NEW.controlling_prd_decision_id IS NOT NULL OR NEW.pending_scope_reopening_id IS NOT NULL
   OR OLD.current_prd_checkpoint_id IS NOT NULL OR OLD.pending_scope_reopening_id IS NOT NULL
   OR NEW.current_local_prd_submission_id IS NULL THEN
   RAISE EXCEPTION 'LOCAL_REVIEW_LIFECYCLE_SCOPE_INVALID' USING ERRCODE='23514'; END IF;
  SELECT * INTO local_subject FROM curve_local_prd_submission WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.id AND id=NEW.current_local_prd_submission_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'LOCAL_REVIEW_SUBMISSION_REQUIRED' USING ERRCODE='23514'; END IF;
  IF NEW.controlling_local_prd_decision_id IS NOT NULL THEN
   SELECT * INTO local_decision FROM curve_local_prd_decision WHERE workspace_id=NEW.workspace_id
    AND initiative_id=NEW.id AND id=NEW.controlling_local_prd_decision_id AND submission_id=local_subject.id;
   IF NOT FOUND THEN RAISE EXCEPTION 'LOCAL_REVIEW_DECISION_SUBJECT_INVALID' USING ERRCODE='23514'; END IF;
  END IF;
  effective_state:=CASE WHEN NEW.state='PAUSED' THEN NEW.paused_from_state ELSE NEW.state END;
  IF effective_state NOT IN ('ALIGNING','PRD_REVIEW','PLANNING','CANCELLED')
   OR (effective_state='PRD_REVIEW' AND NEW.controlling_local_prd_decision_id IS NOT NULL)
   OR (effective_state='PLANNING' AND (NEW.controlling_local_prd_decision_id IS NULL OR local_decision.state IS DISTINCT FROM 'APPROVED'))
   OR (effective_state='ALIGNING' AND (NEW.controlling_local_prd_decision_id IS NULL OR local_decision.state IS DISTINCT FROM 'CHANGES_REQUESTED')) THEN
   RAISE EXCEPTION 'LOCAL_REVIEW_STATE_EVIDENCE_REQUIRED' USING ERRCODE='23514'; END IF;
  local_subject_changed:=NEW.current_local_prd_submission_id IS DISTINCT FROM OLD.current_local_prd_submission_id;
  local_decision_changed:=NEW.controlling_local_prd_decision_id IS DISTINCT FROM OLD.controlling_local_prd_decision_id;
  IF local_subject_changed OR local_decision_changed OR ROW(NEW.state,NEW.paused_from_state) IS DISTINCT FROM ROW(OLD.state,OLD.paused_from_state) THEN
   IF NEW.version<>OLD.version+1 OR
    (to_jsonb(NEW)-ARRAY['state','paused_from_state','version','updated_by','updated_at','current_local_prd_submission_id','controlling_local_prd_decision_id'])
    IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['state','paused_from_state','version','updated_by','updated_at','current_local_prd_submission_id','controlling_local_prd_decision_id']) THEN
    RAISE EXCEPTION 'LOCAL_REVIEW_TRANSITION_FIELDS_INVALID' USING ERRCODE='23514'; END IF;
   IF local_subject_changed THEN
    IF OLD.state<>'ALIGNING' OR NEW.state<>'PRD_REVIEW' OR NEW.paused_from_state IS NOT NULL
     OR NEW.controlling_local_prd_decision_id IS NOT NULL OR local_subject.initiative_version<>OLD.version
     OR local_subject.payload->>'submitted_by' IS DISTINCT FROM NEW.creator_user_id::text
     OR NEW.updated_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',local_subject.payload->>'submitted_by')
     OR NOT curve_sprd_created_here('curve_local_prd_submission',NEW.workspace_id,local_subject.id) THEN
     RAISE EXCEPTION 'LOCAL_REVIEW_SUBMISSION_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
    IF OLD.current_local_prd_submission_id IS NOT NULL AND NOT EXISTS(
     SELECT 1 FROM curve_local_prd_submission old_sub JOIN curve_local_prd_decision old_dec ON old_dec.submission_id=old_sub.id
     WHERE old_sub.workspace_id=NEW.workspace_id AND old_sub.initiative_id=NEW.id AND old_sub.id=OLD.current_local_prd_submission_id
      AND old_dec.id=OLD.controlling_local_prd_decision_id AND old_dec.state='CHANGES_REQUESTED'
      AND old_sub.source_id<>local_subject.source_id) THEN
     RAISE EXCEPTION 'LOCAL_REVIEW_REPLACEMENT_REQUIRED' USING ERRCODE='23514'; END IF;
    PERFORM curve_local_prd_current_subject(local_subject.id,NEW.workspace_id,NEW.id);
   ELSIF local_decision_changed THEN
    IF OLD.state<>'PRD_REVIEW' OR OLD.controlling_local_prd_decision_id IS NOT NULL
     OR NEW.controlling_local_prd_decision_id IS NULL OR local_decision.initiative_version<>OLD.version
     OR NEW.state IS DISTINCT FROM (CASE WHEN local_decision.state='APPROVED' THEN 'PLANNING' ELSE 'ALIGNING' END)
     OR NEW.updated_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',local_decision.payload->>'decided_by')
     OR NOT curve_sprd_created_here('curve_local_prd_decision',NEW.workspace_id,local_decision.id) THEN
     RAISE EXCEPTION 'LOCAL_REVIEW_DECISION_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
    PERFORM curve_local_prd_current_subject(local_subject.id,NEW.workspace_id,NEW.id);
   ELSIF NOT (
    (OLD.state IN ('ALIGNING','PRD_REVIEW','PLANNING') AND NEW.state='PAUSED' AND NEW.paused_from_state=OLD.state)
    OR (OLD.state='PAUSED' AND NEW.state=OLD.paused_from_state AND NEW.paused_from_state IS NULL)
    OR (OLD.state IN ('ALIGNING','PRD_REVIEW','PLANNING','PAUSED') AND NEW.state='CANCELLED' AND NEW.paused_from_state IS NULL)
   ) THEN RAISE EXCEPTION 'LOCAL_REVIEW_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='INSERT' AND NEW.pending_scope_reopening_id IS NOT NULL THEN
  RAISE EXCEPTION 'SCOPE_REOPENING_EXISTING_INITIATIVE_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' THEN
  IF NEW.pending_scope_reopening_id IS DISTINCT FROM OLD.pending_scope_reopening_id THEN
   IF NEW.pending_scope_reopening_id IS NOT NULL THEN
    SELECT * INTO reopening FROM curve_scope_reopening WHERE workspace_id=NEW.workspace_id
     AND initiative_id=NEW.id AND id=NEW.pending_scope_reopening_id;
    IF NOT FOUND OR NOT curve_sprd_created_here('curve_scope_reopening',NEW.workspace_id,reopening.id)
     OR ROW(OLD.version,OLD.state,OLD.current_prd_checkpoint_id,OLD.controlling_prd_decision_id,OLD.pending_scope_reopening_id)
      IS DISTINCT FROM ROW(reopening.previous_initiative_version,reopening.previous_state,reopening.previous_checkpoint_id,
       reopening.previous_decision_id,reopening.previous_pending_reopening_id)
     OR NEW.state<>'ALIGNING' OR NEW.version<>OLD.version+1 OR NEW.controlling_prd_decision_id IS NOT NULL
     OR NEW.current_prd_checkpoint_id IS DISTINCT FROM OLD.current_prd_checkpoint_id
     OR NEW.updated_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',reopening.created_by::text)
     OR (to_jsonb(NEW)-ARRAY['state','version','updated_by','updated_at','controlling_prd_decision_id','pending_scope_reopening_id'])
      IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','version','updated_by','updated_at','controlling_prd_decision_id','pending_scope_reopening_id'])
     OR NOT EXISTS(SELECT 1 FROM curve_scope_proposal_revision WHERE workspace_id=NEW.workspace_id
      AND initiative_id=NEW.id AND id=reopening.scope_revision_id AND policy_edition='REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1'
      AND curve_sprd_created_here('curve_scope_proposal_revision',workspace_id,id)) THEN
     RAISE EXCEPTION 'SCOPE_REOPENING_TRANSITION_INVALID' USING ERRCODE='23514';
    END IF;
    PERFORM curve_reopen_fence(reopening);
    RETURN NEW;
   ELSE
    IF OLD.state<>'ALIGNING' OR NEW.state<>'PRD_REVIEW' OR NEW.version<>OLD.version+1
     OR NEW.controlling_prd_decision_id IS NOT NULL
     OR NEW.current_prd_checkpoint_id IS NOT DISTINCT FROM OLD.current_prd_checkpoint_id
     OR NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject s JOIN curve_scope_proposal h
       ON h.workspace_id=s.workspace_id AND h.initiative_id=s.initiative_id
      WHERE s.workspace_id=NEW.workspace_id AND s.initiative_id=NEW.id AND s.checkpoint_id=NEW.current_prd_checkpoint_id
       AND s.payload->>'scope_revision_id'=h.current_revision_id::text AND s.payload->>'proposal_id'=h.id::text
       AND (s.payload->>'scope_revision')::bigint=h.version
       AND curve_sprd_created_here('curve_scoped_prd_subject',s.workspace_id,s.id)) THEN
     RAISE EXCEPTION 'SCOPE_REOPENING_FRESH_SCOPED_SUBMISSION_REQUIRED' USING ERRCODE='23514';
    END IF;
    -- Continue into unchanged checkpoint/predecessor/actor lifecycle checks.
   END IF;
  ELSIF NEW.pending_scope_reopening_id IS NOT NULL THEN
   -- Pending scope can pause, resume or cancel under the existing lifecycle.
   -- The retained checkpoint remains stale and never gains gate authority.
   IF NEW.current_prd_checkpoint_id IS DISTINCT FROM OLD.current_prd_checkpoint_id
    OR NEW.controlling_prd_decision_id IS NOT NULL
    OR NEW.state NOT IN ('ALIGNING','PAUSED','CANCELLED')
    OR (NEW.state='PAUSED' AND NEW.paused_from_state IS DISTINCT FROM 'ALIGNING') THEN
    RAISE EXCEPTION 'SCOPE_REOPENING_FRESH_SCOPED_SUBMISSION_REQUIRED' USING ERRCODE='23514';
   END IF;
   IF ROW(NEW.state,NEW.paused_from_state) IS DISTINCT FROM ROW(OLD.state,OLD.paused_from_state) THEN
    IF NEW.version<>OLD.version+1 OR NOT (
      (OLD.state='ALIGNING' AND NEW.state='PAUSED' AND NEW.paused_from_state='ALIGNING') OR
      (OLD.state='PAUSED' AND OLD.paused_from_state='ALIGNING' AND NEW.state='ALIGNING') OR
      (OLD.state IN ('ALIGNING','PAUSED') AND NEW.state='CANCELLED')
    ) THEN
     RAISE EXCEPTION 'PRD_LIFECYCLE_TRANSITION_INVALID' USING ERRCODE='23514';
    END IF;
   END IF;
   RETURN NEW;
  END IF;
 END IF;

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
$function$

;
CREATE OR REPLACE FUNCTION public.curve_scope_reopening_verify_coverage()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE expected text; actual text;
BEGIN
 IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage
  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7')
  OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v2_coverage
  WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2' AND catalog_digest='sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_manual_gate2_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_gate2_v2_coverage WHERE edition='CURVE_MANUAL_GATE2_RECONSTRUCTION_V2' AND catalog_digest='sha256:4d33761d55c0f0cb509af13a729cdb6a7479c7b8ca662fc843f856bce33adb08') THEN
 RAISE EXCEPTION 'TWO_STAGE_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_two_stage_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_two_stage_v2_coverage WHERE edition='CURVE_TWO_STAGE_REVIEW_V2' AND catalog_digest='sha256:fb8f201929aac3461836becdecdde3b29996e52e6aea6ed48c2be6035c1083ef') THEN
 RAISE EXCEPTION 'SCOPED_V2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_scoped_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scoped_v2_coverage WHERE edition='CURVE_SCOPED_PRD_V2' AND catalog_digest='sha256:c14b6221600c6e6be301cc3a36d26cbeb4b3c85e3d904f42e6cbb5e39e67f207') THEN
 RAISE EXCEPTION 'MANUAL_V3_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_manual_plan_v3_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v3_coverage WHERE edition='CURVE_MANUAL_PLAN_V3' AND catalog_digest='sha256:1e67c1cedc9bd5529f060b3b6a726291163cc2e5d8634fe2e11b3fe33c2d7866') THEN RAISE EXCEPTION 'TECHNICAL_V3_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_manual_gate2_v3_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_gate2_v3_coverage WHERE edition='CURVE_MANUAL_GATE2_V3' AND catalog_digest='sha256:8b846ec66b306ffc5c95b52818c5bb03acadadde679df7b678da4f3afedc0e64') THEN RAISE EXCEPTION 'LOCAL_PRD_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_coverage WHERE edition='CURVE_LOCAL_PRD_SOURCE_V1' AND catalog_digest='sha256:493f45a0eadfd45263212043ec835fd996ac1968ad2bdeb6e25d23b0657590d3') THEN RAISE EXCEPTION 'LOCAL_PRD_COMMAND_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_command_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_command_coverage WHERE edition='CURVE_LOCAL_PRD_COMMAND_V1' AND catalog_digest='sha256:5a0d96f6556657552da753e3f81d79004c0b84622aad7f89789f1a7fa7e1202d') THEN RAISE EXCEPTION 'LOCAL_REVIEW_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_review_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_review_coverage WHERE edition='CURVE_LOCAL_PRD_REVIEW_V1' AND catalog_digest='sha256:72373212877c9f6510b8fec3fa9881d1f9167e5f703ade011a54d81a8b6c519c') THEN RAISE EXCEPTION 'LOCAL_LIFECYCLE_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 SELECT catalog_digest INTO expected FROM curve_local_prd_lifecycle_coverage WHERE edition='CURVE_LOCAL_PRD_LIFECYCLE_V1';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_local_prd_lifecycle_coverage)<>1 THEN
  RAISE EXCEPTION 'LOCAL_PRD_COMMAND_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
DROP TABLE curve_local_prd_reopening_lifecycle_coverage;
CREATE OR REPLACE FUNCTION public.curve_scope_reopening_verify_coverage()
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE expected text; actual text;
BEGIN
 IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage
  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7')
  OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v2_coverage
  WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2' AND catalog_digest='sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_manual_gate2_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_gate2_v2_coverage WHERE edition='CURVE_MANUAL_GATE2_RECONSTRUCTION_V2' AND catalog_digest='sha256:4d33761d55c0f0cb509af13a729cdb6a7479c7b8ca662fc843f856bce33adb08') THEN
 RAISE EXCEPTION 'TWO_STAGE_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_two_stage_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_two_stage_v2_coverage WHERE edition='CURVE_TWO_STAGE_REVIEW_V2' AND catalog_digest='sha256:fb8f201929aac3461836becdecdde3b29996e52e6aea6ed48c2be6035c1083ef') THEN
 RAISE EXCEPTION 'SCOPED_V2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_scoped_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scoped_v2_coverage WHERE edition='CURVE_SCOPED_PRD_V2' AND catalog_digest='sha256:c14b6221600c6e6be301cc3a36d26cbeb4b3c85e3d904f42e6cbb5e39e67f207') THEN
 RAISE EXCEPTION 'MANUAL_V3_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_manual_plan_v3_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v3_coverage WHERE edition='CURVE_MANUAL_PLAN_V3' AND catalog_digest='sha256:1e67c1cedc9bd5529f060b3b6a726291163cc2e5d8634fe2e11b3fe33c2d7866') THEN RAISE EXCEPTION 'TECHNICAL_V3_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_manual_gate2_v3_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_gate2_v3_coverage WHERE edition='CURVE_MANUAL_GATE2_V3' AND catalog_digest='sha256:8b846ec66b306ffc5c95b52818c5bb03acadadde679df7b678da4f3afedc0e64') THEN RAISE EXCEPTION 'LOCAL_PRD_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_coverage WHERE edition='CURVE_LOCAL_PRD_SOURCE_V1' AND catalog_digest='sha256:493f45a0eadfd45263212043ec835fd996ac1968ad2bdeb6e25d23b0657590d3') THEN RAISE EXCEPTION 'LOCAL_PRD_COMMAND_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_command_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_command_coverage WHERE edition='CURVE_LOCAL_PRD_COMMAND_V1' AND catalog_digest='sha256:5a0d96f6556657552da753e3f81d79004c0b84622aad7f89789f1a7fa7e1202d') THEN RAISE EXCEPTION 'LOCAL_REVIEW_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_review_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_review_coverage WHERE edition='CURVE_LOCAL_PRD_REVIEW_V1' AND catalog_digest='sha256:72373212877c9f6510b8fec3fa9881d1f9167e5f703ade011a54d81a8b6c519c') THEN RAISE EXCEPTION 'LOCAL_LIFECYCLE_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_lifecycle_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_lifecycle_coverage WHERE edition='CURVE_LOCAL_PRD_LIFECYCLE_V1' AND catalog_digest='sha256:686647dc47a2fe04fbc427615338a69f2b6574d6d3c3566450022357006b371a') THEN RAISE EXCEPTION 'LOCAL_REVIEW_COMMAND_PREDECESSOR_INVALID' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM curve_local_review_command_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_review_command_coverage WHERE edition='CURVE_LOCAL_REVIEW_COMMAND_V1' AND catalog_digest='sha256:61e61f1f432642210b96957bd10ae4c73b907db171c79978090c7f202c6c1b27') THEN RAISE EXCEPTION 'LOCAL_PLAN_PREDECESSOR_INVALID'; END IF;
 IF (SELECT count(*) FROM curve_local_plan_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_plan_coverage WHERE edition='CURVE_LOCAL_PLAN_REVISION_V1' AND catalog_digest='sha256:d6fc20764bb94c03248733d050de7cf9a65688ae7589d05c5dd98a7a25e26122') THEN RAISE EXCEPTION 'LOCAL_PLAN_UPLOAD_PREDECESSOR_INVALID'; END IF;
 IF (SELECT count(*) FROM curve_local_plan_upload_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_plan_upload_coverage WHERE edition='CURVE_LOCAL_PLAN_UPLOAD_V1' AND catalog_digest='sha256:ee2a07a279b1f5a6f1c3346dc716644015e4469e3db5938a51e37995c372487c') THEN RAISE EXCEPTION 'LOCAL_PLAN_REVIEW_PREDECESSOR_INVALID'; END IF;
 IF (SELECT count(*) FROM curve_local_plan_review_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_plan_review_coverage WHERE edition='CURVE_LOCAL_PLAN_REVIEW_V1' AND catalog_digest='sha256:918031fe6e522af5cc8b5f292079555e0cf1540c8fffb8a1e98d7fab952ea308') THEN RAISE EXCEPTION 'LOCAL_PLAN_COMMAND_PREDECESSOR_INVALID'; END IF;
 IF (SELECT count(*) FROM curve_local_plan_command_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_plan_command_coverage WHERE edition='CURVE_LOCAL_PLAN_COMMAND_V1' AND catalog_digest='sha256:bfb5d8f7e8a436454ed51d95c3d0f1fd1d6436c45e3bcb557b33857fb1d8e683') THEN RAISE EXCEPTION 'LOCAL_REOPENING_PREDECESSOR_INVALID'; END IF;
 SELECT catalog_digest INTO expected FROM curve_local_prd_reopening_coverage WHERE edition='CURVE_LOCAL_PRD_REOPENING_V1';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_local_prd_reopening_coverage)<>1 THEN
  RAISE EXCEPTION 'LOCAL_PRD_COMMAND_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
