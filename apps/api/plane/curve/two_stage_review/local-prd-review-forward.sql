CREATE TABLE curve_local_prd_review_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);
ALTER TABLE curve_local_prd_submission ADD CONSTRAINT curve_lprs_source_scope_fk FOREIGN KEY(workspace_id,initiative_id,source_id) REFERENCES curve_local_prd_source(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_local_prd_decision ADD CONSTRAINT curve_lprd_dec_subject_scope_fk FOREIGN KEY(workspace_id,initiative_id,submission_id) REFERENCES curve_local_prd_submission(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION curve_lprs_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE FUNCTION curve_lprd_dec_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; subj curve_local_prd_submission%ROWTYPE; s jsonb;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_sprd_shape(CASE WHEN NEW.state='CHANGES_REQUESTED' THEN jsonb_set(p,'{feedback}','null'::jsonb) ELSE p END, '{"type":"object","additionalProperties":false,"required":["id","workspace_id","initiative_id","submission_id","source_id","gate_assignment_id","decided_by","submission_digest","source_digest","digest","schema_version","initiative_version","state","decided_at","feedback"],"properties":{"id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"submission_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"source_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"gate_assignment_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"decided_by":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"submission_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"source_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"schema_version":{"const":"curve.local-prd-decision/v1-candidate"},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"state":{"enum":["APPROVED","CHANGES_REQUESTED"]},"decided_at":{"type":"string","pattern":"^\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d{1,6})?Z$"},"feedback":{"type":"null"}}}'::jsonb) THEN RAISE EXCEPTION 'LOCAL_REVIEW_SHAPE' USING ERRCODE='23514'; END IF;

 SELECT * INTO subj FROM curve_local_prd_submission WHERE id=NEW.submission_id AND workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'LOCAL_REVIEW_SUBMISSION_UNAVAILABLE' USING ERRCODE='23514'; END IF;
 s:=subj.payload;
 IF p->>'id' IS DISTINCT FROM NEW.id::text OR p->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
 OR p->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR p->>'submission_id' IS DISTINCT FROM NEW.submission_id::text
 OR p->'initiative_version' IS DISTINCT FROM to_jsonb(NEW.initiative_version) OR NEW.initiative_version<=subj.initiative_version
 OR p->>'submission_digest' IS DISTINCT FROM subj.digest OR p->>'source_id' IS DISTINCT FROM s->>'source_id'
 OR p->>'source_digest' IS DISTINCT FROM s->>'source_digest' OR p->>'gate_assignment_id' IS DISTINCT FROM s->'reviewers'->1->>'gate_assignment_id'
 OR p->>'decided_by' IS DISTINCT FROM s->'reviewers'->1->>'approver_user_id'
 OR p->>'state' IS DISTINCT FROM NEW.state OR p->>'digest' IS DISTINCT FROM NEW.digest
 OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest
 OR (p->>'decided_at')::timestamptz < (s->>'submitted_at')::timestamptz
 OR (NEW.state='APPROVED' AND p->'feedback' IS DISTINCT FROM 'null'::jsonb)
 OR (NEW.state='CHANGES_REQUESTED' AND NOT curve_sprd_shape(p->'feedback', '{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":16384},"media_type":{"const":"text/plain"}}}'::jsonb))

 THEN RAISE EXCEPTION 'LOCAL_REVIEW_DECISION_INVALID' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_lprs_insert BEFORE INSERT ON curve_local_prd_submission FOR EACH ROW EXECUTE FUNCTION curve_lprs_insert_guard();
CREATE TRIGGER curve_lprd_dec_insert BEFORE INSERT ON curve_local_prd_decision FOR EACH ROW EXECUTE FUNCTION curve_lprd_dec_insert_guard();
CREATE TRIGGER curve_lprs_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON curve_local_prd_submission FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_lprd_dec_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON curve_local_prd_decision FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
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
 SELECT catalog_digest INTO expected FROM curve_local_prd_review_coverage WHERE edition='CURVE_LOCAL_PRD_REVIEW_V1';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_local_prd_review_coverage)<>1 THEN
  RAISE EXCEPTION 'LOCAL_PRD_COMMAND_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
