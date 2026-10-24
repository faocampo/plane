CREATE OR REPLACE FUNCTION public.curve_mpr2_insert_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE p jsonb:=NEW.payload; ident jsonb:=NEW.original_input_identity; v jsonb:=NEW.validation_receipt;
 init curve_initiative; head curve_manual_plan_draft_v2; previous curve_manual_plan_revision_v2; k text; actor jsonb;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_mpd2_shape(p,curve_mpd2_schema('revision')) OR NOT curve_mpd2_shape(ident,curve_mpd2_schema('identity'))
  OR NOT curve_mpd2_shape(v,curve_mpd2_schema('validation'))
  OR octet_length(curve_sprd_canonical(p))>65536 OR octet_length(curve_sprd_canonical(ident))>1048576
  OR octet_length(curve_sprd_canonical(v))>16384
  OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest OR p->>'digest' IS DISTINCT FROM NEW.digest
  OR curve_sprd_digest(ident-'digest') IS DISTINCT FROM NEW.input_identity_digest OR ident->>'digest' IS DISTINCT FROM NEW.input_identity_digest
  OR curve_sprd_digest(v-'digest') IS DISTINCT FROM NEW.validation_receipt_digest OR v->>'digest' IS DISTINCT FROM NEW.validation_receipt_digest
  OR v->>'input_identity_digest' IS DISTINCT FROM NEW.input_identity_digest
  OR v->>'definition_digest' IS DISTINCT FROM p->'definition_ref'->>'digest' THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_RECORD_INVALID' USING ERRCODE='23514';
 END IF;
 FOR k IN SELECT unnest(ARRAY['id','workspace_id','product_id','initiative_id','draft_id','initiative_version','predecessor_id','created_by']) LOOP
  IF to_jsonb(NEW)->k IS DISTINCT FROM p->k THEN RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_RECORD_SUBSTITUTION' USING ERRCODE='23514'; END IF;
 END LOOP;
 FOR k IN SELECT unnest(ARRAY['workspace_id','initiative_id','approved_subject_ref','definition_ref','manual_profile_ref']) LOOP
  IF ident->k IS DISTINCT FROM p->k THEN RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_INPUT_SUBSTITUTION' USING ERRCODE='23514'; END IF;
 END LOOP;
 IF NEW.version IS DISTINCT FROM (p->>'revision')::bigint OR NOT isfinite(NEW.recorded_at)
  OR NEW.recorded_at>clock_timestamp() OR (p->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_RECORD_SUBSTITUTION' USING ERRCODE='23514';
 END IF;
 SELECT * INTO init FROM curve_initiative WHERE id=NEW.initiative_id AND workspace_id=NEW.workspace_id FOR UPDATE;
 IF NOT FOUND OR init.product_id<>NEW.product_id OR init.mode<>'STANDALONE' OR init.state<>'PLANNING'
  OR init.version+1<>NEW.initiative_version OR init.pending_scope_reopening_id IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM curve_product WHERE id=NEW.product_id AND workspace_id=NEW.workspace_id AND state='ACTIVE') THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_INITIATIVE_MISMATCH' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject s JOIN curve_scoped_prd_decision d ON d.scoped_subject_id=s.id
  JOIN curve_prd_review_decision b ON b.id=d.decision_id
  WHERE s.workspace_id=NEW.workspace_id AND s.initiative_id=NEW.initiative_id AND s.product_id=NEW.product_id
  AND s.id=(p->'approved_subject_ref'->>'entity_id')::uuid AND s.digest=p->'approved_subject_ref'->>'digest'
  AND s.checkpoint_id=init.current_prd_checkpoint_id AND d.workspace_id=s.workspace_id AND d.initiative_id=s.initiative_id
  AND d.decision_id=init.controlling_prd_decision_id AND d.payload->>'state'='APPROVED'
  AND b.workspace_id=s.workspace_id AND b.initiative_id=s.initiative_id AND b.state='APPROVED') THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_APPROVED_SUBJECT_REQUIRED' USING ERRCODE='23514';
 END IF;
 SELECT * INTO head FROM curve_manual_plan_draft_v2 WHERE initiative_id=NEW.initiative_id FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO previous FROM curve_manual_plan_revision_v2 WHERE id=head.current_revision_id;
  IF head.id<>NEW.draft_id OR head.workspace_id<>NEW.workspace_id OR head.product_id<>NEW.product_id
   OR head.version+1<>NEW.version OR previous.id IS DISTINCT FROM NEW.predecessor_id
   OR previous.draft_id<>head.id OR previous.version<>head.version OR previous.workspace_id<>NEW.workspace_id
   OR previous.initiative_id<>NEW.initiative_id OR previous.product_id<>NEW.product_id
   OR previous.initiative_version>=NEW.initiative_version OR previous.recorded_at>NEW.recorded_at THEN
   RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_PREDECESSOR_INVALID' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.version<>1 OR NEW.predecessor_id IS NOT NULL
  OR EXISTS(SELECT 1 FROM curve_manual_plan_revision_v2 WHERE initiative_id=NEW.initiative_id OR draft_id=NEW.draft_id) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_PREDECESSOR_INVALID' USING ERRCODE='23514';
 END IF;
 actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);
 IF NOT EXISTS(SELECT 1 FROM curve_policy_decision WHERE workspace_id=NEW.workspace_id AND id=NEW.policy_decision_id
  AND action='CURVE.MANUAL_PLAN_DRAFT.SAVE_V2' AND effect='ALLOW' AND policy_key='CURVE_MANUAL_PLAN_DRAFT_POLICY_V2'
  AND policy_version=2 AND policy_manifest_digest='sha256:cd960f017b8209b5e4a26a624cfb3549577f946c5a9682c593dec5908d6ab2f0'
  AND resource_type='INITIATIVE' AND resource_id=NEW.initiative_id AND resource_version=init.version
  AND subject=actor AND effective_principal=actor AND curve_sprd_created_here('curve_policy_decision',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_POLICY_REQUIRED' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION public.curve_mpr2_commit_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE init curve_initiative; e curve_domain_event; ref jsonb; v_actor jsonb; expected_event jsonb; v_request_digest text; v_response_digest text;
BEGIN
 SELECT * INTO init FROM curve_initiative WHERE id=NEW.initiative_id AND workspace_id=NEW.workspace_id;
 v_actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);
 IF NOT FOUND OR init.version<>NEW.initiative_version OR init.state<>'PLANNING' OR init.product_id<>NEW.product_id
  OR init.updated_by IS DISTINCT FROM v_actor OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2
  WHERE id=NEW.draft_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND product_id=NEW.product_id
   AND current_revision_id=NEW.id AND version=NEW.version) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_GRAPH_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 expected_event:=jsonb_build_object('schema_version','curve.manual-plan-draft.event/v2-candidate',
  'policy_edition','LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2','event_type','CURVE.MANUAL_PLAN_DRAFT_SAVED_V2',
  'workspace_id',NEW.workspace_id::text,'initiative_id',NEW.initiative_id::text,'draft_id',NEW.draft_id::text,
  'revision_id',NEW.id::text,'revision_digest',NEW.digest,'definition_digest',NEW.payload->'definition_ref'->>'digest',
  'input_identity_digest',NEW.input_identity_digest,'policy_decision_id',NEW.policy_decision_id::text,'controlling',false);
 SELECT * INTO e FROM curve_domain_event WHERE id=NEW.command_receipt_id AND workspace_id=NEW.workspace_id;
 IF NOT FOUND OR e.event_type<>'CURVE.MANUAL_PLAN_DRAFT_SAVED_V2' OR e.aggregate_type<>'MANUAL_PLAN_DRAFT_V2'
  OR e.aggregate_id<>NEW.draft_id OR e.aggregate_version<>NEW.version OR e.sequence<>NEW.version
  OR e.payload IS DISTINCT FROM expected_event OR NOT curve_mpd2_shape(e.payload,curve_mpd2_schema('event'))
  OR e.actor IS DISTINCT FROM v_actor OR e.effective_principal IS DISTINCT FROM v_actor
  OR e.payload_schema<>'https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-draft-event-v2.schema.json'
  OR NOT curve_sprd_created_here('curve_domain_event',NEW.workspace_id,e.id)
  OR NOT EXISTS(SELECT 1 FROM curve_outbox_event WHERE workspace_id=NEW.workspace_id AND event_id=e.id
    AND destination='CURVE_MANUAL_PLAN_DRAFT_LOCAL_V2' AND curve_sprd_created_here('curve_outbox_event',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_EVENT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 ref:=jsonb_build_object('resource_type','MANUAL_PLAN_DRAFT_REVISION_V2','resource_id',NEW.id::text,'resource_version',NEW.version);
 v_response_digest:=curve_sprd_digest(jsonb_build_object('response_status',201,'response_resource_ref',ref));
 v_request_digest:=curve_sprd_digest(jsonb_build_object('initiative_id',NEW.initiative_id::text,'expected_initiative_version',NEW.initiative_version-1,
  'payload',jsonb_build_object('schema_version','curve.manual-plan-draft.save/v2-candidate','policy_edition','LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2',
  'expected_draft_revision',NEW.version-1,'approved_subject_ref',NEW.payload->'approved_subject_ref',
  'definition_ref',NEW.payload->'definition_ref','manual_profile_ref',NEW.payload->'manual_profile_ref')));
 IF NOT EXISTS(SELECT 1 FROM curve_idempotency_record i WHERE i.workspace_id=NEW.workspace_id
  AND i.principal_scope='HUMAN:'||NEW.created_by::text AND i.command_scope='CURVE.MANUAL_PLAN_DRAFT.SAVE_V2:'||NEW.initiative_id::text
  AND i.key_digest=e.idempotency_key_digest AND i.request_digest=v_request_digest AND i.state='COMPLETED'
  AND i.response_status=201 AND i.response_resource_ref=ref AND i.response_digest=v_response_digest
  AND curve_sprd_created_here('curve_idempotency_record',i.workspace_id,i.id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_IDEMPOTENCY_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 IF (SELECT count(*) FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id
  AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1))<>1
  OR NOT EXISTS(SELECT 1 FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id
   AND a.action='CURVE.MANUAL_PLAN_DRAFT.SAVE_V2' AND a.target_type='MANUAL_PLAN_DRAFT_REVISION_V2' AND a.target_id=NEW.id
   AND a.target_ref=ref AND a.outcome='SUCCEEDED' AND a.actor=v_actor AND a.effective_principal=v_actor
   AND a.idempotency_key_digest=e.idempotency_key_digest AND a.after_digest=v_response_digest
   AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1)
   AND curve_sprd_created_here('curve_audit_event',a.workspace_id,a.id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_AUDIT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $function$;

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
 SELECT catalog_digest INTO expected FROM curve_scoped_v2_coverage WHERE edition='CURVE_SCOPED_PRD_V2';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_scoped_v2_coverage)<>1 THEN
  RAISE EXCEPTION 'SCOPED_V2_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;

DROP TABLE curve_manual_plan_v3_coverage;
DROP FUNCTION curve_mpd2_schema(text,integer);
DROP FUNCTION curve_mpd_edition(jsonb);
