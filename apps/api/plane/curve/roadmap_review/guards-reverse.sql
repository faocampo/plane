CREATE OR REPLACE FUNCTION curve_lprs_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; src curve_local_prd_source%ROWTYPE;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF ((p->>'schema_version'='curve.local-prd-submission/v1-candidate' AND curve_sprd_shape(p, '{"type":"object","additionalProperties":false,"required":["id","workspace_id","initiative_id","source_id","scope_revision_id","submitted_by","initiative_version","source_version","scope_revision","source_digest","content_digest","membership_digest","digest","schema_version","reviewers","risk_tier","submitted_at"],"properties":{"id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"source_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"scope_revision_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"submitted_by":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"scope_revision":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"membership_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"schema_version":{"const":"curve.local-prd-submission/v1-candidate"},"reviewers":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"enum":["PLAN_APPROVAL","PRD_APPROVAL"]},"gate_assignment_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}}},"risk_tier":{"enum":["LOW","STANDARD","HIGH"]},"submitted_at":{"type":"string","pattern":"^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d{1,6})?Z$"}}}'::jsonb)) OR (p->>'schema_version'='curve.local-prd-submission/v2-candidate' AND curve_sprd_shape(p, '{"type":"object","additionalProperties":false,"required":["id","workspace_id","initiative_id","source_id","submitted_by","initiative_version","source_version","source_digest","content_digest","digest","schema_version","reviewers","risk_tier","submitted_at","product_id","product_version","business_intent"],"properties":{"id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"source_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"submitted_by":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"schema_version":{"const":"curve.local-prd-submission/v2-candidate"},"reviewers":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"enum":["PLAN_APPROVAL","PRD_APPROVAL"]},"gate_assignment_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}}},"risk_tier":{"enum":["LOW","STANDARD","HIGH"]},"submitted_at":{"type":"string","pattern":"^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d{1,6})?Z$"},"product_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"business_intent":{"enum":["STRATEGIC","CUSTOMER_COMMITMENT","BUSINESS_IMPROVEMENT","MANDATORY"]}}}'::jsonb))) IS NOT TRUE THEN RAISE EXCEPTION 'LOCAL_REVIEW_SHAPE' USING ERRCODE='23514'; END IF;

 SELECT * INTO src FROM curve_local_prd_source WHERE id=NEW.source_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id;
 IF NOT FOUND OR p->>'id' IS DISTINCT FROM NEW.id::text OR p->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
 OR p->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR p->>'source_id' IS DISTINCT FROM NEW.source_id::text
 OR p->'initiative_version' IS DISTINCT FROM to_jsonb(NEW.initiative_version)
 OR p->>'source_digest' IS DISTINCT FROM src.digest OR p->'source_version' IS DISTINCT FROM to_jsonb(src.version)
 OR p->>'content_digest' IS DISTINCT FROM src.payload->'snapshot'->>'digest'
 OR p->>'digest' IS DISTINCT FROM NEW.digest OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest
 OR p->'reviewers'->0->>'gate_type' IS DISTINCT FROM 'PLAN_APPROVAL'
 OR p->'reviewers'->1->>'gate_type' IS DISTINCT FROM 'PRD_APPROVAL'
 OR p->'reviewers'->0->>'gate_assignment_id'=p->'reviewers'->1->>'gate_assignment_id'
 OR (p->>'risk_tier'<>'LOW' AND p->'reviewers'->0->>'approver_user_id'=p->'reviewers'->1->>'approver_user_id')
 THEN RAISE EXCEPTION 'LOCAL_REVIEW_SUBMISSION_INVALID' USING ERRCODE='23514'; END IF;
 PERFORM (p->>'submitted_at')::timestamptz;
 IF p->>'schema_version'='curve.local-prd-submission/v2-candidate' AND NOT curve_local_new_work_context(p,NEW.workspace_id,NEW.initiative_id) THEN RAISE EXCEPTION 'LOCAL_NEW_WORK_CONTEXT_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION curve_local_prd_current_subject(subject_id uuid, workspace uuid, initiative uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s curve_local_prd_submission; init curve_initiative; p jsonb;
BEGIN
 SELECT * INTO s FROM curve_local_prd_submission WHERE id=subject_id AND workspace_id=workspace AND initiative_id=initiative;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCAL_REVIEW_SUBJECT_UNAVAILABLE' USING ERRCODE='23514'; END IF;
 SELECT * INTO init FROM curve_initiative WHERE id=initiative AND workspace_id=workspace;
 p:=s.payload;
 IF init.risk_tier IS DISTINCT FROM p->>'risk_tier' OR
 s.source_id IS DISTINCT FROM (SELECT id FROM curve_local_prd_source WHERE workspace_id=workspace AND initiative_id=initiative ORDER BY version DESC LIMIT 1)
 OR (CASE WHEN p->>'schema_version'='curve.local-prd-submission/v2-candidate' THEN NOT curve_local_new_work_context(p,workspace,initiative) ELSE NOT EXISTS(SELECT 1 FROM curve_scope_proposal h JOIN curve_scope_proposal_revision rev ON rev.id=h.current_revision_id AND rev.workspace_id=h.workspace_id
 WHERE h.workspace_id=workspace AND h.initiative_id=initiative AND rev.id::text=p->>'scope_revision_id'
 AND rev.version=(p->>'scope_revision')::bigint AND rev.membership_digest=p->>'membership_digest') END)
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'reviewers') reviewer WHERE NOT EXISTS(
 SELECT 1 FROM curve_gate_assignment a WHERE a.workspace_id=workspace AND a.initiative_id=initiative
 AND a.id::text=reviewer->>'gate_assignment_id' AND a.gate_type=reviewer->>'gate_type'
 AND a.approver_user_id::text=reviewer->>'approver_user_id' AND a.valid_from<=CURRENT_TIMESTAMP
 AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))) THEN
 RAISE EXCEPTION 'LOCAL_REVIEW_SUBJECT_CHANGED' USING ERRCODE='23514'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.curve_init_prd_lifecycle_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE local_subject curve_local_prd_submission; local_decision curve_local_prd_decision;
 local_reopening curve_local_prd_reopening;
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
  SELECT * INTO local_reopening FROM curve_local_prd_reopening WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.id AND submission_id=NEW.current_local_prd_submission_id
   AND decision_id=NEW.controlling_local_prd_decision_id AND initiative_version<NEW.version;
  effective_state:=CASE WHEN NEW.state='PAUSED' THEN NEW.paused_from_state ELSE NEW.state END;
  IF effective_state NOT IN ('ALIGNING','PRD_REVIEW','PLANNING','CANCELLED')
   OR (effective_state='PRD_REVIEW' AND NEW.controlling_local_prd_decision_id IS NOT NULL)
   OR (effective_state='PLANNING' AND (NEW.controlling_local_prd_decision_id IS NULL OR local_decision.state IS DISTINCT FROM 'APPROVED'))
   OR (effective_state='ALIGNING' AND (NEW.controlling_local_prd_decision_id IS NULL OR NOT (
    local_decision.state='CHANGES_REQUESTED' OR (local_decision.state='APPROVED' AND local_reopening.id IS NOT NULL)))) THEN
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
      AND old_dec.id=OLD.controlling_local_prd_decision_id
      AND (old_dec.state='CHANGES_REQUESTED' OR (old_dec.state='APPROVED' AND EXISTS(
       SELECT 1 FROM curve_local_prd_reopening r JOIN curve_local_prd_source fresh ON fresh.id=local_subject.source_id
       WHERE r.workspace_id=NEW.workspace_id AND r.initiative_id=NEW.id AND r.submission_id=old_sub.id
        AND r.decision_id=old_dec.id AND r.initiative_version<OLD.version
        AND fresh.workspace_id=NEW.workspace_id AND fresh.initiative_id=NEW.id
        AND fresh.version>(old_sub.payload->>'source_version')::bigint
        AND (fresh.payload->>'uploaded_at')::timestamptz >= (r.payload->>'reopened_at')::timestamptz)))
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
   ELSIF OLD.state='PLANNING' AND NEW.state='ALIGNING' THEN
    IF NEW.paused_from_state IS NOT NULL OR local_decision.state IS DISTINCT FROM 'APPROVED'
     OR local_reopening.id IS NULL OR local_reopening.initiative_version<>OLD.version
     OR local_reopening.payload->>'reopened_by' IS DISTINCT FROM NEW.creator_user_id::text
     OR NEW.updated_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',NEW.creator_user_id::text)
     OR NOT curve_sprd_created_here('curve_local_prd_reopening',NEW.workspace_id,local_reopening.id) THEN
     RAISE EXCEPTION 'LOCAL_PRD_REOPENING_TRANSITION_INVALID' USING ERRCODE='23514'; END IF;
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
CREATE OR REPLACE FUNCTION curve_lpro_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; subj curve_local_prd_submission%ROWTYPE; deci curve_local_prd_decision%ROWTYPE; init curve_initiative%ROWTYPE;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_sprd_shape(p, '{"additionalProperties":false,"properties":{"decision_digest":{"pattern":"^sha256:[0-9a-f]{64}$","type":"string"},"decision_id":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"},"digest":{"pattern":"^sha256:[0-9a-f]{64}$","type":"string"},"id":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"},"initiative_id":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"},"initiative_version":{"maximum":9007199254740991,"minimum":1,"type":"integer"},"reopened_at":{"pattern":"^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d{1,6})?Z$","type":"string"},"reopened_by":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"},"schema_version":{"const":"curve.local-prd-reopening/v1-candidate"},"source_digest":{"pattern":"^sha256:[0-9a-f]{64}$","type":"string"},"source_id":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"},"submission_digest":{"pattern":"^sha256:[0-9a-f]{64}$","type":"string"},"submission_id":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"},"workspace_id":{"pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","type":"string"}},"required":["decision_digest","decision_id","digest","id","initiative_id","initiative_version","reopened_at","reopened_by","schema_version","source_digest","source_id","submission_digest","submission_id","workspace_id"],"type":"object"}'::jsonb) THEN RAISE EXCEPTION 'LOCAL_PRD_REOPENING_SHAPE' USING ERRCODE='23514'; END IF;
 IF p->>'id' IS DISTINCT FROM NEW.id::text OR p->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
 OR p->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR p->'initiative_version' IS DISTINCT FROM to_jsonb(NEW.initiative_version)
 OR p->>'submission_id' IS DISTINCT FROM NEW.submission_id::text OR p->>'decision_id' IS DISTINCT FROM NEW.decision_id::text
 OR p->>'digest' IS DISTINCT FROM NEW.digest OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest THEN
 RAISE EXCEPTION 'LOCAL_PRD_REOPENING_IDENTITY' USING ERRCODE='23514'; END IF;
 SELECT * INTO subj FROM curve_local_prd_submission WHERE id=NEW.submission_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCAL_PRD_REOPENING_SUBJECT' USING ERRCODE='23514'; END IF;
 SELECT * INTO deci FROM curve_local_prd_decision WHERE id=NEW.decision_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND submission_id=subj.id;
 IF NOT FOUND OR deci.state<>'APPROVED' OR NEW.initiative_version<=deci.initiative_version
 OR p->>'submission_digest' IS DISTINCT FROM subj.digest OR p->>'decision_digest' IS DISTINCT FROM deci.digest
 OR p->>'source_id' IS DISTINCT FROM subj.source_id::text OR p->>'source_digest' IS DISTINCT FROM subj.payload->>'source_digest'
 OR (p->>'reopened_at')::timestamptz<(deci.payload->>'decided_at')::timestamptz THEN
 RAISE EXCEPTION 'LOCAL_PRD_REOPENING_APPROVAL' USING ERRCODE='23514'; END IF;
 SELECT * INTO init FROM curve_initiative WHERE id=NEW.initiative_id AND workspace_id=NEW.workspace_id FOR UPDATE;
 IF NOT FOUND OR init.schema_version<>'1.2' OR init.mode<>'STANDALONE' OR init.state<>'PLANNING'
 OR init.version<>NEW.initiative_version OR init.current_local_prd_submission_id IS DISTINCT FROM subj.id
 OR init.controlling_local_prd_decision_id IS DISTINCT FROM deci.id
 OR init.current_prd_checkpoint_id IS NOT NULL OR init.pending_scope_reopening_id IS NOT NULL
 OR p->>'reopened_by' IS DISTINCT FROM init.creator_user_id::text THEN
 RAISE EXCEPTION 'LOCAL_PRD_REOPENING_CURRENT_OWNER_REQUIRED' USING ERRCODE='23514'; END IF;
 PERFORM curve_local_prd_current_subject(subj.id,NEW.workspace_id,NEW.initiative_id);
 RETURN NEW;
END $$;
