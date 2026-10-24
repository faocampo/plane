CREATE TABLE curve_local_plan_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);
ALTER TABLE curve_local_plan_revision ADD CONSTRAINT curve_lplan_subject_scope_fk FOREIGN KEY(workspace_id,initiative_id,prd_submission_id) REFERENCES curve_local_prd_submission(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_local_plan_revision ADD CONSTRAINT curve_lplan_decision_scope_fk FOREIGN KEY(workspace_id,initiative_id,prd_decision_id) REFERENCES curve_local_prd_decision(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_local_plan_revision ADD CONSTRAINT curve_lplan_previous_scope_fk FOREIGN KEY(workspace_id,initiative_id,predecessor_id) REFERENCES curve_local_plan_revision(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION curve_lplan_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; subj curve_local_prd_submission%ROWTYPE; deci curve_local_prd_decision%ROWTYPE; prior curve_local_plan_revision%ROWTYPE;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT (p ? 'predecessor_id') OR NOT curve_sprd_shape(jsonb_set(p,'{predecessor_id}','null'::jsonb), '{"type":"object","additionalProperties":false,"required":["id","workspace_id","initiative_id","prd_submission_id","prd_decision_id","uploaded_by","prd_submission_digest","prd_decision_digest","digest","version","initiative_version","schema_version","predecessor_id","original","snapshot","normalization_schema_version","uploaded_at"],"properties":{"id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_submission_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_decision_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"uploaded_by":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_submission_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"prd_decision_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"version":{"type":"integer","minimum":1,"maximum":9007199254740991},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"schema_version":{"const":"curve.local-plan-revision/v1-candidate"},"predecessor_id":{"type":"null"},"original":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":10485760},"media_type":{"enum":["application/pdf","text/plain","text/markdown"]}}},"snapshot":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":62918656},"media_type":{"enum":["application/json"]}}},"normalization_schema_version":{"const":"curve.local-upload.normalized/v1-candidate"},"uploaded_at":{"type":"string","pattern":"^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d{1,6})?Z$"}}}'::jsonb)
 THEN RAISE EXCEPTION 'LOCAL_PLAN_SHAPE' USING ERRCODE='23514'; END IF;
 SELECT * INTO subj FROM curve_local_prd_submission WHERE id=NEW.prd_submission_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCAL_PLAN_SUBJECT' USING ERRCODE='23514'; END IF;
 SELECT * INTO deci FROM curve_local_prd_decision WHERE id=NEW.prd_decision_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id;
 IF NOT FOUND OR deci.submission_id<>subj.id OR deci.state<>'APPROVED' THEN RAISE EXCEPTION 'LOCAL_PLAN_APPROVAL' USING ERRCODE='23514'; END IF;
 IF p->>'id' IS DISTINCT FROM NEW.id::text OR p->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
 OR p->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR p->>'prd_submission_id' IS DISTINCT FROM NEW.prd_submission_id::text
 OR p->>'prd_decision_id' IS DISTINCT FROM NEW.prd_decision_id::text OR p->>'prd_submission_digest' IS DISTINCT FROM subj.digest
 OR p->>'prd_decision_digest' IS DISTINCT FROM deci.digest OR p->'version' IS DISTINCT FROM to_jsonb(NEW.version)
 OR p->'initiative_version' IS DISTINCT FROM to_jsonb(NEW.initiative_version) OR NEW.initiative_version<=deci.initiative_version
 OR p->>'digest' IS DISTINCT FROM NEW.digest OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest
 OR p->'original'->>'object_id'=p->'snapshot'->>'object_id'
 OR (p->>'uploaded_at')::timestamptz<(deci.payload->>'decided_at')::timestamptz
 OR p->>'predecessor_id' IS DISTINCT FROM NEW.predecessor_id::text
 THEN RAISE EXCEPTION 'LOCAL_PLAN_IDENTITY' USING ERRCODE='23514'; END IF;
 IF NEW.version=1 THEN
  IF NEW.predecessor_id IS NOT NULL OR p->'predecessor_id' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'LOCAL_PLAN_PREDECESSOR' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO prior FROM curve_local_plan_revision WHERE id=NEW.predecessor_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id;
  IF NOT FOUND OR prior.version+1<>NEW.version THEN RAISE EXCEPTION 'LOCAL_PLAN_PREDECESSOR' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_lplan_insert BEFORE INSERT ON curve_local_plan_revision FOR EACH ROW EXECUTE FUNCTION curve_lplan_insert_guard();
CREATE TRIGGER curve_lplan_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON curve_local_plan_revision FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
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
 SELECT catalog_digest INTO expected FROM curve_local_plan_coverage WHERE edition='CURVE_LOCAL_PLAN_REVISION_V1';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_local_plan_coverage)<>1 THEN
  RAISE EXCEPTION 'LOCAL_PRD_COMMAND_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
