-- Candidate Technical-review storage successor. Qualified by migration0029 before use.
CREATE OR REPLACE FUNCTION curve_mg2_edition(payload jsonb) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE payload->>'schema_version' WHEN 'curve.manual-gate2.record/v2-candidate' THEN 2 WHEN 'curve.manual-gate2.record/v3-candidate' THEN 3 ELSE 0 END
$$;
CREATE OR REPLACE FUNCTION curve_mg2_schema(kind text, edition integer) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $schema$
BEGIN
 IF edition=2 THEN RETURN curve_mg2_schema(kind); END IF;
 IF edition<>3 THEN RETURN '{}'::jsonb; END IF;
 CASE kind
 WHEN 'record' THEN RETURN '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-gate2-v3/record.schema.json","type":"object","additionalProperties":false,"properties":{"schema_version":{"const":"curve.manual-gate2.record/v3-candidate"},"policy_edition":{"const":"LOCAL_MANUAL_GATE2_RECONSTRUCTION_V3"},"id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"sequence":{"type":"integer","minimum":1,"maximum":9007199254740991},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"predecessor_id":{"anyOf":[{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},{"type":"null"}]},"action":{"enum":["PREPARE","APPROVE","REQUEST_CHANGES","RECONCILE","RELEASE"]},"actor_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"draft_revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_metadata":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"edition":{"const":"MANUAL_GATE2_TWO_STAGE_TRANSITION_V3"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_revision":{"type":"integer","minimum":1,"maximum":9007199254740991},"draft_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"input_identity":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v3/manual-plan-input-identity-v3.schema.json","title":"Private retained original-input identities, never a current ACL","type":"object","additionalProperties":false,"required":["schema_version","workspace_id","initiative_id","approved_subject_ref","prd_artifact_version_id","prd_content_digest","evidence_snapshot_id","scope_revision_ref","manual_profile_ref","definition_ref","workflow_ref","quality_policy_ref","repository_inputs","protected_inputs","human_owner_ids","gate_assignments","digest"],"properties":{"schema_version":{"const":"curve.manual-plan-input-identity/v3-candidate"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approved_subject_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"prd_artifact_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"evidence_snapshot_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"scope_revision_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"manual_profile_ref":{"allOf":[{"allOf":[{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000301","digest":"sha256:fbfaf1ae8608aa580c5d76514a948ef515f8e0795248d180840fb89779f5a1e8"}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000301","digest":"sha256:fbfaf1ae8608aa580c5d76514a948ef515f8e0795248d180840fb89779f5a1e8"}},"definition_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":5242880},"media_type":{"const":"application/json"}}},"workflow_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"quality_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"repository_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["repository_ref","base_branch","base_commit","repository_policy_ref","context_input_ref"],"properties":{"repository_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"base_branch":{"type":"string","minLength":1,"maxLength":255,"pattern":"\\S"},"base_commit":{"oneOf":[{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha1"},"value":{"type":"string","pattern":"^[0-9a-f]{40}$"}}},{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha256"},"value":{"type":"string","pattern":"^[0-9a-f]{64}$"}}}]},"repository_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"context_input_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}}}},"minItems":1,"maxItems":32,"uniqueItems":true},"protected_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["object_ref","material_version_id","access_envelope_id","classification","input_kind"],"properties":{"object_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}},"material_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"access_envelope_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"classification":{"type":"string","enum":["INTERNAL","CONFIDENTIAL","RESTRICTED"]},"input_kind":{"type":"string","enum":["CONTEXT_INPUT","ATTACHMENT"]}},"allOf":[{"if":{"properties":{"input_kind":{"const":"ATTACHMENT"}},"required":["input_kind"]},"then":{"properties":{"object_ref":{"properties":{"size_bytes":{"maximum":104857600}}}}}}]},"minItems":1,"maxItems":1024,"uniqueItems":true},"human_owner_ids":{"type":"array","items":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"minItems":1,"maxItems":256,"uniqueItems":true},"gate_assignments":{"type":"array","minItems":2,"maxItems":2,"uniqueItems":true,"prefixItems":[{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PLAN_APPROVAL"}}}]},{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PRD_APPROVAL"}}}]}],"items":false},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"validation_receipt_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"validator_edition":{"const":"DETERMINISTIC_SDLC_MANUAL_PLAN_V3"},"controlling_prd_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"risk_tier":{"enum":["LOW","STANDARD","HIGH"]},"semantic_facts_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"tasks":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"installation_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"issue_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}},"required":["workspace_id","installation_id","issue_id"]},"maxItems":100,"uniqueItems":true}},"required":["edition","workspace_id","product_id","initiative_id","draft_revision_id","draft_revision","draft_digest","input_identity","validation_receipt_digest","validator_edition","controlling_prd_decision_id","risk_tier","semantic_facts_digest","tasks"]},{"type":"null"}]},"rationale_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":16384},"media_type":{"const":"application/json"}},"required":["object_id","digest","size_bytes","media_type"]},{"type":"null"}]},"reconciliation_id":{"anyOf":[{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},{"type":"null"}]},"observations":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"claim_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"installation_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"issue_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"generation":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_fingerprint":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"state_group":{"enum":["backlog","unstarted","completed","cancelled"]}},"required":["claim_id","installation_id","issue_id","generation","source_fingerprint","state_group"]},"maxItems":100,"uniqueItems":true},"claims":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"claim_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"history_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"installation_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"issue_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"generation":{"type":"integer","minimum":1,"maximum":9007199254740991},"state":{"enum":["ACTIVE","RELEASED"]},"record_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}},"required":["claim_id","history_id","installation_id","issue_id","initiative_id","subject_id","generation","state","record_id"]},"maxItems":100,"uniqueItems":true},"native_fence_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"policy_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"command_receipt_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"recorded_at":{"type":"string","format":"date-time"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"request_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},"required":["schema_version","policy_edition","id","workspace_id","product_id","initiative_id","sequence","initiative_version","predecessor_id","action","actor_id","subject_id","subject_digest","draft_revision_id","subject_metadata","rationale_ref","reconciliation_id","observations","claims","native_fence_digest","policy_decision_id","command_receipt_id","recorded_at","digest","request_digest"]}'::jsonb;
 WHEN 'command' THEN RETURN '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-gate2-v3/command.schema.json","type":"object","additionalProperties":false,"properties":{"schema_version":{"const":"curve.manual-gate2.command/v3-candidate"},"action":{"enum":["PREPARE","APPROVE","REQUEST_CHANGES","RECONCILE","RELEASE"]},"draft_revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},"required":["entity_id","digest"]},{"type":"null"}]},"rationale_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":16384},"media_type":{"const":"application/json"}},"required":["object_id","digest","size_bytes","media_type"]},{"type":"null"}]},"claims":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"claim_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"generation":{"type":"integer","minimum":1,"maximum":9007199254740991}},"required":["claim_id","generation"]},"maxItems":100,"uniqueItems":true},"reconciliation_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},"required":["entity_id","digest"]},{"type":"null"}]}},"required":["schema_version","action","draft_revision_id","subject_ref","rationale_ref","claims","reconciliation_ref"]}'::jsonb;
 WHEN 'event' THEN RETURN '{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-gate2-v3/event.schema.json","type":"object","additionalProperties":false,"properties":{"schema_version":{"const":"curve.manual-gate2.event/v3-candidate"},"record_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"record_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"subject_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"action":{"enum":["PREPARE","APPROVE","REQUEST_CHANGES","RECONCILE","RELEASE"]},"policy_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"execution_authorized":{"const":false},"completion_credit":{"const":false}},"required":["schema_version","record_id","record_digest","subject_digest","action","policy_decision_id","execution_authorized","completion_credit"]}'::jsonb;
 ELSE RETURN '{}'::jsonb; END CASE;
END $schema$;

CREATE OR REPLACE FUNCTION curve_mg2_record_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE edition integer:=curve_mg2_edition(NEW.payload); p jsonb:=NEW.payload; q jsonb:=NEW.request_payload; s jsonb; k text; actor jsonb;
 init curve_initiative; ctl curve_manual_gate2_control_v2; draft curve_manual_plan_revision_v2;
 original curve_manual_gate2_record_v2; prior curve_manual_gate2_record_v2; expected_tasks jsonb;
BEGIN
 IF edition NOT IN (2,3) THEN RAISE EXCEPTION 'MANUAL_GATE2_EDITION_INVALID' USING ERRCODE='23514'; END IF;
 PERFORM curve_scope_reopening_verify_coverage();
 IF NOT curve_mpd2_shape(p,curve_mg2_schema('record',edition)) OR NOT curve_mpd2_shape(q,curve_mg2_schema('command',edition))
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
 IF NOT FOUND OR (edition=3 AND init.schema_version<>'1.2') OR (edition=2 AND init.schema_version NOT IN ('1.0','1.1')) OR init.product_id<>NEW.product_id OR init.mode<>'STANDALONE' OR init.pending_scope_reopening_id IS NOT NULL
  OR init.version+1<>NEW.initiative_version OR init.state NOT IN ('PLANNING','PAUSED','CANCELLED')
  OR (NEW.action NOT IN ('RECONCILE','RELEASE') AND init.state<>'PLANNING')
  OR NOT EXISTS(SELECT 1 FROM curve_product WHERE id=NEW.product_id AND workspace_id=NEW.workspace_id AND state='ACTIVE') THEN
  RAISE EXCEPTION 'MANUAL_GATE2_INITIATIVE_MISMATCH' USING ERRCODE='23514';
 END IF;
 SELECT * INTO draft FROM curve_manual_plan_revision_v2 WHERE id=NEW.draft_revision_id AND workspace_id=NEW.workspace_id
  AND initiative_id=NEW.initiative_id AND product_id=NEW.product_id;
 IF NOT FOUND OR curve_mpd_edition(draft.payload)<>edition THEN RAISE EXCEPTION 'MANUAL_GATE2_DRAFT_REQUIRED' USING ERRCODE='23514'; END IF;
 SELECT * INTO ctl FROM curve_manual_gate2_control_v2 WHERE initiative_id=NEW.initiative_id FOR UPDATE;
 IF FOUND THEN
  SELECT * INTO prior FROM curve_manual_gate2_record_v2 WHERE id=ctl.current_record_id;
  IF curve_mg2_edition(prior.payload)<>edition OR ctl.id<>NEW.control_id OR ctl.workspace_id<>NEW.workspace_id OR ctl.product_id<>NEW.product_id
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
  IF NOT FOUND OR curve_mg2_edition(original.payload)<>edition OR original.action<>'PREPARE' OR original.subject_id<>original.id OR original.initiative_id<>NEW.initiative_id
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
   AND sp.payload->>'schema_version'=CASE edition WHEN 3 THEN 'curve.scoped-prd/v2-candidate' ELSE 'curve.scoped-prd/v1-candidate' END AND d.payload->>'schema_version'=sp.payload->>'schema_version' AND d.payload->>'state'='APPROVED' AND b.state='APPROVED') THEN
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
  AND action='CURVE.MANUAL_GATE2.'||NEW.action||('_V'||edition::text) AND effect='ALLOW' AND policy_key=('CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V'||edition::text)
  AND policy_version=edition AND policy_manifest_digest=CASE edition WHEN 2 THEN 'sha256:b77e1c16465b9ebdea65ffa37915bee9239a616f667a72f8e6ad978df8833514' ELSE 'sha256:16d6a552f604f7b8ce4711e2b0521de7155d0542da3d8eaec7cea6f3e60c337b' END AND resource_type='INITIATIVE' AND resource_id=NEW.initiative_id AND resource_version=init.version
  AND input_digest=curve_sprd_digest(jsonb_build_object('request_digest',NEW.request_digest,'native_fence_digest',p->>'native_fence_digest'))
  AND subject=actor AND effective_principal=actor AND permitted_projection=jsonb_build_array('MANUAL_GATE2_METADATA_V'||edition::text)
  AND curve_sprd_created_here('curve_policy_decision',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_POLICY_REQUIRED' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION curve_mg2_commit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE edition integer:=curve_mg2_edition(NEW.payload); init curve_initiative; ctl curve_manual_gate2_control_v2; e curve_domain_event; ref jsonb; v_actor jsonb; v_response text; expected_event jsonb;
BEGIN
 IF edition NOT IN (2,3) THEN RAISE EXCEPTION 'MANUAL_GATE2_EDITION_INVALID' USING ERRCODE='23514'; END IF;
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
 expected_event:=jsonb_build_object('schema_version',('curve.manual-gate2.event/v'||edition::text||'-candidate'),'record_id',NEW.id::text,'record_digest',NEW.digest,
  'subject_digest',NEW.subject_digest,'action',NEW.action,'policy_decision_id',NEW.policy_decision_id::text,'execution_authorized',false,'completion_credit',false);
 SELECT * INTO e FROM curve_domain_event WHERE id=NEW.command_receipt_id AND workspace_id=NEW.workspace_id;
 IF NOT FOUND OR e.event_type<>('CURVE.MANUAL_GATE2_RECORDED_V'||edition::text) OR e.schema_version<>'1.0' OR e.initiative_id IS DISTINCT FROM NEW.initiative_id OR e.workflow_version_id IS DISTINCT FROM init.workflow_version_id OR e.aggregate_type<>('MANUAL_GATE2_CONTROL_V'||edition::text)
  OR e.aggregate_id<>NEW.control_id OR e.aggregate_version<>NEW.version OR e.sequence<>NEW.version OR e.payload IS DISTINCT FROM expected_event
  OR NOT curve_mpd2_shape(e.payload,curve_mg2_schema('event',edition)) OR e.actor IS DISTINCT FROM v_actor OR e.effective_principal IS DISTINCT FROM v_actor
  OR e.payload_schema<>('https://curve.example.invalid/candidates/manual-gate2-v'||edition::text||'/event.schema.json')
  OR NOT curve_sprd_created_here('curve_domain_event',NEW.workspace_id,e.id)
  OR NOT EXISTS(SELECT 1 FROM curve_outbox_event WHERE workspace_id=NEW.workspace_id AND event_id=e.id AND destination=('curve-local-manual-gate2-v'||edition::text)
   AND curve_sprd_created_here('curve_outbox_event',workspace_id,id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_EVENT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 ref:=jsonb_build_object('resource_type',('MANUAL_GATE2_RECORD_V'||edition::text),'resource_id',NEW.id::text,'resource_version',NEW.version);
 v_response:=curve_sprd_digest(jsonb_build_object('response_status',201,'response_resource_ref',ref));
 IF NOT EXISTS(SELECT 1 FROM curve_idempotency_record i WHERE i.workspace_id=NEW.workspace_id
  AND i.principal_scope='HUMAN:'||NEW.created_by::text AND i.command_scope='CURVE.MANUAL_GATE2.'||NEW.action||('_V'||edition::text||':')||NEW.initiative_id::text
  AND i.key_digest=e.idempotency_key_digest AND i.request_digest=NEW.request_digest AND i.state='COMPLETED'
  AND i.response_status=201 AND i.response_resource_ref=ref AND i.response_digest=v_response
  AND curve_sprd_created_here('curve_idempotency_record',i.workspace_id,i.id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_IDEMPOTENCY_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 IF (SELECT count(*) FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id AND a.policy_decision_ref->>'resource_id'=NEW.policy_decision_id::text)<>1
  OR NOT EXISTS(SELECT 1 FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id AND a.action='CURVE.MANUAL_GATE2.'||NEW.action||('_V'||edition::text)
   AND a.target_type=('MANUAL_GATE2_RECORD_V'||edition::text) AND a.target_id=NEW.id AND a.target_ref=ref AND a.outcome='SUCCEEDED' AND a.actor=v_actor AND a.effective_principal=v_actor
   AND a.idempotency_key_digest=e.idempotency_key_digest AND a.after_digest=v_response
   AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1)
   AND curve_sprd_created_here('curve_audit_event',a.workspace_id,a.id)) THEN
  RAISE EXCEPTION 'MANUAL_GATE2_AUDIT_INCOMPLETE' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;

CREATE TABLE curve_manual_gate2_v3_coverage (edition text PRIMARY KEY, catalog_digest text NOT NULL);
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
 SELECT catalog_digest INTO expected FROM curve_manual_gate2_v3_coverage WHERE edition='CURVE_MANUAL_GATE2_V3';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_gate2_v3_coverage)<>1 THEN
  RAISE EXCEPTION 'TECHNICAL_V3_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;
END $function$;
