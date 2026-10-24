CREATE OR REPLACE FUNCTION public.curve_sprd_scope_fence(p jsonb, acting_id uuid DEFAULT NULL::uuid)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE init curve_initiative; head curve_scope_proposal; rev curve_scope_proposal_revision;
 members jsonb; canonical_members jsonb; reviewers jsonb; member jsonb; actor uuid;
 source_record record; source_digest text;
BEGIN
 -- Same workspace and acting-human membership fence as ordinary policy.
 PERFORM 1 FROM workspaces WHERE id=(p->>'workspace_id')::uuid FOR UPDATE;
 PERFORM 1 FROM workspace_members WHERE workspace_id=(p->>'workspace_id')::uuid
  AND member_id=COALESCE(acting_id,(p->>'created_by')::uuid) ORDER BY id FOR UPDATE;
 SELECT * INTO init FROM curve_initiative WHERE workspace_id=(p->>'workspace_id')::uuid
  AND id=(p->>'initiative_id')::uuid FOR UPDATE;
 IF NOT FOUND OR init.product_id::text <> p->>'product_id' OR init.mode <> 'STANDALONE'
  OR init.state NOT IN ('ALIGNING','PRD_REVIEW') THEN
  RAISE EXCEPTION 'SCOPED_PRD_SCOPE_UNAVAILABLE' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM curve_gate_assignment WHERE workspace_id=init.workspace_id
  AND initiative_id=init.id ORDER BY id FOR UPDATE;
 PERFORM 1 FROM curve_product WHERE workspace_id=init.workspace_id AND id=init.product_id AND state='ACTIVE' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SCOPED_PRD_PRODUCT_UNAVAILABLE' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM users WHERE id IN (SELECT (r->>'approver_user_id')::uuid FROM jsonb_array_elements(p->'reviewers') r
  UNION SELECT COALESCE(acting_id,(p->>'created_by')::uuid)) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM workspace_members WHERE workspace_id=init.workspace_id AND member_id IN
  (SELECT (r->>'approver_user_id')::uuid FROM jsonb_array_elements(p->'reviewers') r
   UNION SELECT COALESCE(acting_id,(p->>'created_by')::uuid)) ORDER BY member_id FOR UPDATE;
 SELECT * INTO head FROM curve_scope_proposal WHERE workspace_id=init.workspace_id AND initiative_id=init.id FOR UPDATE;
 IF NOT FOUND OR head.id::text <> p->>'proposal_id' OR head.product_id <> init.product_id
  OR head.current_revision_id::text <> p->>'scope_revision_id' OR head.version <> (p->>'scope_revision')::bigint THEN
  RAISE EXCEPTION 'SCOPED_PRD_HEAD_MISMATCH' USING ERRCODE='23514';
 END IF;
 SELECT * INTO rev FROM curve_scope_proposal_revision WHERE workspace_id=init.workspace_id AND id=head.current_revision_id FOR UPDATE;
 IF NOT FOUND OR rev.proposal_id <> head.id OR rev.initiative_id <> init.id OR rev.product_id <> init.product_id
  OR rev.version <> head.version OR rev.membership_digest <> p->>'membership_digest' THEN
  RAISE EXCEPTION 'SCOPED_PRD_REVISION_MISMATCH' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM curve_scope_proposal_item WHERE workspace_id=init.workspace_id AND revision_id=rev.id ORDER BY id FOR UPDATE;
 SELECT jsonb_agg(jsonb_build_object('association_id',association_id::text,'association_version',association_version,
  'provider_installation_id',provider_installation_id::text,'source_project_id',source_project_id::text,
  'source_issue_id',source_issue_id::text,'purpose',purpose) ORDER BY source_issue_id),
  jsonb_agg(jsonb_build_object('association_id',association_id::text,'association_version',association_version,
  'provider_installation_id',provider_installation_id::text,'source_project_id',source_project_id::text,
  'source_issue_id',source_issue_id::text,'purpose',purpose,'source_observed_at',curve_sprd_instant(source_observed_at),
  'source_version',source_version,'source_fingerprint',source_fingerprint) ORDER BY source_issue_id)
  INTO members, canonical_members FROM curve_scope_proposal_item WHERE workspace_id=init.workspace_id AND revision_id=rev.id;
 IF members IS NULL OR jsonb_array_length(members) <> rev.item_count
  OR rev.item_count NOT BETWEEN 1 AND 100
  OR rev.delivery_count <> (SELECT count(*) FROM jsonb_array_elements(members) m WHERE m->>'purpose'='PROPOSED_DELIVERY')
  OR curve_sprd_digest(canonical_members) <> rev.membership_digest
  OR members IS DISTINCT FROM (SELECT jsonb_agg(m - ARRAY['source_version','source_fingerprint'] ORDER BY m->>'source_issue_id')
                              FROM jsonb_array_elements(p->'members') m)
  OR jsonb_array_length(p->'members') <> rev.item_count
  OR p->'members' IS DISTINCT FROM (SELECT jsonb_agg(m ORDER BY m->>'source_issue_id') FROM jsonb_array_elements(p->'members') m) THEN
  RAISE EXCEPTION 'SCOPED_PRD_MEMBERS_MISMATCH' USING ERRCODE='23514';
 END IF;
 -- Only observation payloads reach this function; every later sidecar refers back
 -- to its exact immutable observation, while current source state is rechecked.
 SELECT jsonb_agg(jsonb_build_object('gate_assignment_id',g.id::text,'gate_type',g.gate_type,
  'approver_user_id',g.approver_user_id::text) ORDER BY g.gate_type) INTO reviewers
 FROM curve_gate_assignment g JOIN users u ON u.id=g.approver_user_id
  JOIN workspace_members w ON w.member_id=g.approver_user_id AND w.workspace_id=g.workspace_id
 WHERE g.workspace_id=init.workspace_id AND g.initiative_id=init.id AND g.valid_from<=clock_timestamp()
  AND (g.valid_until IS NULL OR g.valid_until>clock_timestamp()) AND u.is_active AND NOT u.is_bot
  AND w.is_active AND w.deleted_at IS NULL AND w.role IN (5,15,20);
 IF reviewers IS DISTINCT FROM p->'reviewers' OR jsonb_array_length(reviewers) <> 3
  OR (init.risk_tier IN ('STANDARD','HIGH') AND
      (SELECT count(DISTINCT r->>'approver_user_id') FROM jsonb_array_elements(reviewers) r) <> 3) THEN
  RAISE EXCEPTION 'SCOPED_PRD_REVIEWERS_MISMATCH' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM curve_project_association WHERE id IN
  (SELECT (m->>'association_id')::uuid FROM jsonb_array_elements(members) m) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM projects WHERE id IN
  (SELECT (m->>'source_project_id')::uuid FROM jsonb_array_elements(members) m) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM project_members WHERE project_id IN
  (SELECT (m->>'source_project_id')::uuid FROM jsonb_array_elements(members) m) ORDER BY project_id,member_id FOR UPDATE;
 PERFORM 1 FROM issues WHERE id IN
  (SELECT (m->>'source_issue_id')::uuid FROM jsonb_array_elements(members) m) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM states WHERE id IN
  (SELECT state_id FROM issues WHERE id IN
   (SELECT (m->>'source_issue_id')::uuid FROM jsonb_array_elements(members) m)) ORDER BY id FOR UPDATE;
 FOR member IN SELECT value FROM jsonb_array_elements(p->'members') LOOP
  SELECT i.id, i.workspace_id, i.project_id, i.parent_id, i.state_id, i.created_by_id, i.updated_at,
   s."group" AS state_group, s.updated_at AS state_updated_at INTO source_record
  FROM issues i JOIN projects pr ON pr.id=i.project_id JOIN states s ON s.id=i.state_id
   JOIN curve_project_association a ON a.id=(member->>'association_id')::uuid
  WHERE i.id=(member->>'source_issue_id')::uuid AND i.workspace_id=init.workspace_id
   AND i.project_id=(member->>'source_project_id')::uuid AND i.deleted_at IS NULL AND i.archived_at IS NULL AND NOT i.is_draft
   AND pr.workspace_id=init.workspace_id AND pr.deleted_at IS NULL AND pr.archived_at IS NULL
   AND s.workspace_id=init.workspace_id AND s.project_id=pr.id AND s.deleted_at IS NULL AND s."group"<>'triage'
   AND a.workspace_id=init.workspace_id AND a.product_id=init.product_id AND a.state='ACTIVE'
   AND a.version=(member->>'association_version')::bigint AND a.provider_installation_id::text=member->>'provider_installation_id'
   AND a.source_project_id=pr.id;
  IF NOT FOUND THEN RAISE EXCEPTION 'SCOPED_PRD_SOURCE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
  source_digest := curve_sprd_digest(jsonb_build_object('id',source_record.id::text,'workspace_id',source_record.workspace_id::text,
   'project_id',source_record.project_id::text,'parent_id',source_record.parent_id::text,'state_id',source_record.state_id::text,
   'created_by_id',source_record.created_by_id::text,'archived_at',NULL,'deleted_at',NULL,'is_draft','False',
   'updated_at',replace(curve_sprd_instant(source_record.updated_at),'T',' '),'state_group',source_record.state_group,
   'state_updated_at',curve_sprd_instant(source_record.state_updated_at)));
  IF member->>'source_version' IS DISTINCT FROM curve_sprd_instant(source_record.updated_at)
   OR member->>'source_fingerprint' IS DISTINCT FROM source_digest THEN
   RAISE EXCEPTION 'SCOPED_PRD_SOURCE_CHANGED' USING ERRCODE='23514';
  END IF;
  FOR actor IN SELECT (r->>'approver_user_id')::uuid FROM jsonb_array_elements(reviewers) r
   UNION SELECT COALESCE(acting_id,(p->>'created_by')::uuid) LOOP
   IF NOT EXISTS (SELECT 1 FROM project_members m JOIN projects pr ON pr.id=m.project_id
    JOIN users u ON u.id=m.member_id JOIN workspace_members w ON w.member_id=m.member_id AND w.workspace_id=m.workspace_id
    WHERE m.workspace_id=init.workspace_id AND m.project_id=source_record.project_id AND m.member_id=actor
     AND m.deleted_at IS NULL AND m.is_active AND m.role IN (5,15,20) AND u.is_active AND NOT u.is_bot
     AND w.is_active AND w.deleted_at IS NULL AND w.role IN (5,15,20)
     AND (m.role<>5 OR pr.guest_view_all_features OR source_record.created_by_id=actor)) THEN
    RAISE EXCEPTION 'SCOPED_PRD_SOURCE_UNAVAILABLE' USING ERRCODE='23514';
   END IF;
  END LOOP;
 END LOOP;
END $function$;

CREATE OR REPLACE FUNCTION public.curve_sprd_record_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE p jsonb:=NEW.payload; row_json jsonb:=to_jsonb(NEW); k text; obs curve_scoped_prd_observation;
 base curve_prd_readiness_record; ready curve_scoped_prd_readiness; subj curve_scoped_prd_subject;
 cp curve_document_checkpoint; dec curve_prd_review_decision; cmd curve_scoped_prd_accepted_command;
 op curve_operation; init curve_initiative; schema_name text; identity_members jsonb; acting_id uuid;
BEGIN
 schema_name := replace(TG_TABLE_NAME, 'curve_scoped_prd_', '');
 IF NOT curve_sprd_shape(p, curve_sprd_schema(schema_name))
  OR octet_length(curve_sprd_canonical(p))>262144
  OR p->>'digest' IS DISTINCT FROM NEW.digest OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest THEN
  RAISE EXCEPTION 'SCOPED_PRD_RECORD_INVALID' USING ERRCODE='23514';
 END IF;
 FOR k IN SELECT jsonb_object_keys(row_json - ARRAY['payload','recorded_at','submission_operation_id','review_operation_id']) LOOP
  IF row_json->k IS DISTINCT FROM p->k THEN
   RAISE EXCEPTION 'SCOPED_PRD_RECORD_SUBSTITUTION' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF row_json ? 'recorded_at' AND ((p->>'recorded_at')::timestamptz IS DISTINCT FROM (row_json->>'recorded_at')::timestamptz
  OR (row_json->>'recorded_at')::timestamptz>clock_timestamp()) THEN
  RAISE EXCEPTION 'SCOPED_PRD_TIME_INVALID' USING ERRCODE='23514';
 END IF;
 -- Start at the same common workspace/membership fence as application policy.
 acting_id := (row_json->>'created_by')::uuid;
 IF schema_name='readiness' THEN
  SELECT (pd.subject->>'actor_id')::uuid INTO acting_id FROM curve_prd_readiness_record b
   JOIN curve_policy_decision pd ON pd.id=b.policy_decision_id
   WHERE b.workspace_id=NEW.workspace_id AND b.initiative_id=NEW.initiative_id AND b.id=NEW.base_readiness_id;
 END IF;
 PERFORM 1 FROM workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 PERFORM 1 FROM workspace_members WHERE workspace_id=NEW.workspace_id AND member_id=acting_id ORDER BY id FOR UPDATE;
 SELECT * INTO init FROM curve_initiative WHERE workspace_id=NEW.workspace_id AND id=NEW.initiative_id FOR UPDATE;
 IF NOT FOUND OR init.product_id<>NEW.product_id THEN
  RAISE EXCEPTION 'SCOPED_PRD_SCOPE_MISMATCH' USING ERRCODE='23514';
 END IF;
 IF schema_name='observation' THEN
  IF init.version<>(p->>'initiative_version')::bigint OR NEW.recorded_at<init.created_at THEN
   RAISE EXCEPTION 'SCOPED_PRD_VERSION_CONFLICT' USING ERRCODE='23514';
  END IF;
  PERFORM curve_sprd_scope_fence(p);
  RETURN NEW;
 END IF;
 IF schema_name='decision' THEN
  SELECT * INTO subj FROM curve_scoped_prd_subject WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=NEW.scoped_subject_id;
  IF NOT FOUND OR subj.product_id<>NEW.product_id OR subj.digest<>p->>'scoped_subject_digest'
   OR subj.checkpoint_id IS DISTINCT FROM init.current_prd_checkpoint_id OR init.state<>'PRD_REVIEW' THEN
   RAISE EXCEPTION 'SCOPED_PRD_SUBJECT_MISMATCH' USING ERRCODE='23514';
  END IF;
  SELECT * INTO obs FROM curve_scoped_prd_observation WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=subj.observation_set_id;
  PERFORM curve_sprd_scope_fence(obs.payload,NEW.created_by);
  SELECT * INTO dec FROM curve_prd_review_decision WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=NEW.decision_id;
  IF NOT FOUND OR dec.checkpoint_id<>subj.checkpoint_id OR dec.state<>p->>'state'
   OR dec.decided_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text)
   OR NEW.recorded_at<dec.decided_at
   OR NOT curve_sprd_created_here('curve_prd_review_decision',NEW.workspace_id,dec.id) THEN
   RAISE EXCEPTION 'SCOPED_PRD_DECISION_PROVENANCE_INVALID' USING ERRCODE='23514';
  END IF;
  SELECT * INTO cmd FROM curve_scoped_prd_accepted_command WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND operation_id=NEW.review_operation_id;
  IF NOT FOUND OR cmd.action IS DISTINCT FROM (CASE dec.state WHEN 'APPROVED' THEN 'CURVE.PRD.APPROVE'
    WHEN 'CHANGES_REQUESTED' THEN 'CURVE.PRD.REQUEST_CHANGES' ELSE 'CURVE.PRD.REJECT' END)
   OR cmd.actor_id<>NEW.created_by OR cmd.expected_version<>init.version
   OR cmd.subject->>'scoped_subject_id'<>subj.id::text OR cmd.subject->>'scoped_subject_digest'<>subj.digest
   OR cmd.subject->>'gate_assignment_id'<>dec.gate_assignment_id::text
   OR cmd.rationale_object_id IS DISTINCT FROM dec.rationale_object_id
   OR cmd.rationale_digest IS DISTINCT FROM dec.rationale_digest
   OR cmd.rationale_size_bytes IS DISTINCT FROM dec.rationale_size_bytes
   OR cmd.rationale_access_envelope_id IS DISTINCT FROM dec.rationale_access_envelope_id
   OR cmd.rationale_retention_policy_version_id::text IS DISTINCT FROM dec.rationale_retention_policy_version_id THEN
   RAISE EXCEPTION 'SCOPED_PRD_DECISION_COMMAND_MISMATCH' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO obs FROM curve_scoped_prd_observation WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=NEW.observation_set_id;
  IF NOT FOUND OR obs.product_id<>NEW.product_id OR obs.digest<>p->>'observation_digest'
   OR EXISTS(SELECT 1 FROM unnest(ARRAY['proposal_id','scope_revision_id','scope_revision','membership_digest']) key
             WHERE p->key IS DISTINCT FROM obs.payload->key) THEN
   RAISE EXCEPTION 'SCOPED_PRD_OBSERVATION_MISMATCH' USING ERRCODE='23514';
  END IF;
  IF schema_name='readiness' THEN
   SELECT * INTO base FROM curve_prd_readiness_record WHERE workspace_id=NEW.workspace_id
    AND initiative_id=NEW.initiative_id AND id=NEW.base_readiness_id;
   IF NOT FOUND OR curve_sprd_digest(base.payload)<>p->>'base_readiness_digest' OR base.payload->>'status'<>'READY'
    OR NOT curve_sprd_created_here('curve_prd_readiness_record',NEW.workspace_id,base.id) THEN
    RAISE EXCEPTION 'SCOPED_PRD_READINESS_PROVENANCE_INVALID' USING ERRCODE='23514';
   END IF;
   PERFORM curve_sprd_scope_fence(obs.payload,
    (SELECT (subject->>'actor_id')::uuid FROM curve_policy_decision WHERE id=base.policy_decision_id));
   RETURN NEW;
  END IF;
  PERFORM curve_sprd_scope_fence(obs.payload,NEW.created_by);
  SELECT * INTO ready FROM curve_scoped_prd_readiness WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=NEW.scoped_readiness_id;
  IF NOT FOUND OR ready.product_id<>NEW.product_id OR ready.observation_set_id<>obs.id
   OR ready.digest<>p->>'scoped_readiness_digest'
   OR NOT curve_sprd_created_here('curve_scoped_prd_readiness',NEW.workspace_id,ready.id) THEN
   RAISE EXCEPTION 'SCOPED_PRD_READINESS_MISMATCH' USING ERRCODE='23514';
  END IF;
  SELECT * INTO base FROM curve_prd_readiness_record WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=ready.base_readiness_id;
  SELECT * INTO cp FROM curve_document_checkpoint WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=NEW.checkpoint_id;
  IF NOT FOUND OR cp.artifact_version_id::text<>p->>'artifact_version_id' OR cp.content_digest<>p->>'content_digest'
   OR cp.provider_version<>p->>'provider_version' OR cp.evidence_snapshot_id::text<>p->>'evidence_snapshot_id'
   OR cp.submitted_or_approved_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text)
   OR NEW.recorded_at<date_trunc('milliseconds',cp.recorded_at) OR base.binding_id<>cp.external_document_binding_id
   OR base.id<>cp.completeness_check_id OR base.payload->>'evidence_snapshot_id'<>cp.evidence_snapshot_id::text
   OR base.payload->>'provider_version'<>cp.provider_version OR base.payload->>'content_digest'<>cp.content_digest
   OR NOT curve_sprd_created_here('curve_document_checkpoint',NEW.workspace_id,cp.id)
   OR NOT curve_sprd_created_here('curve_prd_readiness_record',NEW.workspace_id,base.id) THEN
   RAISE EXCEPTION 'SCOPED_PRD_CHECKPOINT_PROVENANCE_INVALID' USING ERRCODE='23514';
  END IF;
  SELECT jsonb_agg(m - ARRAY['source_version','source_fingerprint'] ORDER BY m->>'source_issue_id')
   INTO identity_members FROM jsonb_array_elements(obs.payload->'members') m;
  IF p->'members' IS DISTINCT FROM identity_members THEN
   RAISE EXCEPTION 'SCOPED_PRD_SUBJECT_MEMBERS_MISMATCH' USING ERRCODE='23514';
  END IF;
  SELECT * INTO cmd FROM curve_scoped_prd_accepted_command WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND operation_id=NEW.submission_operation_id;
  IF NOT FOUND OR cmd.action<>'CURVE.PRD.SUBMIT' OR cmd.actor_id<>NEW.created_by OR cmd.expected_version<>init.version
   OR cmd.subject->>'observation_set_id'<>obs.id::text OR cmd.subject->>'observation_digest'<>obs.digest
   OR cmd.subject->>'external_document_binding_id'<>cp.external_document_binding_id::text
   OR cmd.subject->>'completeness_check_id'<>cp.completeness_check_id::text
   OR cmd.subject->>'evidence_snapshot_id' IS DISTINCT FROM base.payload->>'evidence_snapshot_id'
   OR (base.payload->>'initiative_version')::bigint<>cmd.expected_version THEN
   RAISE EXCEPTION 'SCOPED_PRD_SUBMISSION_COMMAND_MISMATCH' USING ERRCODE='23514';
  END IF;
 END IF;
 SELECT * INTO op FROM curve_operation WHERE workspace_id=NEW.workspace_id AND id=cmd.operation_id FOR UPDATE;
 IF NOT FOUND OR op.status<>'RUNNING' OR op.command_type<>replace(cmd.action,'CURVE.PRD.','SCOPED_PRD_V1_')
  OR op.target IS DISTINCT FROM jsonb_build_object('resource_type','INITIATIVE','resource_id',NEW.initiative_id::text,
   'resource_version',cmd.expected_version) OR op.created_by->>'actor_id'<>cmd.actor_id::text THEN
  RAISE EXCEPTION 'SCOPED_PRD_OPERATION_MISMATCH' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION public.curve_sprd_command_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE init curve_initiative; op curve_operation; cp curve_document_checkpoint; gate curve_gate_assignment;
 obs curve_scoped_prd_observation; subj curve_scoped_prd_subject; schema_name text;
BEGIN
 PERFORM 1 FROM workspaces WHERE id=NEW.workspace_id FOR UPDATE;
 PERFORM 1 FROM workspace_members WHERE workspace_id=NEW.workspace_id AND member_id=NEW.actor_id ORDER BY id FOR UPDATE;
 SELECT * INTO init FROM curve_initiative WHERE workspace_id=NEW.workspace_id AND id=NEW.initiative_id FOR UPDATE;
 IF NOT FOUND OR init.version<>NEW.expected_version THEN
  RAISE EXCEPTION 'SCOPED_PRD_COMMAND_VERSION_CONFLICT' USING ERRCODE='23514';
 END IF;
 schema_name:=CASE NEW.action WHEN 'CURVE.PRD.SUBMIT' THEN 'submit'
  WHEN 'CURVE.PRD.APPROVE' THEN 'approve' ELSE 'return-for-revision' END;
 IF NOT curve_sprd_shape(NEW.subject,curve_sprd_schema(schema_name))
  OR octet_length(curve_sprd_canonical(NEW.subject))>65536
  OR NEW.edition<>'curve.scoped-prd/v1-candidate' THEN
  RAISE EXCEPTION 'SCOPED_PRD_COMMAND_SUBJECT_INVALID' USING ERRCODE='23514';
 END IF;
 IF NEW.action='CURVE.PRD.SUBMIT' THEN
  IF init.state NOT IN ('ALIGNING','PRD_REVIEW')
   OR num_nonnulls(NEW.rationale_object_id,NEW.rationale_digest,NEW.rationale_size_bytes,
    NEW.rationale_access_envelope_id,NEW.rationale_retention_policy_version_id)<>0 THEN
   RAISE EXCEPTION 'SCOPED_PRD_COMMAND_SUBJECT_INVALID' USING ERRCODE='23514';
  END IF;
  SELECT * INTO obs FROM curve_scoped_prd_observation WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=(NEW.subject->>'observation_set_id')::uuid;
  IF NOT FOUND OR obs.digest<>NEW.subject->>'observation_digest'
   OR EXISTS(SELECT 1 FROM unnest(ARRAY['proposal_id','scope_revision_id','scope_revision','membership_digest']) key
             WHERE NEW.subject->key IS DISTINCT FROM obs.payload->key)
   OR NOT EXISTS(SELECT 1 FROM curve_external_document_binding WHERE workspace_id=NEW.workspace_id
      AND initiative_id=NEW.initiative_id AND id=(NEW.subject->>'external_document_binding_id')::uuid)
   OR NEW.request_digest IS DISTINCT FROM curve_sprd_digest(jsonb_build_object('edition',NEW.edition,'action',NEW.action,
        'expected_version',NEW.expected_version,'payload',NEW.subject)) THEN
   RAISE EXCEPTION 'SCOPED_PRD_COMMAND_OBSERVATION_MISMATCH' USING ERRCODE='23514';
  END IF;
 ELSE
  IF init.state<>'PRD_REVIEW' OR num_nonnulls(NEW.rationale_object_id,NEW.rationale_digest,NEW.rationale_size_bytes,
   NEW.rationale_access_envelope_id,NEW.rationale_retention_policy_version_id)<>5
   OR NEW.rationale_digest !~ '^sha256:[0-9a-f]{64}$' OR NEW.rationale_size_bytes NOT BETWEEN 1 AND 8000
   OR (NEW.action='CURVE.PRD.REQUEST_CHANGES' AND NEW.subject->>'decision'<>'CHANGES_REQUESTED')
   OR (NEW.action='CURVE.PRD.REJECT' AND NEW.subject->>'decision'<>'REJECTED') THEN
   RAISE EXCEPTION 'SCOPED_PRD_COMMAND_RATIONALE_INVALID' USING ERRCODE='23514';
  END IF;
  SELECT * INTO subj FROM curve_scoped_prd_subject WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=(NEW.subject->>'scoped_subject_id')::uuid;
  IF NOT FOUND OR subj.digest<>NEW.subject->>'scoped_subject_digest'
   OR subj.checkpoint_id IS DISTINCT FROM init.current_prd_checkpoint_id THEN
   RAISE EXCEPTION 'SCOPED_PRD_COMMAND_SUBJECT_MISMATCH' USING ERRCODE='23514';
  END IF;
  SELECT * INTO obs FROM curve_scoped_prd_observation WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=subj.observation_set_id;
  SELECT * INTO cp FROM curve_document_checkpoint WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=(NEW.subject->>'checkpoint_id')::uuid;
  IF NOT FOUND OR cp.id IS DISTINCT FROM init.current_prd_checkpoint_id OR cp.id<>subj.checkpoint_id
   OR cp.artifact_version_id::text<>NEW.subject->>'artifact_version_id'
   OR cp.evidence_snapshot_id::text<>NEW.subject->>'evidence_snapshot_id'
   OR cp.content_digest<>NEW.subject->>'content_digest' OR cp.provider_version<>NEW.subject->>'provider_version'
   OR init.risk_tier<>NEW.subject->>'confirmed_risk_tier' THEN
   RAISE EXCEPTION 'SCOPED_PRD_COMMAND_CHECKPOINT_MISMATCH' USING ERRCODE='23514';
  END IF;
  SELECT * INTO gate FROM curve_gate_assignment WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND id=(NEW.subject->>'gate_assignment_id')::uuid;
  IF NOT FOUND OR gate.gate_type<>'PRD_APPROVAL' OR gate.approver_user_id<>NEW.actor_id THEN
   RAISE EXCEPTION 'SCOPED_PRD_COMMAND_ASSIGNMENT_MISMATCH' USING ERRCODE='23514';
  END IF;
 END IF;
 PERFORM curve_sprd_scope_fence(obs.payload,NEW.actor_id);
 SELECT * INTO op FROM curve_operation WHERE workspace_id=NEW.workspace_id AND id=NEW.operation_id FOR UPDATE;
 IF NOT FOUND OR op.operation_type<>'WORKFLOW_COMMAND' OR op.status<>'PENDING'
  OR op.command_type<>replace(NEW.action,'CURVE.PRD.','SCOPED_PRD_V1_')
  OR op.target IS DISTINCT FROM jsonb_build_object('resource_type','INITIATIVE','resource_id',NEW.initiative_id::text,
    'resource_version',NEW.expected_version)
  OR op.created_by IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',NEW.actor_id::text)
  OR (op.effective_principal IS NOT NULL AND op.effective_principal IS DISTINCT FROM op.created_by)
  OR NOT isfinite(NEW.accepted_at) OR NEW.accepted_at<op.created_at OR NEW.accepted_at>clock_timestamp() THEN
  RAISE EXCEPTION 'SCOPED_PRD_COMMAND_OPERATION_MISMATCH' USING ERRCODE='23514';
 END IF;
 PERFORM 1 FROM curve_policy_decision WHERE workspace_id=NEW.workspace_id
  AND id::text=op.policy_version_ref->>'resource_id' AND op.policy_version_ref->>'resource_type'='POLICY_DECISION'
  AND action=NEW.action AND effect='ALLOW' AND policy_key='CURVE_PRD_POLICY'
  AND resource_type='INITIATIVE' AND resource_id=NEW.initiative_id AND resource_version=NEW.expected_version
  AND subject=op.created_by AND effective_principal=op.created_by;
 IF NOT FOUND THEN RAISE EXCEPTION 'SCOPED_PRD_COMMAND_POLICY_MISMATCH' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $function$;

CREATE OR REPLACE FUNCTION public.curve_sprd_verify_commit()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE op curve_operation; cmd curve_scoped_prd_accepted_command; s curve_scoped_prd_subject;
 d curve_scoped_prd_decision; init curve_initiative; completion_operation_id uuid; event curve_domain_event;
 policy curve_policy_decision; audit curve_audit_event;
BEGIN
 IF TG_TABLE_NAME='curve_scoped_prd_observation' THEN
  SELECT * INTO event FROM curve_domain_event WHERE workspace_id=NEW.workspace_id
   AND aggregate_type='SCOPED_PRD_OBSERVATION' AND aggregate_id=NEW.id AND aggregate_version=1 AND sequence=1;
  IF NOT FOUND OR event.event_type<>'CURVE.SCOPED_PRD.OBSERVATION_RECORDED'
   OR NOT curve_sprd_shape(event.payload,curve_sprd_schema('observed-event'))
   OR event.payload->>'observation_id'<>NEW.id::text OR event.payload->>'observation_digest'<>NEW.digest
   OR event.payload->>'initiative_id'<>NEW.initiative_id::text
   OR event.actor IS DISTINCT FROM jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text)
   OR event.effective_principal IS DISTINCT FROM event.actor
   OR NOT curve_sprd_created_here('curve_domain_event',NEW.workspace_id,event.id)
   OR NOT EXISTS(SELECT 1 FROM curve_outbox_event WHERE workspace_id=NEW.workspace_id AND event_id=event.id
      AND destination='CURVE_SCOPED_PRD_METADATA_V1' AND curve_sprd_created_here('curve_outbox_event',workspace_id,id)) THEN
   RAISE EXCEPTION 'SCOPED_PRD_OBSERVATION_EVENT_REQUIRED' USING ERRCODE='23514';
  END IF;
  SELECT * INTO policy FROM curve_policy_decision WHERE workspace_id=NEW.workspace_id
   AND id=(event.payload->>'policy_decision_id')::uuid;
  IF NOT FOUND OR policy.action<>'CURVE.PRD.SUBMIT' OR policy.effect<>'ALLOW' OR policy.policy_key<>'CURVE_PRD_POLICY'
   OR policy.resource_type<>'INITIATIVE' OR policy.resource_id<>NEW.initiative_id
   OR policy.resource_version<>(NEW.payload->>'initiative_version')::bigint
   OR policy.subject IS DISTINCT FROM event.actor OR policy.effective_principal IS DISTINCT FROM event.actor
   OR NOT curve_sprd_created_here('curve_policy_decision',NEW.workspace_id,policy.id)
   OR NOT EXISTS(SELECT 1 FROM curve_audit_event WHERE workspace_id=NEW.workspace_id
      AND target_type='SCOPED_PRD_OBSERVATION' AND target_id=NEW.id AND outcome='SUCCEEDED'
      AND action='CURVE.SCOPED_PRD.OBSERVE' AND actor=event.actor
      AND policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',policy.id::text,'resource_version',1)
      AND curve_sprd_created_here('curve_audit_event',workspace_id,id))
   OR NOT EXISTS(SELECT 1 FROM curve_idempotency_record WHERE workspace_id=NEW.workspace_id
      AND principal_scope='HUMAN:'||NEW.created_by::text
      AND command_scope='SCOPED_PRD_V1_OBSERVE:'||NEW.initiative_id::text
      AND key_digest=event.idempotency_key_digest AND state='COMPLETED' AND response_status=201
      AND response_resource_ref=jsonb_build_object('resource_type','SCOPED_PRD_OBSERVATION','resource_id',NEW.id::text,'resource_version',1)) THEN
   RAISE EXCEPTION 'SCOPED_PRD_OBSERVATION_AUDIT_REQUIRED' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 ELSIF TG_TABLE_NAME='curve_document_checkpoint' THEN
  IF EXISTS(SELECT 1 FROM curve_scope_proposal h JOIN curve_scope_proposal_item i
    ON i.workspace_id=h.workspace_id AND i.revision_id=h.current_revision_id
    WHERE h.workspace_id=NEW.workspace_id AND h.initiative_id=NEW.initiative_id AND (i.purpose='PROPOSED_DELIVERY' OR EXISTS(SELECT 1 FROM curve_scope_proposal_revision r WHERE r.workspace_id=h.workspace_id AND r.id=h.current_revision_id AND r.policy_edition='REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1')))
   AND NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject WHERE workspace_id=NEW.workspace_id
    AND initiative_id=NEW.initiative_id AND checkpoint_id=NEW.id
    AND curve_sprd_created_here('curve_scoped_prd_subject',workspace_id,id)) THEN
   RAISE EXCEPTION 'SCOPED_PRD_CHECKPOINT_SIDECAR_REQUIRED' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 ELSIF TG_TABLE_NAME='curve_prd_review_decision' THEN
  IF EXISTS(SELECT 1 FROM curve_scoped_prd_subject WHERE workspace_id=NEW.workspace_id
    AND initiative_id=NEW.initiative_id AND checkpoint_id=NEW.checkpoint_id)
   AND NOT EXISTS(SELECT 1 FROM curve_scoped_prd_decision WHERE workspace_id=NEW.workspace_id
    AND initiative_id=NEW.initiative_id AND decision_id=NEW.id
    AND curve_sprd_created_here('curve_scoped_prd_decision',workspace_id,id)) THEN
   RAISE EXCEPTION 'SCOPED_PRD_DECISION_SIDECAR_REQUIRED' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 ELSIF TG_TABLE_NAME='curve_scoped_prd_readiness' THEN
  IF NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject WHERE workspace_id=NEW.workspace_id
   AND initiative_id=NEW.initiative_id AND scoped_readiness_id=NEW.id
   AND curve_sprd_created_here('curve_scoped_prd_subject',workspace_id,id)) THEN
   RAISE EXCEPTION 'SCOPED_PRD_READINESS_SUBJECT_REQUIRED' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 ELSIF TG_TABLE_NAME='curve_scoped_prd_subject' THEN completion_operation_id:=NEW.submission_operation_id;
 ELSIF TG_TABLE_NAME='curve_scoped_prd_decision' THEN completion_operation_id:=NEW.review_operation_id;
 ELSIF TG_TABLE_NAME='curve_scoped_prd_accepted_command' THEN completion_operation_id:=NEW.operation_id;
 ELSE
  IF NEW.command_type NOT LIKE 'SCOPED_PRD_V1_%' THEN RETURN NULL; END IF;
  completion_operation_id:=NEW.id;
 END IF;
 SELECT * INTO op FROM curve_operation WHERE workspace_id=NEW.workspace_id AND id=completion_operation_id;
 SELECT * INTO cmd FROM curve_scoped_prd_accepted_command WHERE workspace_id=NEW.workspace_id AND operation_id=op.id;
 IF NOT FOUND OR op.command_type<>replace(cmd.action,'CURVE.PRD.','SCOPED_PRD_V1_') THEN
  RAISE EXCEPTION 'SCOPED_PRD_OPERATION_COMMAND_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME IN ('curve_scoped_prd_subject','curve_scoped_prd_decision') AND op.status<>'SUCCEEDED' THEN
  RAISE EXCEPTION 'SCOPED_PRD_ATOMIC_COMPLETION_REQUIRED' USING ERRCODE='23514';
 END IF;
 IF op.status<>'SUCCEEDED' THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM curve_domain_event e JOIN curve_outbox_event o
   ON o.workspace_id=e.workspace_id AND o.event_id=e.id
   WHERE e.workspace_id=op.workspace_id AND e.aggregate_type='OPERATION' AND e.aggregate_id=op.id
    AND e.aggregate_version=op.aggregate_version AND e.event_type='curve.operation.state_changed'
    AND e.payload->>'status'='SUCCEEDED' AND o.destination='CURVE_SCOPED_PRD_CANDIDATE_V1'
    AND curve_sprd_created_here('curve_domain_event',e.workspace_id,e.id)
    AND curve_sprd_created_here('curve_outbox_event',o.workspace_id,o.id))
  OR NOT EXISTS(SELECT 1 FROM curve_audit_event a JOIN curve_policy_decision p
    ON p.workspace_id=a.workspace_id AND p.id::text=a.policy_decision_ref->>'resource_id'
   WHERE a.workspace_id=op.workspace_id AND a.action=cmd.action||'.COMPLETION' AND a.outcome='SUCCEEDED'
    AND a.target_type='INITIATIVE' AND a.target_id=cmd.initiative_id AND a.target_ref=op.result_ref
    AND a.actor=op.created_by AND a.causation_id=op.id::text
    AND p.action=cmd.action AND p.effect='ALLOW' AND p.policy_key='CURVE_PRD_POLICY'
    AND p.resource_type='INITIATIVE' AND p.resource_id=cmd.initiative_id AND p.resource_version=cmd.expected_version
    AND p.subject=op.created_by AND p.effective_principal=op.created_by
    AND curve_sprd_created_here('curve_audit_event',a.workspace_id,a.id)
    AND curve_sprd_created_here('curve_policy_decision',p.workspace_id,p.id)) THEN
  RAISE EXCEPTION 'SCOPED_PRD_ATOMIC_AUDIT_REQUIRED' USING ERRCODE='23514';
 END IF;
 SELECT * INTO init FROM curve_initiative WHERE workspace_id=op.workspace_id AND id=cmd.initiative_id;
 IF op.result_ref IS DISTINCT FROM jsonb_build_object('resource_type','INITIATIVE','resource_id',cmd.initiative_id::text,
    'resource_version',cmd.expected_version+1) THEN
  RAISE EXCEPTION 'SCOPED_PRD_OPERATION_RESULT_MISMATCH' USING ERRCODE='23514';
 END IF;
 IF cmd.action='CURVE.PRD.SUBMIT' THEN
  SELECT * INTO s FROM curve_scoped_prd_subject WHERE workspace_id=op.workspace_id
   AND initiative_id=cmd.initiative_id AND submission_operation_id=op.id;
  IF NOT FOUND OR NOT curve_sprd_created_here('curve_scoped_prd_subject',s.workspace_id,s.id)
   OR init.current_prd_checkpoint_id IS DISTINCT FROM s.checkpoint_id OR init.version<>cmd.expected_version+1
   OR init.state<>'PRD_REVIEW' OR init.controlling_prd_decision_id IS NOT NULL OR init.pending_scope_reopening_id IS NOT NULL THEN
   RAISE EXCEPTION 'SCOPED_PRD_SUBMISSION_INCOMPLETE' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO d FROM curve_scoped_prd_decision WHERE workspace_id=op.workspace_id
   AND initiative_id=cmd.initiative_id AND review_operation_id=op.id;
  IF NOT FOUND OR NOT curve_sprd_created_here('curve_scoped_prd_decision',d.workspace_id,d.id)
   OR init.controlling_prd_decision_id IS DISTINCT FROM d.decision_id OR init.version<>cmd.expected_version+1
   OR init.state IS DISTINCT FROM (CASE WHEN cmd.action='CURVE.PRD.APPROVE' THEN 'PLANNING' ELSE 'ALIGNING' END) THEN
   RAISE EXCEPTION 'SCOPED_PRD_REVIEW_INCOMPLETE' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NULL;
END $function$;

CREATE OR REPLACE FUNCTION public.curve_sprd_operation_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
 IF OLD.command_type LIKE 'SCOPED_PRD_V1_%' OR EXISTS
  (SELECT 1 FROM curve_scoped_prd_accepted_command WHERE operation_id=OLD.id) THEN
  IF ROW(NEW.id,NEW.workspace_id,NEW.operation_type,NEW.command_type,NEW.target,NEW.created_by,
         NEW.effective_principal,NEW.idempotency_key_digest,NEW.created_at)
    IS DISTINCT FROM ROW(OLD.id,OLD.workspace_id,OLD.operation_type,OLD.command_type,OLD.target,OLD.created_by,
         OLD.effective_principal,OLD.idempotency_key_digest,OLD.created_at)
   OR (OLD.status IN ('SUCCEEDED','FAILED','CANCELLED') AND NEW IS DISTINCT FROM OLD) THEN
   RAISE EXCEPTION 'SCOPED_PRD_OPERATION_IDENTITY_IMMUTABLE' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
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
 SELECT catalog_digest INTO expected FROM curve_two_stage_v2_coverage WHERE edition='CURVE_TWO_STAGE_REVIEW_V2';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_two_stage_v2_coverage)<>1 THEN
  RAISE EXCEPTION 'TWO_STAGE_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;

DROP TABLE curve_scoped_v2_coverage;
DROP FUNCTION curve_sprd_schema(text,text);
DROP FUNCTION curve_sprd_command_prefix(text);
DROP FUNCTION curve_sprd_initiative_edition(text);
