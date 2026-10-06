CREATE FUNCTION curve_mg2_record_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; q jsonb:=NEW.request_payload; s jsonb; k text; actor jsonb;
 init curve_initiative; ctl curve_manual_gate2_control_v2; draft curve_manual_plan_revision_v2;
 original curve_manual_gate2_record_v2; prior curve_manual_gate2_record_v2; expected_tasks jsonb;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_mpd2_shape(p,curve_mg2_schema('record')) OR NOT curve_mpd2_shape(q,curve_mg2_schema('command'))
  OR octet_length(curve_sprd_canonical(p))>2097152 OR octet_length(curve_sprd_canonical(q))>65536
  OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest OR p->>'digest' IS DISTINCT FROM NEW.digest
  OR p->>'request_digest' IS DISTINCT FROM NEW.request_digest
  OR curve_sprd_digest(jsonb_build_object('initiative_id',NEW.initiative_id::text,'expected_version',NEW.initiative_version-1,'payload',q)) IS DISTINCT FROM NEW.request_digest THEN
  RAISE EXCEPTION 'MANUAL_GATE2_RECORD_INVALID' USING ERRCODE='23514';
 END IF;
 FOR k IN SELECT unnest(ARRAY['id','workspace_id','product_id','initiative_id','initiative_version','predecessor_id','action','subject_id','subject_digest','draft_revision_id','policy_decision_id','command_receipt_id']) LOOP
  IF to_jsonb(NEW)->k IS DISTINCT FROM p->k THEN RAISE EXCEPTION 'MANUAL_GATE2_RECORD_SUBSTITUTION' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF p->>'actor_id' IS DISTINCT FROM NEW.created_by::text OR (p->>'sequence')::bigint<>NEW.version
  OR (p->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at OR NOT isfinite(NEW.recorded_at) OR NEW.recorded_at>clock_timestamp()
  OR q->>'action' IS DISTINCT FROM NEW.action OR q->>'draft_revision_id' IS DISTINCT FROM NEW.draft_revision_id::text
  OR q->'rationale_ref' IS DISTINCT FROM p->'rationale_ref'
  OR (q->'subject_ref'='null'::jsonb) IS DISTINCT FROM (NEW.action='PREPARE')
  OR (q->'rationale_ref'='null'::jsonb) IS DISTINCT FROM (NEW.action='PREPARE')
  OR (q->'reconciliation_ref'<>'null'::jsonb) IS DISTINCT FROM (NEW.action='RELEASE')
  OR (jsonb_array_length(q->'claims')>0) IS DISTINCT FROM (NEW.action IN ('RECONCILE','RELEASE'))
  OR (p->'subject_metadata'<>'null'::jsonb) IS DISTINCT FROM (NEW.action='PREPARE')
  OR (p->'reconciliation_id'<>'null'::jsonb) IS DISTINCT FROM (NEW.action='RELEASE') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_REQUEST_SUBSTITUTION' USING ERRCODE='23514';
 END IF;
 SELECT * INTO init FROM curve_initiative WHERE workspace_id=NEW.workspace_id AND id=NEW.initiative_id FOR UPDATE;
 IF NOT FOUND OR init.product_id<>NEW.product_id OR init.mode<>'STANDALONE' OR init.pending_scope_reopening_id IS NOT NULL
  OR init.version+1<>NEW.initiative_version OR init.state NOT IN ('PLANNING','PAUSED','CANCELLED')
  OR (NEW.action NOT IN ('RECONCILE','RELEASE') AND init.state<>'PLANNING')
  OR NOT EXISTS(SELECT 1 FROM curve_product WHERE id=NEW.product_id AND workspace_id=NEW.workspace_id AND state='ACTIVE') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_INITIATIVE_MISMATCH' USING ERRCODE='23514';
 END IF;
 SELECT * INTO draft FROM curve_manual_plan_revision_v2 WHERE id=NEW.draft_revision_id AND workspace_id=NEW.workspace_id
  AND initiative_id=NEW.initiative_id AND product_id=NEW.product_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'MANUAL_GATE2_DRAFT_REQUIRED' USING ERRCODE='23514'; END IF;
 SELECT * INTO ctl FROM curve_manual_gate2_control_v2 WHERE initiative_id=NEW.initiative_id FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO prior FROM curve_manual_gate2_record_v2 WHERE id=ctl.current_record_id;
  IF ctl.id<>NEW.control_id OR ctl.workspace_id<>NEW.workspace_id OR ctl.product_id<>NEW.product_id
   OR ctl.version+1<>NEW.version OR NEW.predecessor_id IS DISTINCT FROM prior.id
   OR prior.control_id<>ctl.id OR prior.version<>ctl.version OR prior.initiative_version>=NEW.initiative_version OR prior.recorded_at>NEW.recorded_at THEN
   RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_INVALID' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.action<>'PREPARE' OR NEW.version<>1 OR NEW.predecessor_id IS NOT NULL
  OR EXISTS(SELECT 1 FROM curve_manual_gate2_record_v2 WHERE initiative_id=NEW.initiative_id OR control_id=NEW.control_id) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_INVALID' USING ERRCODE='23514';
 END IF;
 IF NEW.action='PREPARE' THEN
  s:=p->'subject_metadata';
  IF NEW.subject_id<>NEW.id OR curve_sprd_digest(s) IS DISTINCT FROM NEW.subject_digest
   OR s->'input_identity' IS DISTINCT FROM draft.original_input_identity
   OR s->>'draft_revision_id' IS DISTINCT FROM draft.id::text OR s->>'draft_digest' IS DISTINCT FROM draft.digest
   OR (s->>'draft_revision')::bigint<>draft.version OR s->>'validation_receipt_digest' IS DISTINCT FROM draft.validation_receipt_digest
   OR s->>'validator_edition' IS DISTINCT FROM draft.validation_receipt->>'validator_edition'
   OR s->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text OR s->>'product_id' IS DISTINCT FROM NEW.product_id::text
   OR s->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR s->>'controlling_prd_decision_id' IS DISTINCT FROM init.controlling_prd_decision_id::text
   OR s->>'risk_tier' IS DISTINCT FROM init.risk_tier
   OR (ctl.id IS NOT NULL AND (ctl.approved_record_id IS NOT NULL OR ctl.state NOT IN ('PLAN_REVIEW','CHANGES_REQUESTED')))
   OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2 WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND current_revision_id=draft.id)
   OR EXISTS(SELECT 1 FROM curve_manual_gate2_record_v2 WHERE initiative_id=NEW.initiative_id AND action='PREPARE' AND draft_revision_id=draft.id) THEN
   RAISE EXCEPTION 'MANUAL_GATE2_SUBJECT_INVALID' USING ERRCODE='23514';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('workspace_id',i.workspace_id::text,'installation_id',i.provider_installation_id::text,'issue_id',i.source_issue_id::text) ORDER BY i.provider_installation_id,i.source_issue_id)
   INTO expected_tasks FROM curve_scope_proposal_item i WHERE i.workspace_id=NEW.workspace_id
    AND i.revision_id=(draft.original_input_identity->'scope_revision_ref'->>'entity_id')::uuid AND i.purpose='PROPOSED_DELIVERY';
  IF expected_tasks IS NULL OR s->'tasks' IS DISTINCT FROM expected_tasks THEN
   RAISE EXCEPTION 'MANUAL_GATE2_TASK_SET_INVALID' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO original FROM curve_manual_gate2_record_v2 WHERE id=NEW.subject_id AND workspace_id=NEW.workspace_id;
  IF NOT FOUND OR original.action<>'PREPARE' OR original.subject_id<>original.id OR original.initiative_id<>NEW.initiative_id
   OR original.product_id<>NEW.product_id OR original.draft_revision_id<>draft.id OR original.subject_digest<>NEW.subject_digest
   OR q->'subject_ref' IS DISTINCT FROM jsonb_build_object('entity_id',original.id::text,'digest',original.subject_digest)
   OR ctl.subject_id IS DISTINCT FROM original.id OR original.payload->'subject_metadata'->>'controlling_prd_decision_id' IS DISTINCT FROM init.controlling_prd_decision_id::text THEN
   RAISE EXCEPTION 'MANUAL_GATE2_SUBJECT_SUBSTITUTION' USING ERRCODE='23514';
  END IF;
  s:=original.payload->'subject_metadata';
  IF NEW.action IN ('APPROVE','REQUEST_CHANGES') THEN
   IF ctl.state<>'PLAN_REVIEW' OR ctl.approved_record_id IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2 WHERE initiative_id=NEW.initiative_id AND current_revision_id=draft.id)
    OR s->>'risk_tier' IS DISTINCT FROM init.risk_tier
    OR NOT EXISTS(SELECT 1 FROM curve_gate_assignment a, jsonb_array_elements(draft.original_input_identity->'gate_assignments') retained_gate
     WHERE a.workspace_id=NEW.workspace_id AND a.initiative_id=NEW.initiative_id AND a.gate_type='PLAN_APPROVAL'
      AND a.id=(retained_gate->>'gate_assignment_id')::uuid AND a.approver_user_id=(retained_gate->>'approver_user_id')::uuid
      AND a.approver_user_id=NEW.created_by AND retained_gate->>'gate_type'='PLAN_APPROVAL' AND a.valid_from<=clock_timestamp() AND (a.valid_until IS NULL OR a.valid_until>clock_timestamp())) THEN
    RAISE EXCEPTION 'MANUAL_GATE2_CURRENT_REVIEW_REQUIRED' USING ERRCODE='23514';
   END IF;
  ELSIF ctl.state<>'MANUAL_APPROVED' OR ctl.approved_record_id IS NULL THEN
   RAISE EXCEPTION 'MANUAL_GATE2_APPROVAL_REQUIRED' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject sp JOIN curve_scoped_prd_decision d ON d.scoped_subject_id=sp.id
  JOIN curve_prd_review_decision b ON b.id=d.decision_id
  WHERE sp.workspace_id=NEW.workspace_id AND sp.initiative_id=NEW.initiative_id AND sp.product_id=NEW.product_id
   AND sp.id=(draft.payload->'approved_subject_ref'->>'entity_id')::uuid AND sp.digest=draft.payload->'approved_subject_ref'->>'digest'
   AND sp.checkpoint_id=init.current_prd_checkpoint_id AND d.workspace_id=NEW.workspace_id AND d.initiative_id=NEW.initiative_id
   AND b.workspace_id=NEW.workspace_id AND b.initiative_id=NEW.initiative_id AND d.decision_id=init.controlling_prd_decision_id
   AND d.payload->>'state'='APPROVED' AND b.state='APPROVED') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_APPROVED_PRD_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF NEW.action<>'PREPARE' AND (SELECT count(*) FROM curve_gate_assignment WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id
  AND gate_type='PLAN_APPROVAL' AND approver_user_id=NEW.created_by AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR valid_until>clock_timestamp()))<>1 THEN
  RAISE EXCEPTION 'MANUAL_GATE2_APPROVER_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF (NEW.action IN ('PREPARE','REQUEST_CHANGES','RECONCILE') AND p->'claims'<>'[]'::jsonb)
  OR (NEW.action NOT IN ('RECONCILE','RELEASE') AND p->'observations'<>'[]'::jsonb)
  OR (NEW.action IN ('APPROVE','RELEASE') AND jsonb_array_length(p->'claims')=0) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_SET_INVALID' USING ERRCODE='23514';
 END IF;
 IF NEW.action='APPROVE' AND (SELECT jsonb_agg(jsonb_build_object('workspace_id',NEW.workspace_id::text,'installation_id',c->>'installation_id','issue_id',c->>'issue_id') ORDER BY c->>'installation_id',c->>'issue_id') FROM jsonb_array_elements(p->'claims') c) IS DISTINCT FROM s->'tasks' THEN
  RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_SET_INVALID' USING ERRCODE='23514';
 END IF;
 IF NEW.action IN ('RECONCILE','RELEASE') THEN
  IF (SELECT jsonb_agg(jsonb_build_object('claim_id',c->>'claim_id','generation',c->'generation') ORDER BY c->>'claim_id') FROM jsonb_array_elements(p->'observations') c) IS DISTINCT FROM q->'claims'
   OR (SELECT count(DISTINCT c->>'claim_id') FROM jsonb_array_elements(p->'observations') c)<>jsonb_array_length(p->'observations') THEN
   RAISE EXCEPTION 'MANUAL_GATE2_OBSERVATIONS_INVALID' USING ERRCODE='23514';
  END IF;
  PERFORM 1 FROM curve_manual_task_claim_v2 c WHERE c.workspace_id=NEW.workspace_id AND c.id IN (SELECT (x->>'claim_id')::uuid FROM jsonb_array_elements(q->'claims') x) ORDER BY c.id FOR UPDATE;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(p->'observations') o WHERE NOT EXISTS(SELECT 1 FROM curve_manual_task_claim_v2 c
   WHERE c.workspace_id=NEW.workspace_id AND c.id=(o->>'claim_id')::uuid AND c.initiative_id=NEW.initiative_id AND c.subject_id=NEW.subject_id
    AND c.generation=(o->>'generation')::bigint AND c.installation_id=(o->>'installation_id')::uuid AND c.issue_id=(o->>'issue_id')::uuid AND c.state='ACTIVE')) THEN
   RAISE EXCEPTION 'MANUAL_GATE2_GENERATION_CONFLICT' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NEW.action='RELEASE' THEN
  SELECT * INTO prior FROM curve_manual_gate2_record_v2 WHERE id=(q->'reconciliation_ref'->>'entity_id')::uuid;
  IF NOT FOUND OR prior.workspace_id<>NEW.workspace_id OR prior.initiative_id<>NEW.initiative_id OR prior.subject_id<>NEW.subject_id
   OR prior.action<>'RECONCILE' OR prior.created_by<>NEW.created_by OR prior.digest IS DISTINCT FROM q->'reconciliation_ref'->>'digest'
   OR prior.id::text IS DISTINCT FROM p->>'reconciliation_id' OR prior.payload->'native_fence_digest' IS DISTINCT FROM p->'native_fence_digest'
   OR prior.payload->'rationale_ref' IS DISTINCT FROM p->'rationale_ref' OR prior.payload->'observations' IS DISTINCT FROM p->'observations'
   OR prior.request_payload->'claims' IS DISTINCT FROM q->'claims'
   OR (SELECT jsonb_agg(jsonb_build_object('claim_id',c->>'claim_id','generation',c->'generation') ORDER BY c->>'claim_id') FROM jsonb_array_elements(p->'claims') c) IS DISTINCT FROM q->'claims' THEN
   RAISE EXCEPTION 'MANUAL_GATE2_RECONCILIATION_REQUIRED' USING ERRCODE='23514';
  END IF;
 END IF;
 actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);
 IF NOT EXISTS(SELECT 1 FROM curve_policy_decision WHERE workspace_id=NEW.workspace_id AND id=NEW.policy_decision_id
  AND action='CURVE.MANUAL_GATE2.'||NEW.action||'_V2' AND effect='ALLOW' AND policy_key='CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2'
  AND policy_version=2 AND policy_manifest_digest='POLICY_DIGEST_LITERAL' AND resource_type='INITIATIVE' AND resource_id=NEW.initiative_id AND resource_version=init.version
  AND input_digest=curve_sprd_digest(jsonb_build_object('request_digest',NEW.request_digest,'native_fence_digest',p->>'native_fence_digest'))
  AND subject=actor AND effective_principal=actor AND permitted_projection='["MANUAL_GATE2_METADATA_V2"]'::jsonb
  AND curve_sprd_created_here('curve_policy_decision',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_POLICY_REQUIRED' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mg2r_insert BEFORE INSERT ON curve_manual_gate2_record_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_record_insert();
CREATE TRIGGER curve_mg2r_stamp AFTER INSERT ON curve_manual_gate2_record_v2 FOR EACH ROW EXECUTE FUNCTION curve_sprd_stamp();

CREATE FUNCTION curve_mg2_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r curve_manual_gate2_record_v2;
BEGIN
 SELECT * INTO r FROM curve_manual_gate2_record_v2 WHERE id=NEW.current_record_id;
 IF NOT FOUND OR r.workspace_id<>NEW.workspace_id OR r.initiative_id<>NEW.initiative_id OR r.product_id<>NEW.product_id
  OR r.control_id<>NEW.id OR r.version<>NEW.version OR r.subject_id<>NEW.subject_id
  OR NOT curve_sprd_created_here('curve_manual_gate2_record_v2',r.workspace_id,r.id)
  OR (r.action='PREPARE' AND NEW.state<>'PLAN_REVIEW') OR (r.action='REQUEST_CHANGES' AND NEW.state<>'CHANGES_REQUESTED')
  OR (r.action IN ('APPROVE','RECONCILE') AND NEW.state<>'MANUAL_APPROVED') OR (r.action='RELEASE' AND NEW.state NOT IN ('MANUAL_APPROVED','RELEASED')) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_HEAD_INVALID' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.version<>1 OR r.action<>'PREPARE' OR NEW.approved_record_id IS NOT NULL THEN
   RAISE EXCEPTION 'MANUAL_GATE2_HEAD_INVALID' USING ERRCODE='23514'; END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['version','current_record_id','subject_id','state','approved_record_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','current_record_id','subject_id','state','approved_record_id'])
   OR NEW.version<>OLD.version+1 OR r.predecessor_id IS DISTINCT FROM OLD.current_record_id
   OR (r.action='APPROVE' AND (OLD.approved_record_id IS NOT NULL OR NEW.approved_record_id IS DISTINCT FROM r.id))
   OR (r.action<>'APPROVE' AND NEW.approved_record_id IS DISTINCT FROM OLD.approved_record_id)
   OR (r.action<>'PREPARE' AND NEW.subject_id IS DISTINCT FROM OLD.subject_id) THEN
   RAISE EXCEPTION 'MANUAL_GATE2_HEAD_REWRITE' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mg2c_head BEFORE INSERT OR UPDATE ON curve_manual_gate2_control_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_head_guard();

CREATE FUNCTION curve_mg2_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r curve_manual_gate2_record_v2; expected jsonb;
BEGIN
 SELECT * INTO r FROM curve_manual_gate2_record_v2 WHERE workspace_id=NEW.workspace_id AND id=NEW.current_record_id;
 expected:=jsonb_build_object('claim_id',NEW.id::text,'history_id',NEW.current_history_id::text,'installation_id',NEW.installation_id::text,'issue_id',NEW.issue_id::text,
  'initiative_id',NEW.initiative_id::text,'subject_id',NEW.subject_id::text,'generation',NEW.generation,'state',NEW.state,'record_id',NEW.current_record_id::text);
 IF NOT FOUND OR r.action NOT IN ('APPROVE','RELEASE') OR r.initiative_id<>NEW.initiative_id OR r.subject_id<>NEW.subject_id
  OR NOT curve_sprd_created_here('curve_manual_gate2_record_v2',r.workspace_id,r.id)
  OR (SELECT count(*) FROM jsonb_array_elements(r.payload->'claims') v WHERE v=expected)<>1
  OR NOT EXISTS(SELECT 1 FROM issues WHERE workspace_id=NEW.workspace_id AND id=NEW.issue_id) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_INVALID' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM issues WHERE workspace_id=NEW.workspace_id AND id=NEW.issue_id FOR UPDATE;
 IF TG_OP='INSERT' THEN
  IF r.action<>'APPROVE' OR NEW.generation<>1 OR NEW.state<>'ACTIVE' THEN RAISE EXCEPTION 'MANUAL_GATE2_FIRST_CLAIM_INVALID' USING ERRCODE='23514'; END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['initiative_id','subject_id','generation','state','current_record_id','current_history_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['initiative_id','subject_id','generation','state','current_record_id','current_history_id'])
   OR NEW.current_record_id=OLD.current_record_id OR NEW.current_history_id=OLD.current_history_id THEN
   RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_IDENTITY_IMMUTABLE' USING ERRCODE='23514'; END IF;
  IF r.action='APPROVE' THEN
   IF OLD.state<>'RELEASED' OR NEW.state<>'ACTIVE' OR NEW.generation<>OLD.generation+1 THEN RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_OCCUPIED' USING ERRCODE='23514'; END IF;
  ELSE
   IF OLD.state<>'ACTIVE' OR NEW.state<>'RELEASED' OR NEW.generation<>OLD.generation OR NEW.initiative_id<>OLD.initiative_id OR NEW.subject_id<>OLD.subject_id THEN
    RAISE EXCEPTION 'MANUAL_GATE2_RELEASE_CONFLICT' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mtc2_head BEFORE INSERT OR UPDATE ON curve_manual_task_claim_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_claim_guard();

CREATE FUNCTION curve_mg2_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r curve_manual_gate2_record_v2; c curve_manual_task_claim_v2; p jsonb:=NEW.payload;
BEGIN
 SELECT * INTO r FROM curve_manual_gate2_record_v2 WHERE id=NEW.record_id AND workspace_id=NEW.workspace_id;
 SELECT * INTO c FROM curve_manual_task_claim_v2 WHERE id=NEW.claim_id AND workspace_id=NEW.workspace_id;
 IF r.id IS NULL OR c.id IS NULL OR NOT curve_sprd_created_here('curve_manual_gate2_record_v2',r.workspace_id,r.id)
  OR (SELECT count(*) FROM jsonb_array_elements(r.payload->'claims') v WHERE v=p)<>1
  OR c.current_history_id<>NEW.id OR c.current_record_id<>r.id OR c.initiative_id<>NEW.initiative_id OR c.generation<>NEW.generation OR c.state<>NEW.state
  OR p->>'claim_id' IS DISTINCT FROM c.id::text OR p->>'history_id' IS DISTINCT FROM NEW.id::text
  OR p->>'record_id' IS DISTINCT FROM r.id::text OR p->>'installation_id' IS DISTINCT FROM c.installation_id::text
  OR p->>'issue_id' IS DISTINCT FROM c.issue_id::text OR p->>'subject_id' IS DISTINCT FROM c.subject_id::text
  OR p->>'initiative_id' IS DISTINCT FROM c.initiative_id::text OR (p->>'generation')::bigint IS DISTINCT FROM c.generation OR p->>'state' IS DISTINCT FROM c.state THEN
  RAISE EXCEPTION 'MANUAL_GATE2_HISTORY_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mtch2_insert BEFORE INSERT ON curve_manual_task_claim_history_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_history_guard();

CREATE FUNCTION curve_mg2_commit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE init curve_initiative; ctl curve_manual_gate2_control_v2; e curve_domain_event; ref jsonb; v_actor jsonb; v_response text; expected_event jsonb;
BEGIN
 SELECT * INTO init FROM curve_initiative WHERE id=NEW.initiative_id AND workspace_id=NEW.workspace_id;
 SELECT * INTO ctl FROM curve_manual_gate2_control_v2 WHERE id=NEW.control_id AND workspace_id=NEW.workspace_id;
 v_actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);
 IF init.id IS NULL OR ctl.id IS NULL OR init.version<>NEW.initiative_version OR init.updated_by IS DISTINCT FROM v_actor
  OR init.product_id<>NEW.product_id OR init.state NOT IN ('PLANNING','PAUSED','CANCELLED')
  OR ctl.current_record_id<>NEW.id OR ctl.version<>NEW.version OR ctl.initiative_id<>NEW.initiative_id
  OR (NEW.action='APPROVE' AND ctl.approved_record_id IS DISTINCT FROM NEW.id)
  OR (NEW.action='RELEASE' AND ((ctl.state='RELEASED') IS DISTINCT FROM NOT EXISTS(SELECT 1 FROM curve_manual_task_claim_v2 WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND subject_id=NEW.subject_id AND state='ACTIVE')))
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'claims') c WHERE NOT EXISTS(SELECT 1 FROM curve_manual_task_claim_history_v2 h JOIN curve_manual_task_claim_v2 t ON t.id=h.claim_id AND t.workspace_id=h.workspace_id
   WHERE h.id=(c->>'history_id')::uuid AND h.workspace_id=NEW.workspace_id AND h.record_id=NEW.id AND h.payload=c
    AND t.current_history_id=h.id AND t.current_record_id=NEW.id))
  OR (SELECT count(*) FROM curve_manual_task_claim_history_v2 WHERE record_id=NEW.id)<>jsonb_array_length(NEW.payload->'claims') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_GRAPH_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 expected_event:=jsonb_build_object('schema_version','curve.manual-gate2.event/v2-candidate','record_id',NEW.id::text,'record_digest',NEW.digest,
  'subject_digest',NEW.subject_digest,'action',NEW.action,'policy_decision_id',NEW.policy_decision_id::text,'execution_authorized',false,'completion_credit',false);
 SELECT * INTO e FROM curve_domain_event WHERE id=NEW.command_receipt_id AND workspace_id=NEW.workspace_id;
 IF NOT FOUND OR e.event_type<>'CURVE.MANUAL_GATE2_RECORDED_V2' OR e.schema_version<>'1.0' OR e.initiative_id IS DISTINCT FROM NEW.initiative_id OR e.workflow_version_id IS DISTINCT FROM init.workflow_version_id OR e.aggregate_type<>'MANUAL_GATE2_CONTROL_V2'
  OR e.aggregate_id<>NEW.control_id OR e.aggregate_version<>NEW.version OR e.sequence<>NEW.version OR e.payload IS DISTINCT FROM expected_event
  OR NOT curve_mpd2_shape(e.payload,curve_mg2_schema('event')) OR e.actor IS DISTINCT FROM v_actor OR e.effective_principal IS DISTINCT FROM v_actor
  OR e.payload_schema<>'https://curve.example.invalid/candidates/manual-gate2-v2/event.schema.json'
  OR NOT curve_sprd_created_here('curve_domain_event',NEW.workspace_id,e.id)
  OR NOT EXISTS(SELECT 1 FROM curve_outbox_event WHERE workspace_id=NEW.workspace_id AND event_id=e.id AND destination='curve-local-manual-gate2-v2'
   AND curve_sprd_created_here('curve_outbox_event',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_EVENT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 ref:=jsonb_build_object('resource_type','MANUAL_GATE2_RECORD_V2','resource_id',NEW.id::text,'resource_version',NEW.version);
 v_response:=curve_sprd_digest(jsonb_build_object('response_status',201,'response_resource_ref',ref));
 IF NOT EXISTS(SELECT 1 FROM curve_idempotency_record i WHERE i.workspace_id=NEW.workspace_id
  AND i.principal_scope='HUMAN:'||NEW.created_by::text AND i.command_scope='CURVE.MANUAL_GATE2.'||NEW.action||'_V2:'||NEW.initiative_id::text
  AND i.key_digest=e.idempotency_key_digest AND i.request_digest=NEW.request_digest AND i.state='COMPLETED'
  AND i.response_status=201 AND i.response_resource_ref=ref AND i.response_digest=v_response
  AND curve_sprd_created_here('curve_idempotency_record',i.workspace_id,i.id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_IDEMPOTENCY_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 IF (SELECT count(*) FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id AND a.policy_decision_ref->>'resource_id'=NEW.policy_decision_id::text)<>1
  OR NOT EXISTS(SELECT 1 FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id AND a.action='CURVE.MANUAL_GATE2.'||NEW.action||'_V2'
   AND a.target_type='MANUAL_GATE2_RECORD_V2' AND a.target_id=NEW.id AND a.target_ref=ref AND a.outcome='SUCCEEDED' AND a.actor=v_actor AND a.effective_principal=v_actor
   AND a.idempotency_key_digest=e.idempotency_key_digest AND a.after_digest=v_response
   AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1)
   AND curve_sprd_created_here('curve_audit_event',a.workspace_id,a.id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_AUDIT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER curve_mg2r_commit AFTER INSERT ON curve_manual_gate2_record_v2 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION curve_mg2_commit_guard();

CREATE FUNCTION curve_mg2_preplan_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM curve_manual_gate2_control_v2 WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND approved_record_id IS NOT NULL) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_PREPLAN_CLOSED' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mg2_draft_closed BEFORE INSERT ON curve_manual_plan_revision_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_preplan_guard();
CREATE TRIGGER curve_mg2_reopen_closed BEFORE INSERT ON curve_scope_reopening FOR EACH ROW EXECUTE FUNCTION curve_mg2_preplan_guard();
CREATE TRIGGER curve_mg2_scope_closed BEFORE INSERT ON curve_scope_proposal_revision FOR EACH ROW EXECUTE FUNCTION curve_mg2_preplan_guard();
CREATE FUNCTION curve_mg2_initiative_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM curve_manual_gate2_control_v2 WHERE workspace_id=OLD.workspace_id AND initiative_id=OLD.id AND approved_record_id IS NOT NULL)
 AND (NEW.state NOT IN ('PLANNING','PAUSED','CANCELLED')
  OR (to_jsonb(NEW)-ARRAY['version','state','paused_from_state','updated_at','updated_by']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','state','paused_from_state','updated_at','updated_by'])) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_APPROVED_CONTEXT_IMMUTABLE' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mg2_init_closed BEFORE UPDATE ON curve_initiative FOR EACH ROW EXECUTE FUNCTION curve_mg2_initiative_guard();

CREATE TABLE curve_manual_gate2_v2_coverage(edition text PRIMARY KEY, catalog_digest text NOT NULL);
CREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$
DECLARE expected text; actual text;
BEGIN
 IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage
  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7')
  OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v2_coverage
  WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2' AND catalog_digest='sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;
 SELECT catalog_digest INTO expected FROM curve_manual_gate2_v2_coverage WHERE edition='CURVE_MANUAL_GATE2_RECONSTRUCTION_V2';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_gate2_v2_coverage)<>1 THEN
  RAISE EXCEPTION 'MANUAL_GATE2_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $$;
