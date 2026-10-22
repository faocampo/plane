CREATE TABLE curve_local_prd_reopening_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);
ALTER TABLE curve_local_prd_reopening ADD CONSTRAINT curve_lpro_sub_scope_fk FOREIGN KEY(workspace_id,initiative_id,submission_id) REFERENCES curve_local_prd_submission(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_local_prd_reopening ADD CONSTRAINT curve_lpro_dec_scope_fk FOREIGN KEY(workspace_id,initiative_id,decision_id) REFERENCES curve_local_prd_decision(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION curve_lpro_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER curve_lpro_guard BEFORE INSERT ON curve_local_prd_reopening FOR EACH ROW EXECUTE FUNCTION curve_lpro_insert_guard();
CREATE TRIGGER curve_lpro_stamp AFTER INSERT ON curve_local_prd_reopening FOR EACH ROW EXECUTE FUNCTION curve_sprd_stamp();
CREATE TRIGGER curve_lpro_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON curve_local_prd_reopening FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
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
