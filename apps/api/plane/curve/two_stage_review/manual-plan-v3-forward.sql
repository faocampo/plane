CREATE FUNCTION curve_mpd_edition(p jsonb) RETURNS integer LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
 IF p->>'schema_version'='curve.manual-plan-draft.revision/v2-candidate' THEN RETURN 2; END IF;
 IF p->>'schema_version'='curve.manual-plan-draft.revision/v3-candidate' THEN RETURN 3; END IF;
 RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_EDITION_INVALID' USING ERRCODE='23514';
END $$;
CREATE FUNCTION curve_mpd2_schema(kind text, edition integer) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE STRICT AS $$
BEGIN
 IF edition=2 THEN RETURN curve_mpd2_schema(kind); END IF;
 IF edition=3 THEN RETURN '{"revision":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v3/manual-plan-draft-revision-v3.schema.json","title":"Protected immutable draft metadata projection","type":"object","additionalProperties":false,"required":["schema_version","policy_edition","id","workspace_id","product_id","initiative_id","draft_id","revision","initiative_version","predecessor_id","approved_subject_ref","definition_ref","manual_profile_ref","created_by","recorded_at","digest","controlling"],"properties":{"schema_version":{"const":"curve.manual-plan-draft.revision/v3-candidate"},"policy_edition":{"const":"LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V3"},"id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"revision":{"type":"integer","minimum":1,"maximum":9007199254740991},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"predecessor_id":{"anyOf":[{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},{"type":"null"}]},"approved_subject_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"definition_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":5242880},"media_type":{"const":"application/json"}}},"manual_profile_ref":{"allOf":[{"allOf":[{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000301","digest":"sha256:fbfaf1ae8608aa580c5d76514a948ef515f8e0795248d180840fb89779f5a1e8"}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000301","digest":"sha256:fbfaf1ae8608aa580c5d76514a948ef515f8e0795248d180840fb89779f5a1e8"}},"created_by":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"recorded_at":{"type":"string","format":"date-time","pattern":"^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d{1,6})?Z$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"controlling":{"const":false}}},"identity":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v3/manual-plan-input-identity-v3.schema.json","title":"Private retained original-input identities, never a current ACL","type":"object","additionalProperties":false,"required":["schema_version","workspace_id","initiative_id","approved_subject_ref","prd_artifact_version_id","prd_content_digest","evidence_snapshot_id","scope_revision_ref","manual_profile_ref","definition_ref","workflow_ref","quality_policy_ref","repository_inputs","protected_inputs","human_owner_ids","gate_assignments","digest"],"properties":{"schema_version":{"const":"curve.manual-plan-input-identity/v3-candidate"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approved_subject_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"prd_artifact_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"evidence_snapshot_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"scope_revision_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"manual_profile_ref":{"allOf":[{"allOf":[{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000301","digest":"sha256:fbfaf1ae8608aa580c5d76514a948ef515f8e0795248d180840fb89779f5a1e8"}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000301","digest":"sha256:fbfaf1ae8608aa580c5d76514a948ef515f8e0795248d180840fb89779f5a1e8"}},"definition_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":5242880},"media_type":{"const":"application/json"}}},"workflow_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"quality_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"repository_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["repository_ref","base_branch","base_commit","repository_policy_ref","context_input_ref"],"properties":{"repository_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"base_branch":{"type":"string","minLength":1,"maxLength":255,"pattern":"\\S"},"base_commit":{"oneOf":[{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha1"},"value":{"type":"string","pattern":"^[0-9a-f]{40}$"}}},{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha256"},"value":{"type":"string","pattern":"^[0-9a-f]{64}$"}}}]},"repository_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"context_input_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}}}},"minItems":1,"maxItems":32,"uniqueItems":true},"protected_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["object_ref","material_version_id","access_envelope_id","classification","input_kind"],"properties":{"object_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}},"material_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"access_envelope_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"classification":{"type":"string","enum":["INTERNAL","CONFIDENTIAL","RESTRICTED"]},"input_kind":{"type":"string","enum":["CONTEXT_INPUT","ATTACHMENT"]}},"allOf":[{"if":{"properties":{"input_kind":{"const":"ATTACHMENT"}},"required":["input_kind"]},"then":{"properties":{"object_ref":{"properties":{"size_bytes":{"maximum":104857600}}}}}}]},"minItems":1,"maxItems":1024,"uniqueItems":true},"human_owner_ids":{"type":"array","items":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"minItems":1,"maxItems":256,"uniqueItems":true},"gate_assignments":{"type":"array","minItems":2,"maxItems":2,"uniqueItems":true,"prefixItems":[{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PLAN_APPROVAL"}}}]},{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PRD_APPROVAL"}}}]}],"items":false},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"validation":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v3/manual-plan-validation-receipt-v3.schema.json","title":"Private deterministic validation result","type":"object","additionalProperties":false,"required":["schema_version","validator_edition","definition_digest","input_identity_digest","result","repository_count","slice_count","edge_count","required_conditions","digest"],"properties":{"schema_version":{"const":"curve.manual-plan-validation-receipt/v3-candidate"},"validator_edition":{"const":"DETERMINISTIC_SDLC_MANUAL_PLAN_V3"},"definition_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"input_identity_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"result":{"const":"VALID"},"repository_count":{"type":"integer","minimum":1,"maximum":32},"slice_count":{"type":"integer","minimum":1,"maximum":256},"edge_count":{"type":"integer","minimum":0,"maximum":4096},"required_conditions":{"const":"FUTURE_NOT_ASSERTED"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"event":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v3/manual-plan-draft-event-v3.schema.json","title":"Minimal immutable manual draft event payload","type":"object","additionalProperties":false,"required":["schema_version","policy_edition","event_type","workspace_id","initiative_id","draft_id","revision_id","revision_digest","definition_digest","input_identity_digest","policy_decision_id","controlling"],"properties":{"schema_version":{"const":"curve.manual-plan-draft.event/v3-candidate"},"policy_edition":{"const":"LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V3"},"event_type":{"const":"CURVE.MANUAL_PLAN_DRAFT_SAVED_V3"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"revision_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"definition_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"input_identity_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"policy_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"controlling":{"const":false}}}}'::jsonb->kind; END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION public.curve_mpr2_insert_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE edition integer:=curve_mpd_edition(NEW.payload); p jsonb:=NEW.payload; ident jsonb:=NEW.original_input_identity; v jsonb:=NEW.validation_receipt;
 init curve_initiative; head curve_manual_plan_draft_v2; previous curve_manual_plan_revision_v2; k text; actor jsonb;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_mpd2_shape(p,curve_mpd2_schema('revision',edition)) OR NOT curve_mpd2_shape(ident,curve_mpd2_schema('identity',edition))
  OR NOT curve_mpd2_shape(v,curve_mpd2_schema('validation',edition))
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
  OR (edition=3 AND init.schema_version<>'1.2') OR (edition=2 AND init.schema_version NOT IN ('1.0','1.1'))
  OR init.version+1<>NEW.initiative_version OR init.pending_scope_reopening_id IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM curve_product WHERE id=NEW.product_id AND workspace_id=NEW.workspace_id AND state='ACTIVE') THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_INITIATIVE_MISMATCH' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject s JOIN curve_scoped_prd_decision d ON d.scoped_subject_id=s.id
  JOIN curve_prd_review_decision b ON b.id=d.decision_id
  WHERE s.workspace_id=NEW.workspace_id AND s.initiative_id=NEW.initiative_id AND s.product_id=NEW.product_id
  AND s.id=(p->'approved_subject_ref'->>'entity_id')::uuid AND s.digest=p->'approved_subject_ref'->>'digest'
  AND s.payload->>'schema_version'=curve_sprd_initiative_edition(init.schema_version)
  AND d.payload->>'schema_version'=s.payload->>'schema_version'
  AND s.checkpoint_id=init.current_prd_checkpoint_id AND d.workspace_id=s.workspace_id AND d.initiative_id=s.initiative_id
  AND d.decision_id=init.controlling_prd_decision_id AND d.payload->>'state'='APPROVED'
  AND b.workspace_id=s.workspace_id AND b.initiative_id=s.initiative_id AND b.state='APPROVED') THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_APPROVED_SUBJECT_REQUIRED' USING ERRCODE='23514';
 END IF;
 SELECT * INTO head FROM curve_manual_plan_draft_v2 WHERE initiative_id=NEW.initiative_id FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO previous FROM curve_manual_plan_revision_v2 WHERE id=head.current_revision_id;
  IF curve_mpd_edition(previous.payload)<>edition OR head.id<>NEW.draft_id OR head.workspace_id<>NEW.workspace_id OR head.product_id<>NEW.product_id
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
  AND action=('CURVE.MANUAL_PLAN_DRAFT.SAVE'||'_V'||edition::text) AND effect='ALLOW' AND policy_key=('CURVE_MANUAL_PLAN_DRAFT_POLICY'||'_V'||edition::text)
  AND policy_version=edition AND policy_manifest_digest=(CASE edition WHEN 3 THEN 'sha256:84e831c2011a85b83acb8a2d414d586b0d948fbcf76fc666140459e04276f38f' ELSE 'sha256:cd960f017b8209b5e4a26a624cfb3549577f946c5a9682c593dec5908d6ab2f0' END)
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
DECLARE edition integer:=curve_mpd_edition(NEW.payload); init curve_initiative; e curve_domain_event; ref jsonb; v_actor jsonb; expected_event jsonb; v_request_digest text; v_response_digest text;
BEGIN
 SELECT * INTO init FROM curve_initiative WHERE id=NEW.initiative_id AND workspace_id=NEW.workspace_id;
 v_actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);
 IF NOT FOUND OR init.version<>NEW.initiative_version OR init.state<>'PLANNING' OR init.product_id<>NEW.product_id
  OR init.updated_by IS DISTINCT FROM v_actor OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2
  WHERE id=NEW.draft_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND product_id=NEW.product_id
   AND current_revision_id=NEW.id AND version=NEW.version) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_GRAPH_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 expected_event:=jsonb_build_object('schema_version',('curve.manual-plan-draft.event'||'/v'||edition::text||'-candidate'),
  'policy_edition',('LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION'||'_V'||edition::text),'event_type',('CURVE.MANUAL_PLAN_DRAFT_SAVED'||'_V'||edition::text),
  'workspace_id',NEW.workspace_id::text,'initiative_id',NEW.initiative_id::text,'draft_id',NEW.draft_id::text,
  'revision_id',NEW.id::text,'revision_digest',NEW.digest,'definition_digest',NEW.payload->'definition_ref'->>'digest',
  'input_identity_digest',NEW.input_identity_digest,'policy_decision_id',NEW.policy_decision_id::text,'controlling',false);
 SELECT * INTO e FROM curve_domain_event WHERE id=NEW.command_receipt_id AND workspace_id=NEW.workspace_id;
 IF NOT FOUND OR e.event_type<>('CURVE.MANUAL_PLAN_DRAFT_SAVED'||'_V'||edition::text) OR e.aggregate_type<>('MANUAL_PLAN_DRAFT'||'_V'||edition::text)
  OR e.aggregate_id<>NEW.draft_id OR e.aggregate_version<>NEW.version OR e.sequence<>NEW.version
  OR e.payload IS DISTINCT FROM expected_event OR NOT curve_mpd2_shape(e.payload,curve_mpd2_schema('event',edition))
  OR e.actor IS DISTINCT FROM v_actor OR e.effective_principal IS DISTINCT FROM v_actor
  OR e.payload_schema<>('https://curve.example.invalid/candidates/manual-planning'||'-v'||edition::text||'/manual-plan-draft-event'||'-v'||edition::text||'.schema.json')
  OR NOT curve_sprd_created_here('curve_domain_event',NEW.workspace_id,e.id)
  OR NOT EXISTS(SELECT 1 FROM curve_outbox_event WHERE workspace_id=NEW.workspace_id AND event_id=e.id
    AND destination=('CURVE_MANUAL_PLAN_DRAFT_LOCAL'||'_V'||edition::text) AND curve_sprd_created_here('curve_outbox_event',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_EVENT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 ref:=jsonb_build_object('resource_type',('MANUAL_PLAN_DRAFT_REVISION'||'_V'||edition::text),'resource_id',NEW.id::text,'resource_version',NEW.version);
 v_response_digest:=curve_sprd_digest(jsonb_build_object('response_status',201,'response_resource_ref',ref));
 v_request_digest:=curve_sprd_digest(jsonb_build_object('initiative_id',NEW.initiative_id::text,'expected_initiative_version',NEW.initiative_version-1,
  'payload',jsonb_build_object('schema_version',('curve.manual-plan-draft.save'||'/v'||edition::text||'-candidate'),'policy_edition',('LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION'||'_V'||edition::text),
  'expected_draft_revision',NEW.version-1,'approved_subject_ref',NEW.payload->'approved_subject_ref',
  'definition_ref',NEW.payload->'definition_ref','manual_profile_ref',NEW.payload->'manual_profile_ref')));
 IF NOT EXISTS(SELECT 1 FROM curve_idempotency_record i WHERE i.workspace_id=NEW.workspace_id
  AND i.principal_scope='HUMAN:'||NEW.created_by::text AND i.command_scope=('CURVE.MANUAL_PLAN_DRAFT.SAVE'||'_V'||edition::text||':')||NEW.initiative_id::text
  AND i.key_digest=e.idempotency_key_digest AND i.request_digest=v_request_digest AND i.state='COMPLETED'
  AND i.response_status=201 AND i.response_resource_ref=ref AND i.response_digest=v_response_digest
  AND curve_sprd_created_here('curve_idempotency_record',i.workspace_id,i.id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_IDEMPOTENCY_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 IF (SELECT count(*) FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id
  AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1))<>1
  OR NOT EXISTS(SELECT 1 FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id
   AND a.action=('CURVE.MANUAL_PLAN_DRAFT.SAVE'||'_V'||edition::text) AND a.target_type=('MANUAL_PLAN_DRAFT_REVISION'||'_V'||edition::text) AND a.target_id=NEW.id
   AND a.target_ref=ref AND a.outcome='SUCCEEDED' AND a.actor=v_actor AND a.effective_principal=v_actor
   AND a.idempotency_key_digest=e.idempotency_key_digest AND a.after_digest=v_response_digest
   AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1)
   AND curve_sprd_created_here('curve_audit_event',a.workspace_id,a.id)) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_AUDIT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $function$;

CREATE TABLE curve_manual_plan_v3_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);
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
 SELECT catalog_digest INTO expected FROM curve_manual_plan_v3_coverage WHERE edition='CURVE_MANUAL_PLAN_V3';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_plan_v3_coverage)<>1 THEN
  RAISE EXCEPTION 'MANUAL_V3_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
