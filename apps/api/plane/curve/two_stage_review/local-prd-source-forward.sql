CREATE TABLE curve_local_prd_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);
ALTER TABLE curve_local_prd_source ADD CONSTRAINT curve_lprd_init_scope_fk
 FOREIGN KEY (workspace_id,initiative_id) REFERENCES curve_initiative(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_local_prd_source ADD CONSTRAINT curve_lprd_predecessor_scope_fk
 FOREIGN KEY (workspace_id,initiative_id,predecessor_id) REFERENCES curve_local_prd_source(workspace_id,initiative_id,id) DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION curve_lprd_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p jsonb:=NEW.payload; previous curve_local_prd_source%ROWTYPE;
BEGIN
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT EXISTS(SELECT 1 FROM curve_initiative WHERE workspace_id=NEW.workspace_id AND id=NEW.initiative_id AND schema_version='1.2') THEN
  RAISE EXCEPTION 'LOCAL_PRD_INITIATIVE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(p)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p))<>13
  OR NOT p ?& ARRAY['schema_version','source_kind','id','workspace_id','initiative_id','version','predecessor_id','uploaded_by','uploaded_at','original','snapshot','normalization_schema_version','digest']
  OR p->>'schema_version' IS DISTINCT FROM 'curve.local-prd-source/v1-candidate' OR p->>'source_kind' IS DISTINCT FROM 'LOCAL_UPLOAD'
  OR p->>'normalization_schema_version' IS DISTINCT FROM 'curve.local-upload.normalized/v1-candidate'
  OR p->>'id' IS DISTINCT FROM NEW.id::text OR p->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text
  OR p->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR p->>'uploaded_by' IS DISTINCT FROM NEW.uploaded_by::text
  OR p->'version' IS DISTINCT FROM to_jsonb(NEW.version) OR p->>'predecessor_id' IS DISTINCT FROM NEW.predecessor_id::text
  OR p->>'digest' IS DISTINCT FROM NEW.digest OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest
  OR jsonb_typeof(p->'uploaded_at') IS DISTINCT FROM 'string' OR p->>'uploaded_at' !~ '^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?Z$'
 THEN RAISE EXCEPTION 'LOCAL_PRD_METADATA_INVALID' USING ERRCODE='23514'; END IF;
 IF NOT curve_sprd_shape(p->'original', '{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":10485760},"media_type":{"enum":["application/pdf","text/plain","text/markdown"]}}}'::jsonb)
 OR NOT curve_sprd_shape(p->'snapshot', '{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":62918656},"media_type":{"enum":["application/json"]}}}'::jsonb)
 OR p->'original'->>'object_id'=p->'snapshot'->>'object_id' THEN RAISE EXCEPTION 'LOCAL_PRD_REFERENCE_INVALID' USING ERRCODE='23514'; END IF;
 PERFORM (p->>'uploaded_at')::timestamptz;
 IF NEW.version=1 THEN
  IF NEW.predecessor_id IS NOT NULL THEN RAISE EXCEPTION 'LOCAL_PRD_CHAIN_INVALID' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO previous FROM curve_local_prd_source WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND id=NEW.predecessor_id;
  IF NOT FOUND OR previous.version<>NEW.version-1 OR previous.payload->'original'->>'object_id'=p->'original'->>'object_id'
   OR previous.payload->'snapshot'->>'object_id'=p->'snapshot'->>'object_id' THEN RAISE EXCEPTION 'LOCAL_PRD_CHAIN_INVALID' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_lprd_insert BEFORE INSERT ON curve_local_prd_source FOR EACH ROW EXECUTE FUNCTION curve_lprd_insert_guard();
CREATE TRIGGER curve_lprd_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON curve_local_prd_source FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
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
 SELECT catalog_digest INTO expected FROM curve_local_prd_coverage WHERE edition='CURVE_LOCAL_PRD_SOURCE_V1';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_local_prd_coverage)<>1 THEN
  RAISE EXCEPTION 'LOCAL_PRD_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
