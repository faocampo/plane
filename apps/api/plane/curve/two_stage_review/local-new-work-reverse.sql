CREATE OR REPLACE FUNCTION curve_lprs_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; src curve_local_prd_source%ROWTYPE;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_sprd_shape(p, '{"type":"object","additionalProperties":false,"required":["id","workspace_id","initiative_id","source_id","scope_revision_id","submitted_by","initiative_version","source_version","scope_revision","source_digest","content_digest","membership_digest","digest","schema_version","reviewers","risk_tier","submitted_at"],"properties":{"id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"source_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"scope_revision_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"submitted_by":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"scope_revision":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"membership_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"schema_version":{"const":"curve.local-prd-submission/v1-candidate"},"reviewers":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"enum":["PLAN_APPROVAL","PRD_APPROVAL"]},"gate_assignment_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}}},"risk_tier":{"enum":["LOW","STANDARD","HIGH"]},"submitted_at":{"type":"string","pattern":"^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d{1,6})?Z$"}}}'::jsonb) THEN RAISE EXCEPTION 'LOCAL_REVIEW_SHAPE' USING ERRCODE='23514'; END IF;

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
 OR NOT EXISTS(SELECT 1 FROM curve_scope_proposal h JOIN curve_scope_proposal_revision rev ON rev.id=h.current_revision_id AND rev.workspace_id=h.workspace_id
 WHERE h.workspace_id=workspace AND h.initiative_id=initiative AND rev.id::text=p->>'scope_revision_id'
 AND rev.version=(p->>'scope_revision')::bigint AND rev.membership_digest=p->>'membership_digest')
 OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'reviewers') reviewer WHERE NOT EXISTS(
 SELECT 1 FROM curve_gate_assignment a WHERE a.workspace_id=workspace AND a.initiative_id=initiative
 AND a.id::text=reviewer->>'gate_assignment_id' AND a.gate_type=reviewer->>'gate_type'
 AND a.approver_user_id::text=reviewer->>'approver_user_id' AND a.valid_from<=CURRENT_TIMESTAMP
 AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))) THEN
 RAISE EXCEPTION 'LOCAL_REVIEW_SUBJECT_CHANGED' USING ERRCODE='23514'; END IF;
END $$;
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
 IF (SELECT count(*) FROM curve_local_prd_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_reopening_coverage WHERE edition='CURVE_LOCAL_PRD_REOPENING_V1' AND catalog_digest='sha256:663c765011f3d9423704e1d3fb3758ee8ed8d6b589ea8dc2271d38f55bbbd3b6') THEN RAISE EXCEPTION 'LOCAL_REOPENING_LIFECYCLE_PREDECESSOR_INVALID'; END IF;
 IF (SELECT count(*) FROM curve_local_prd_reopening_lifecycle_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_local_prd_reopening_lifecycle_coverage WHERE edition='CURVE_LOCAL_PRD_REOPENING_LIFECYCLE_V1' AND catalog_digest='sha256:1920e236fcbc4ddb00b75e3a6cd82aaebadb774b41b9eca3c23a008e6dabf118') THEN RAISE EXCEPTION 'LOCAL_REOPENING_COMMAND_PREDECESSOR_INVALID'; END IF;
 SELECT catalog_digest INTO expected FROM curve_local_reopen_command_coverage WHERE edition='CURVE_LOCAL_PRD_REOPENING_COMMAND_V1';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_local_reopen_command_coverage)<>1 THEN
  RAISE EXCEPTION 'LOCAL_PRD_COMMAND_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;

DROP FUNCTION curve_local_new_work_context(jsonb,uuid,uuid);
DROP TABLE curve_local_new_work_coverage;
