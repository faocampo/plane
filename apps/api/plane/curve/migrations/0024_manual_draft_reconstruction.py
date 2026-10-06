"""UNQUALIFIED candidate: immutable manual drafts and transaction graph guards.

CURRENT_CATALOG_DIGEST must remain unset until real disposable PostgreSQL tests
and review. The first operation refuses execution before any DDL when unset.
No deployed/observed schema can populate that value automatically.
"""

import hashlib
from importlib import import_module
from pathlib import Path
import re
import uuid

import django.utils.timezone
from django.db import migrations, models

# Frozen independent of runtime loaders. The predecessor migration is immutable.
# ruff: noqa: E501
BASELINE_CATALOG_DIGEST = "sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7"
CURRENT_CATALOG_DIGEST = 'sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8'
POLICY_DIGEST = "sha256:cd960f017b8209b5e4a26a624cfb3549577f946c5a9682c593dec5908d6ab2f0"
PREDECESSOR_MIGRATIONS = {
    "0001_initial.py": "sha256:0bf82e2cc24d37052d6f6afabc4b75d93e3c343490a4a6d30b39d21defe79341",
    "0002_initial.py": "sha256:5a67c98c10690d0b94266aea871e1ab9c34d3bddfcad56f24aa5c7aaa18586f4",
    "0003_policydecision.py": "sha256:6e4774d25c5b94886c4fc5651b63a83502d708147381282f637752b3e2a2de6d",
    "0004_policydecision_recorded_at_default.py": "sha256:cf572e156911ebbbf42b200b4022c3f7b6bf5bbaa8a5f66f5253ef7426949415",
    "0005_providerconnection_providercapability.py": "sha256:739fbc03267a594e42db9a7b4f9f146eaf325961afaae710e5e59c27de025b7d",
    "0006_product.py": "sha256:219caf004407992065fa854b667408e8b435c7e91ed7bd78d6dd3b4a26d1d0b9",
    "0007_initiative_gateassignment.py": "sha256:ea6864188d4e2043d2662e5e3c572011bb05739f85a755ba94bb10c1e0dfece9",
    "0008_initiative_business_intent.py": "sha256:1554f49f72b43425e86d8c20c713df7e296bea101222d55b9733261af3e5e8bd",
    "0009_external_document_binding.py": "sha256:7a743d33e414683a910646dfb1388355e8daad9ae83f27736caabb2ac269524b",
    "0010_prd_artifact_evidence.py": "sha256:4b98b179ea2686888d1c490355227a0d692aafeeef8a2cc302f2de1feb3dcb7d",
    "0011_document_checkpoint.py": "sha256:8d331bef958f192ff9f92daa3018844e375d1eb7d602517437a731d07ed3ef9e",
    "0012_prd_review_decision.py": "sha256:d251d309330143d6b59af7dc41504a02a43db76ecef6979b2531c4c202933f7d",
    "0013_initiative_prd_lifecycle.py": "sha256:3c6c8c5e650316a8dce91f1c4a3be49eea91cafac5fcb4e7912fda0501977516",
    "0014_prd_policy_identity.py": "sha256:b8c7f91acca0b6fb856647d852b8bf78851ac89fa1a122c724832f53e32eb1ec",
    "0015_prd_accepted_command.py": "sha256:f68407866f0229d6f08f945faf88504d5ad1f230e5e87e899b989ddb209772d6",
    "0016_prd_readiness_record.py": "sha256:0df90c91fa024e7ec6d0521d137d0cd5e40740eab9c8d50b0d494cf7b3b38a73",
    "0017_prd_git_retention.py": "sha256:0bb46986aacef3eca13a3bb2253df634a04789b91f728db626fff24f110dd99e",
    "0018_prd_rationale_git_retention.py": "sha256:48f5b3f1fdc634e7e473b627e56d23c73061927d8504f5e5192791794ecad6da",
    "0019_prd_evidence_git_retention.py": "sha256:f9e4eaf6d73e7063188d9fd02cb5608fccb93410a2fddaab189f05c44a5016dc",
    "0020_project_association.py": "sha256:208933c0adb01bba734e4453774fb1371ba7bc1662872063585626b984b5058d",
    "0021_scope_proposal.py": "sha256:f8886950a8c7603acc461d7e8657d10a48a239173335b92e2039de8c5988569e",
    "0022_scoped_prd.py": "sha256:bbde99b2ea25671f7fcc62626abed5de09d7eafd6777a54a39646d576133426f",
    "0023_scope_reopening.py": "sha256:d1f1563d0cf63998635c192a5046df683b059e48c976a520ffc049296d2a56c9",
}

SHAPE_SQL = r"""
CREATE FUNCTION curve_mpd2_shape(p jsonb, s jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE k text; v jsonb; t text:=s->>'type'; n int; i int;
BEGIN
 IF p IS NULL OR s IS NULL OR s ? '$ref' THEN RETURN false; END IF;
 IF s ? 'const' AND p IS DISTINCT FROM s->'const' THEN RETURN false; END IF;
 IF s ? 'enum' AND NOT (s->'enum' @> jsonb_build_array(p)) THEN RETURN false; END IF;
 IF s ? 'allOf' THEN
  FOR v IN SELECT value FROM jsonb_array_elements(s->'allOf') LOOP
   IF NOT curve_mpd2_shape(p,v) THEN RETURN false; END IF;
  END LOOP;
 END IF;
 IF s ? 'anyOf' AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(s->'anyOf') AS alternatives(schema) WHERE curve_mpd2_shape(p,alternatives.schema)) THEN RETURN false; END IF;
 IF s ? 'oneOf' AND (SELECT count(*) FROM jsonb_array_elements(s->'oneOf') AS alternatives(schema) WHERE curve_mpd2_shape(p,alternatives.schema))<>1 THEN RETURN false; END IF;
 IF s ? 'if' THEN
  IF curve_mpd2_shape(p,s->'if') THEN
   IF s ? 'then' AND NOT curve_mpd2_shape(p,s->'then') THEN RETURN false; END IF;
  ELSE
   IF s ? 'else' AND NOT curve_mpd2_shape(p,s->'else') THEN RETURN false; END IF;
  END IF;
 END IF;
 IF t='integer' THEN
  IF jsonb_typeof(p)<>'number' OR p::text !~ '^[0-9]+$' THEN RETURN false; END IF;
 ELSIF t IS NOT NULL AND jsonb_typeof(p) IS DISTINCT FROM t THEN RETURN false;
 END IF;
 IF jsonb_typeof(p)='number' THEN
  IF (s ? 'minimum' AND p::text::numeric<(s->>'minimum')::numeric)
   OR (s ? 'maximum' AND p::text::numeric>(s->>'maximum')::numeric) THEN RETURN false; END IF;
 ELSIF jsonb_typeof(p)='object' THEN
  IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(s->'required') r WHERE NOT p ? r) THEN RETURN false; END IF;
  IF s->'additionalProperties'='false'::jsonb AND EXISTS(SELECT 1 FROM jsonb_object_keys(p) a WHERE NOT s->'properties' ? a) THEN RETURN false; END IF;
  FOR k,v IN SELECT * FROM jsonb_each(p) LOOP
   IF s->'properties' ? k AND NOT curve_mpd2_shape(v,s->'properties'->k) THEN RETURN false; END IF;
  END LOOP;
 ELSIF jsonb_typeof(p)='array' THEN
  n:=jsonb_array_length(p);
  IF (s ? 'minItems' AND n<(s->>'minItems')::int) OR (s ? 'maxItems' AND n>(s->>'maxItems')::int)
   OR (s->'uniqueItems'='true'::jsonb AND n<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(p))) THEN RETURN false; END IF;
  FOR i IN 0..n-1 LOOP
   IF s ? 'prefixItems' AND i<jsonb_array_length(s->'prefixItems') THEN
    IF NOT curve_mpd2_shape(p->i,s->'prefixItems'->i) THEN RETURN false; END IF;
   ELSIF s ? 'items' THEN
    IF s->'items'='false'::jsonb OR NOT curve_mpd2_shape(p->i,s->'items') THEN RETURN false; END IF;
   END IF;
  END LOOP;
 ELSIF jsonb_typeof(p)='string' THEN
  IF (s ? 'minLength' AND length(p #>> '{}')<(s->>'minLength')::int)
   OR (s ? 'maxLength' AND length(p #>> '{}')>(s->>'maxLength')::int)
   OR (s ? 'pattern' AND (p #>> '{}') !~ (s->>'pattern')) THEN RETURN false; END IF;
  IF s->>'format'='date-time' THEN
   IF NOT isfinite((p #>> '{}')::timestamptz) THEN RETURN false; END IF;
  END IF;
  IF s->>'format'='uuid' THEN PERFORM (p #>> '{}')::uuid; END IF;
 END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
"""

# Schema literals are dereferenced from the pinned snapshot during authoring,
# never fetched or read from a mutable runtime file while migrating.
SCHEMA_SQL = 'CREATE FUNCTION curve_mpd2_schema(kind text) RETURNS jsonb LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT CASE kind WHEN \'revision\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-draft-revision-v2.schema.json","title":"Protected immutable draft metadata projection","type":"object","additionalProperties":false,"required":["schema_version","policy_edition","id","workspace_id","product_id","initiative_id","draft_id","revision","initiative_version","predecessor_id","approved_subject_ref","definition_ref","manual_profile_ref","created_by","recorded_at","digest","controlling"],"properties":{"schema_version":{"const":"curve.manual-plan-draft.revision/v2-candidate"},"policy_edition":{"const":"LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2"},"id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"revision":{"type":"integer","minimum":1,"maximum":9007199254740991},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"predecessor_id":{"anyOf":[{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},{"type":"null"}]},"approved_subject_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"definition_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":5242880},"media_type":{"const":"application/json"}}},"manual_profile_ref":{"allOf":[{"allOf":[{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000201","digest":"sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000201","digest":"sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"}},"created_by":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"recorded_at":{"type":"string","format":"date-time","pattern":"^\\\\d{4}-\\\\d{2}-\\\\d{2}T\\\\d{2}:\\\\d{2}:\\\\d{2}(?:\\\\.\\\\d{1,6})?Z$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"controlling":{"const":false}}}\'::jsonb WHEN \'identity\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-input-identity-v2.schema.json","title":"Private retained original-input identities, never a current ACL","type":"object","additionalProperties":false,"required":["schema_version","workspace_id","initiative_id","approved_subject_ref","prd_artifact_version_id","prd_content_digest","evidence_snapshot_id","scope_revision_ref","manual_profile_ref","definition_ref","workflow_ref","quality_policy_ref","repository_inputs","protected_inputs","human_owner_ids","gate_assignments","digest"],"properties":{"schema_version":{"const":"curve.manual-plan-input-identity/v2-candidate"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approved_subject_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"prd_artifact_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"evidence_snapshot_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"scope_revision_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"manual_profile_ref":{"allOf":[{"allOf":[{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000201","digest":"sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000201","digest":"sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"}},"definition_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":5242880},"media_type":{"const":"application/json"}}},"workflow_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"quality_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"repository_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["repository_ref","base_branch","base_commit","repository_policy_ref","context_input_ref"],"properties":{"repository_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"base_branch":{"type":"string","minLength":1,"maxLength":255,"pattern":"\\\\S"},"base_commit":{"oneOf":[{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha1"},"value":{"type":"string","pattern":"^[0-9a-f]{40}$"}}},{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha256"},"value":{"type":"string","pattern":"^[0-9a-f]{64}$"}}}]},"repository_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"context_input_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}}}},"minItems":1,"maxItems":32,"uniqueItems":true},"protected_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["object_ref","material_version_id","access_envelope_id","classification","input_kind"],"properties":{"object_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}},"material_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"access_envelope_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"classification":{"type":"string","enum":["INTERNAL","CONFIDENTIAL","RESTRICTED"]},"input_kind":{"type":"string","enum":["CONTEXT_INPUT","ATTACHMENT"]}},"allOf":[{"if":{"properties":{"input_kind":{"const":"ATTACHMENT"}},"required":["input_kind"]},"then":{"properties":{"object_ref":{"properties":{"size_bytes":{"maximum":104857600}}}}}}]},"minItems":1,"maxItems":1024,"uniqueItems":true},"human_owner_ids":{"type":"array","items":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"minItems":1,"maxItems":256,"uniqueItems":true},"gate_assignments":{"type":"array","minItems":3,"maxItems":3,"uniqueItems":true,"prefixItems":[{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL","CODE_READINESS"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"CODE_READINESS"}}}]},{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL","CODE_READINESS"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PLAN_APPROVAL"}}}]},{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL","CODE_READINESS"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PRD_APPROVAL"}}}]}],"items":false},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}\'::jsonb WHEN \'validation\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-validation-receipt-v2.schema.json","title":"Private deterministic validation result","type":"object","additionalProperties":false,"required":["schema_version","validator_edition","definition_digest","input_identity_digest","result","repository_count","slice_count","edge_count","required_conditions","digest"],"properties":{"schema_version":{"const":"curve.manual-plan-validation-receipt/v2-candidate"},"validator_edition":{"const":"DETERMINISTIC_SDLC_MANUAL_PLAN_V2"},"definition_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"input_identity_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"result":{"const":"VALID"},"repository_count":{"type":"integer","minimum":1,"maximum":32},"slice_count":{"type":"integer","minimum":1,"maximum":256},"edge_count":{"type":"integer","minimum":0,"maximum":4096},"required_conditions":{"const":"FUTURE_NOT_ASSERTED"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}\'::jsonb WHEN \'event\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-draft-event-v2.schema.json","title":"Minimal immutable manual draft event payload","type":"object","additionalProperties":false,"required":["schema_version","policy_edition","event_type","workspace_id","initiative_id","draft_id","revision_id","revision_digest","definition_digest","input_identity_digest","policy_decision_id","controlling"],"properties":{"schema_version":{"const":"curve.manual-plan-draft.event/v2-candidate"},"policy_edition":{"const":"LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2"},"event_type":{"const":"CURVE.MANUAL_PLAN_DRAFT_SAVED_V2"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"revision_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"definition_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"input_identity_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"policy_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"controlling":{"const":false}}}\'::jsonb ELSE NULL END $$;'

GUARD_SQL = r"""
ALTER TABLE curve_manual_plan_draft_v2 ADD CONSTRAINT curve_mpd2_init_fk
 FOREIGN KEY(workspace_id,initiative_id) REFERENCES curve_initiative(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_manual_plan_revision_v2 ADD CONSTRAINT curve_mpr2_draft_fk
 FOREIGN KEY(workspace_id,draft_id) REFERENCES curve_manual_plan_draft_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_manual_plan_draft_v2 ADD CONSTRAINT curve_mpd2_revision_fk
 FOREIGN KEY(workspace_id,current_revision_id) REFERENCES curve_manual_plan_revision_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_manual_plan_revision_v2 ADD CONSTRAINT curve_mpr2_previous_fk
 FOREIGN KEY(workspace_id,predecessor_id) REFERENCES curve_manual_plan_revision_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_manual_plan_revision_v2 ADD CONSTRAINT curve_mpr2_policy_fk
 FOREIGN KEY(policy_decision_id) REFERENCES curve_policy_decision(id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_manual_plan_revision_v2 ADD CONSTRAINT curve_mpr2_event_fk
 FOREIGN KEY(command_receipt_id) REFERENCES curve_domain_event(id) DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION curve_mpd2_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_HISTORY_IMMUTABLE' USING ERRCODE='23514'; END $$;
CREATE TRIGGER curve_mpr2_immutable BEFORE UPDATE OR DELETE ON curve_manual_plan_revision_v2
 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_mpr2_no_truncate BEFORE TRUNCATE ON curve_manual_plan_revision_v2
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_mpd2_no_delete BEFORE DELETE ON curve_manual_plan_draft_v2
 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_mpd2_no_truncate BEFORE TRUNCATE ON curve_manual_plan_draft_v2
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();

CREATE FUNCTION curve_mpr2_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
END $$;
CREATE TRIGGER curve_mpr2_insert_guard BEFORE INSERT ON curve_manual_plan_revision_v2
 FOR EACH ROW EXECUTE FUNCTION curve_mpr2_insert_guard();
CREATE TRIGGER curve_mpr2_stamp AFTER INSERT ON curve_manual_plan_revision_v2
 FOR EACH ROW EXECUTE FUNCTION curve_sprd_stamp();

CREATE FUNCTION curve_mpd2_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r curve_manual_plan_revision_v2;
BEGIN
 SELECT * INTO r FROM curve_manual_plan_revision_v2 WHERE id=NEW.current_revision_id;
 IF NOT FOUND OR r.workspace_id<>NEW.workspace_id OR r.initiative_id<>NEW.initiative_id
  OR r.product_id<>NEW.product_id OR r.draft_id<>NEW.id OR r.version<>NEW.version
  OR NOT curve_sprd_created_here('curve_manual_plan_revision_v2',r.workspace_id,r.id) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_HEAD_INVALID' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND ((to_jsonb(NEW)-ARRAY['version','current_revision_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','current_revision_id'])
  OR NEW.version<>OLD.version+1 OR r.predecessor_id IS DISTINCT FROM OLD.current_revision_id) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_HEAD_REWRITE' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND (NEW.version<>1 OR r.predecessor_id IS NOT NULL) THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_HEAD_INVALID' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER curve_mpd2_head_guard BEFORE INSERT OR UPDATE ON curve_manual_plan_draft_v2
 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_head_guard();

CREATE FUNCTION curve_mpr2_commit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
END $$;
CREATE CONSTRAINT TRIGGER curve_mpr2_commit AFTER INSERT ON curve_manual_plan_revision_v2
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION curve_mpr2_commit_guard();

CREATE TABLE curve_manual_plan_v2_coverage(edition text PRIMARY KEY, catalog_digest text NOT NULL);
CREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$
DECLARE expected text; actual text;
BEGIN
 IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage
  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7') THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514';
 END IF;
 SELECT catalog_digest INTO expected FROM curve_manual_plan_v2_coverage WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2';
 actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');
 IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 THEN
  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_COVERAGE_UNAVAILABLE' USING ERRCODE='23514';
 END IF;
END $$;
"""

SEAL_SQL = """CREATE TRIGGER curve_mpd2_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON curve_manual_plan_v2_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"""

REVERSE_SQL = "DROP TRIGGER curve_mpr2_commit ON curve_manual_plan_revision_v2;\nDROP TRIGGER curve_mpd2_head_guard ON curve_manual_plan_draft_v2;\nDROP TRIGGER curve_mpr2_insert_guard ON curve_manual_plan_revision_v2;\nDROP TRIGGER curve_mpr2_stamp ON curve_manual_plan_revision_v2;\nDROP TRIGGER curve_mpr2_immutable ON curve_manual_plan_revision_v2;\nDROP TRIGGER curve_mpr2_no_truncate ON curve_manual_plan_revision_v2;\nDROP TRIGGER curve_mpd2_no_delete ON curve_manual_plan_draft_v2;\nDROP TRIGGER curve_mpd2_no_truncate ON curve_manual_plan_draft_v2;\nDROP TABLE curve_manual_plan_v2_coverage;\nDROP FUNCTION curve_mpr2_commit_guard();\nDROP FUNCTION curve_mpd2_head_guard();\nDROP FUNCTION curve_mpr2_insert_guard();\nDROP FUNCTION curve_mpd2_immutable();\nDROP FUNCTION curve_mpd2_schema(text);\nDROP FUNCTION curve_mpd2_shape(jsonb,jsonb);\nALTER TABLE curve_manual_plan_draft_v2 DROP CONSTRAINT curve_mpd2_revision_fk;\nALTER TABLE curve_manual_plan_draft_v2 DROP CONSTRAINT curve_mpd2_init_fk;\nALTER TABLE curve_manual_plan_revision_v2 DROP CONSTRAINT curve_mpr2_draft_fk;\nALTER TABLE curve_manual_plan_revision_v2 DROP CONSTRAINT curve_mpr2_previous_fk;\nALTER TABLE curve_manual_plan_revision_v2 DROP CONSTRAINT curve_mpr2_policy_fk;\nALTER TABLE curve_manual_plan_revision_v2 DROP CONSTRAINT curve_mpr2_event_fk;\nCREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$\nDECLARE expected text; actual text;\nBEGIN\n SELECT catalog_digest INTO expected FROM curve_scope_reopening_coverage\n  WHERE edition='CURVE_PRE_PLAN_C2B_V1';\n actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');\n IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 THEN\n  RAISE EXCEPTION 'SCOPE_REOPENING_PREPLAN_COVERAGE_UNAVAILABLE' USING ERRCODE='23514';\n END IF;\nEND $$;"


def _catalog(cursor):
    sql = import_module("plane.curve.migrations.0023_scope_reopening").CATALOG_SQL
    cursor.execute("SHOW search_path")
    previous_path = cursor.fetchone()[0]
    cursor.execute("SET LOCAL search_path = pg_catalog, public")
    cursor.execute("SELECT 'sha256:' || encode(sha256(convert_to((" + sql + ")::text, 'UTF8')), 'hex')")
    result = cursor.fetchone()[0]
    cursor.execute("SELECT set_config('search_path', %s, true)", [previous_path])
    return result


def verify_predecessor(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None or re.fullmatch(r"sha256:[0-9a-f]{64}", CURRENT_CATALOG_DIGEST) is None:
        raise RuntimeError("MANUAL_PLAN_DRAFT_POSTGRESQL_QUALIFICATION_REQUIRED")
    directory = Path(__file__).parent
    for name, expected in PREDECESSOR_MIGRATIONS.items():
        if "sha256:" + hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("MANUAL_PLAN_DRAFT_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM django_migrations WHERE app='curve' ORDER BY name")
        if [row[0] + ".py" for row in cursor.fetchall()] != sorted(PREDECESSOR_MIGRATIONS):
            raise RuntimeError("MANUAL_PLAN_DRAFT_PREDECESSOR_MIGRATIONS_CHANGED")
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_PLAN_DRAFT_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("MANUAL_PLAN_DRAFT_POSTGRESQL_QUALIFICATION_REQUIRED")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_manual_plan_v2_coverage(edition,catalog_digest) VALUES (%s,%s)",
            ["CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_PLAN_DRAFT_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    if not schema_editor.connection.in_atomic_block:
        raise RuntimeError("MANUAL_PLAN_DRAFT_ATOMIC_REVERSAL_REQUIRED")
    with schema_editor.connection.cursor() as cursor:
        # Prevent evidence from appearing between the emptiness check and DDL.
        # Locks remain held by the enclosing atomic migration until completion.
        cursor.execute("""LOCK TABLE curve_audit_event, curve_domain_event,
          curve_idempotency_record, curve_manual_plan_draft_v2,
          curve_manual_plan_revision_v2, curve_outbox_event,
          curve_policy_decision IN ACCESS EXCLUSIVE MODE""")
        cursor.execute("""SELECT EXISTS(SELECT 1 FROM curve_manual_plan_revision_v2)
          OR EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2)
          OR EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE_MANUAL_PLAN_DRAFT_POLICY_V2')
          OR EXISTS(SELECT 1 FROM curve_domain_event WHERE event_type='CURVE.MANUAL_PLAN_DRAFT_SAVED_V2')
          OR EXISTS(SELECT 1 FROM curve_audit_event WHERE action='CURVE.MANUAL_PLAN_DRAFT.SAVE_V2')
          OR EXISTS(SELECT 1 FROM curve_idempotency_record WHERE command_scope LIKE 'CURVE.MANUAL_PLAN_DRAFT.SAVE_V2:%')
          OR EXISTS(SELECT 1 FROM curve_outbox_event WHERE destination='CURVE_MANUAL_PLAN_DRAFT_LOCAL_V2')""")
        if cursor.fetchone()[0]:
            raise RuntimeError("MANUAL_PLAN_DRAFT_RETAINED_EVIDENCE_PREVENTS_REVERSE")


def verify_empty_predecessor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_PLAN_DRAFT_REVERSE_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


# Django CreateModel operations and the exact policy-identity extension are
# appended below during authoring. Runtime migration execution remains blocked.


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0023_scope_reopening")]
    operations = [
        migrations.RunPython(verify_predecessor, verify_empty_predecessor),
        migrations.CreateModel(
            name="ManualPlanDraftV2",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("initiative_id", models.UUIDField(editable=False)),
                ("product_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("current_revision_id", models.UUIDField(editable=False)),
            ],
            options={
                "db_table": "curve_manual_plan_draft_v2",
                "constraints": [
                    models.UniqueConstraint(fields=("workspace_id", "id"), name="curve_mpd2_ws_id_uq"),
                    models.UniqueConstraint(fields=("workspace_id", "initiative_id"), name="curve_mpd2_init_uq"),
                    models.CheckConstraint(
                        condition=models.Q(("version__gte", 1), ("version__lte", 9007199254740991)),
                        name="curve_mpd2_ver_ck",
                    ),
                ],
                "indexes": [],
            },
        ),
        migrations.CreateModel(
            name="ManualPlanRevisionV2",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("product_id", models.UUIDField(editable=False)),
                ("initiative_id", models.UUIDField(db_index=True, editable=False)),
                ("draft_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("predecessor_id", models.UUIDField(editable=False, null=True)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("original_input_identity", models.JSONField(editable=False)),
                ("input_identity_digest", models.CharField(editable=False, max_length=71)),
                ("validation_receipt", models.JSONField(editable=False)),
                ("validation_receipt_digest", models.CharField(editable=False, max_length=71)),
                ("policy_decision_id", models.UUIDField(editable=False)),
                ("command_receipt_id", models.UUIDField(editable=False)),
                ("created_by", models.UUIDField(editable=False)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ],
            options={
                "db_table": "curve_manual_plan_revision_v2",
                "constraints": [
                    models.UniqueConstraint(fields=("workspace_id", "id"), name="curve_mpr2_ws_id_uq"),
                    models.UniqueConstraint(fields=("workspace_id", "draft_id", "version"), name="curve_mpr2_seq_uq"),
                    models.UniqueConstraint(fields=("workspace_id", "command_receipt_id"), name="curve_mpr2_cmd_uq"),
                    models.UniqueConstraint(fields=("workspace_id", "policy_decision_id"), name="curve_mpr2_policy_uq"),
                    models.CheckConstraint(
                        condition=models.Q(("version__gte", 1), ("version__lte", 9007199254740991)),
                        name="curve_mpr2_ver_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("initiative_version__gte", 2), ("initiative_version__lte", 9007199254740991)
                        ),
                        name="curve_mpr2_init_ver_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("predecessor_id__isnull", True), ("version", 1)),
                            models.Q(("predecessor_id__isnull", False), ("version__gt", 1)),
                            _connector="OR",
                        ),
                        name="curve_mpr2_prev_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_mpr2_digest_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("input_identity_digest__regex", "^sha256:[0-9a-f]{64}$")),
                        name="curve_mpr2_input_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("validation_receipt_digest__regex", "^sha256:[0-9a-f]{64}$")),
                        name="curve_mpr2_valid_ck",
                    ),
                ],
                "indexes": [],
            },
        ),
        migrations.RemoveConstraint(model_name="policydecision", name="curve_policy_identity_ck"),
        migrations.AddConstraint(
            model_name="policydecision",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        policy_key="CURVE_PROJECT_ASSOCIATION_POLICY",
                        policy_version=1,
                        policy_manifest_digest="sha256:0ea402f3db6a7fb0743a79a45644d79235a685781ad844d3c42230da2c548691",
                    )
                    | models.Q(
                        policy_key="CURVE_SCOPE_PROPOSAL_POLICY",
                        policy_version=1,
                        policy_manifest_digest="sha256:778bdbd6fb82f51482d791d22ae6cf884a8906e91613b07cdafc6b429d24e266",
                    )
                    | models.Q(
                        policy_key="CURVE_SCOPE_REOPENING_POLICY",
                        policy_version=1,
                        policy_manifest_digest="sha256:598e492b7dc23369eaf3029d7e208b4fd338d03d3e3388fcb10305e9c02b0094",
                    )
                    | models.Q(policy_key="CURVE_CORE_POLICY", policy_version__in=[1, 2])
                    | models.Q(policy_key="CURVE_PRODUCT_POLICY", policy_version=1)
                    | models.Q(policy_key="CURVE_INITIATIVE_POLICY", policy_version=1)
                    | models.Q(
                        policy_key="CURVE_PRD_POLICY",
                        policy_version=1,
                        policy_manifest_digest="sha256:ad38408f0e4450c615025debdf3361965f3a7361ad392aaf9aeb4219b910cb4c",
                    )
                )
                | models.Q(
                    policy_key="CURVE_MANUAL_PLAN_DRAFT_POLICY_V2",
                    policy_version=2,
                    policy_manifest_digest="sha256:cd960f017b8209b5e4a26a624cfb3549577f946c5a9682c593dec5908d6ab2f0",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(SHAPE_SQL + SCHEMA_SQL + GUARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(SEAL_SQL, "DROP TRIGGER curve_mpd2_coverage_immutable ON curve_manual_plan_v2_coverage;"),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
