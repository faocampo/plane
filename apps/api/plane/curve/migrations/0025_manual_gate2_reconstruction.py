"""UNQUALIFIED candidate: exclusive manual Gate 2 claims and transaction graph guards.

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
BASELINE_CATALOG_DIGEST = (
    "sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8"
)
CURRENT_CATALOG_DIGEST = 'sha256:4d33761d55c0f0cb509af13a729cdb6a7479c7b8ca662fc843f856bce33adb08'
POLICY_DIGEST = (
    "sha256:b77e1c16465b9ebdea65ffa37915bee9239a616f667a72f8e6ad978df8833514"
)
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
    "0024_manual_draft_reconstruction.py": "sha256:2d27fec515cb31ba5f2ed95052e21723385679392defeaea67686a93fa3c3b50",
}

CATALOG_SQL = "SELECT jsonb_build_object(\n 'tables', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind,c.relpersistence AS persistence,\n   c.relrowsecurity AS row_security,c.relforcerowsecurity AS force_row_security\n  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','v','m','f')\n   AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'columns', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,position),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,row_number() OVER (PARTITION BY n.nspname,c.relname ORDER BY a.attnum) AS position,a.attname AS name,\n   format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull AS not_null,a.attidentity AS identity_kind,\n   a.attgenerated AS generated_kind,pg_get_expr(d.adbin,d.adrelid,true) AS default_expression,\n   co.collname AS collation\n  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid\n  LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','v','m','f')\n   AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND a.attnum>0 AND NOT a.attisdropped) r),\n 'constraints', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,k.conname AS name,k.contype AS kind,\n   pg_get_constraintdef(k.oid,true) AS definition,k.condeferrable AS deferrable,\n   k.condeferred AS initially_deferred,k.convalidated AS validated,k.connoinherit AS no_inherit\n  FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'triggers', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name,definition,constraint_name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,\n   CASE WHEN t.tgisinternal THEN '<internal>' ELSE t.tgname END AS name,t.tgisinternal AS internal,\n   t.tgenabled AS enabled,CASE WHEN t.tgisinternal THEN regexp_replace(pg_get_triggerdef(t.oid,true),\n    'TRIGGER \"?RI_ConstraintTrigger_[ac]_[0-9]+\"?', 'TRIGGER <internal>') ELSE pg_get_triggerdef(t.oid,true) END AS definition,\n   k.conname AS constraint_name,pn.nspname AS function_schema,p.proname AS function_name,\n   pg_get_function_identity_arguments(p.oid) AS function_identity_arguments\n  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace\n  JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace\n  LEFT JOIN pg_constraint k ON k.oid=t.tgconstraint\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'indexes', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,i.relname AS name,pg_get_indexdef(i.oid) AS definition,\n   x.indisunique AS unique,x.indisprimary AS primary_key,x.indisvalid AS valid,x.indisready AS ready\n  FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid\n  JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'functions', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,name,identity_arguments),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,p.proname AS name,pg_get_function_identity_arguments(p.oid) AS identity_arguments,\n   pg_get_functiondef(p.oid) AS definition,p.proconfig AS configuration\n  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE p.prokind IN ('f','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'\n   AND (p.proname LIKE 'curve\\_%' ESCAPE '\\' OR EXISTS(\n    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid\n     WHERE t.tgfoid=p.oid AND c.relname LIKE 'curve\\_%' ESCAPE '\\'))) r)\n)\n"

SCHEMA_SQL = 'CREATE FUNCTION curve_mg2_schema(kind text) RETURNS jsonb LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT CASE kind WHEN \'record\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-gate2-v2/record.schema.json","type":"object","additionalProperties":false,"properties":{"schema_version":{"const":"curve.manual-gate2.record/v2-candidate"},"policy_edition":{"const":"LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2"},"id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"sequence":{"type":"integer","minimum":1,"maximum":9007199254740991},"initiative_version":{"type":"integer","minimum":1,"maximum":9007199254740991},"predecessor_id":{"anyOf":[{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},{"type":"null"}]},"action":{"enum":["PREPARE","APPROVE","REQUEST_CHANGES","RECONCILE","RELEASE"]},"actor_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"draft_revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_metadata":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"edition":{"const":"MANUAL_GATE2_TRANSITION_CANDIDATE_V1"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"product_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"draft_revision":{"type":"integer","minimum":1,"maximum":9007199254740991},"draft_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"input_identity":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-planning-v2/manual-plan-input-identity-v2.schema.json","title":"Private retained original-input identities, never a current ACL","type":"object","additionalProperties":false,"required":["schema_version","workspace_id","initiative_id","approved_subject_ref","prd_artifact_version_id","prd_content_digest","evidence_snapshot_id","scope_revision_ref","manual_profile_ref","definition_ref","workflow_ref","quality_policy_ref","repository_inputs","protected_inputs","human_owner_ids","gate_assignments","digest"],"properties":{"schema_version":{"const":"curve.manual-plan-input-identity/v2-candidate"},"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approved_subject_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"prd_artifact_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"prd_content_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"evidence_snapshot_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"scope_revision_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"manual_profile_ref":{"allOf":[{"allOf":[{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000201","digest":"sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"}}],"const":{"entity_id":"20000000-0000-4000-8000-000000000201","digest":"sha256:16ddfbb742fb06e370e1c2db3723eb98c826e1454bf237d97f678656649314a4"}},"definition_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":5242880},"media_type":{"const":"application/json"}}},"workflow_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"quality_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"repository_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["repository_ref","base_branch","base_commit","repository_policy_ref","context_input_ref"],"properties":{"repository_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"base_branch":{"type":"string","minLength":1,"maxLength":255,"pattern":"\\\\S"},"base_commit":{"oneOf":[{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha1"},"value":{"type":"string","pattern":"^[0-9a-f]{40}$"}}},{"type":"object","additionalProperties":false,"required":["algorithm","value"],"properties":{"algorithm":{"const":"sha256"},"value":{"type":"string","pattern":"^[0-9a-f]{64}$"}}}]},"repository_policy_ref":{"type":"object","additionalProperties":false,"required":["entity_id","digest"],"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"context_input_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}}}},"minItems":1,"maxItems":32,"uniqueItems":true},"protected_inputs":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["object_ref","material_version_id","access_envelope_id","classification","input_kind"],"properties":{"object_ref":{"type":"object","additionalProperties":false,"required":["object_id","digest","size_bytes","media_type"],"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":0,"maximum":524288000},"media_type":{"type":"string","minLength":1,"maxLength":255}}},"material_version_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"access_envelope_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"classification":{"type":"string","enum":["INTERNAL","CONFIDENTIAL","RESTRICTED"]},"input_kind":{"type":"string","enum":["CONTEXT_INPUT","ATTACHMENT"]}},"allOf":[{"if":{"properties":{"input_kind":{"const":"ATTACHMENT"}},"required":["input_kind"]},"then":{"properties":{"object_ref":{"properties":{"size_bytes":{"maximum":104857600}}}}}}]},"minItems":1,"maxItems":1024,"uniqueItems":true},"human_owner_ids":{"type":"array","items":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"minItems":1,"maxItems":256,"uniqueItems":true},"gate_assignments":{"type":"array","minItems":3,"maxItems":3,"uniqueItems":true,"prefixItems":[{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL","CODE_READINESS"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"CODE_READINESS"}}}]},{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL","CODE_READINESS"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PLAN_APPROVAL"}}}]},{"allOf":[{"type":"object","additionalProperties":false,"required":["gate_type","gate_assignment_id","approver_user_id"],"properties":{"gate_type":{"type":"string","enum":["PRD_APPROVAL","PLAN_APPROVAL","CODE_READINESS"]},"gate_assignment_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"approver_user_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}}},{"properties":{"gate_type":{"const":"PRD_APPROVAL"}}}]}],"items":false},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}}},"validation_receipt_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"validator_edition":{"const":"DETERMINISTIC_SDLC_MANUAL_PLAN_V2"},"controlling_prd_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"risk_tier":{"enum":["LOW","STANDARD","HIGH"]},"semantic_facts_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"tasks":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"workspace_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"installation_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"issue_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}},"required":["workspace_id","installation_id","issue_id"]},"maxItems":100,"uniqueItems":true}},"required":["edition","workspace_id","product_id","initiative_id","draft_revision_id","draft_revision","draft_digest","input_identity","validation_receipt_digest","validator_edition","controlling_prd_decision_id","risk_tier","semantic_facts_digest","tasks"]},{"type":"null"}]},"rationale_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":16384},"media_type":{"const":"application/json"}},"required":["object_id","digest","size_bytes","media_type"]},{"type":"null"}]},"reconciliation_id":{"anyOf":[{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},{"type":"null"}]},"observations":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"claim_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"installation_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"issue_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"generation":{"type":"integer","minimum":1,"maximum":9007199254740991},"source_fingerprint":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"state_group":{"enum":["backlog","unstarted","completed","cancelled"]}},"required":["claim_id","installation_id","issue_id","generation","source_fingerprint","state_group"]},"maxItems":100,"uniqueItems":true},"claims":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"claim_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"history_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"installation_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"issue_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"initiative_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"generation":{"type":"integer","minimum":1,"maximum":9007199254740991},"state":{"enum":["ACTIVE","RELEASED"]},"record_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"}},"required":["claim_id","history_id","installation_id","issue_id","initiative_id","subject_id","generation","state","record_id"]},"maxItems":100,"uniqueItems":true},"native_fence_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"policy_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"command_receipt_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"recorded_at":{"type":"string","format":"date-time"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"request_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},"required":["schema_version","policy_edition","id","workspace_id","product_id","initiative_id","sequence","initiative_version","predecessor_id","action","actor_id","subject_id","subject_digest","draft_revision_id","subject_metadata","rationale_ref","reconciliation_id","observations","claims","native_fence_digest","policy_decision_id","command_receipt_id","recorded_at","digest","request_digest"]}\'::jsonb WHEN \'command\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-gate2-v2/command.schema.json","type":"object","additionalProperties":false,"properties":{"schema_version":{"const":"curve.manual-gate2.command/v2-candidate"},"action":{"enum":["PREPARE","APPROVE","REQUEST_CHANGES","RECONCILE","RELEASE"]},"draft_revision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"subject_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},"required":["entity_id","digest"]},{"type":"null"}]},"rationale_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"object_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"size_bytes":{"type":"integer","minimum":1,"maximum":16384},"media_type":{"const":"application/json"}},"required":["object_id","digest","size_bytes","media_type"]},{"type":"null"}]},"claims":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"claim_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"generation":{"type":"integer","minimum":1,"maximum":9007199254740991}},"required":["claim_id","generation"]},"maxItems":100,"uniqueItems":true},"reconciliation_ref":{"anyOf":[{"type":"object","additionalProperties":false,"properties":{"entity_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},"required":["entity_id","digest"]},{"type":"null"}]}},"required":["schema_version","action","draft_revision_id","subject_ref","rationale_ref","claims","reconciliation_ref"]}\'::jsonb WHEN \'event\' THEN \'{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://curve.example.invalid/candidates/manual-gate2-v2/event.schema.json","type":"object","additionalProperties":false,"properties":{"schema_version":{"const":"curve.manual-gate2.event/v2-candidate"},"record_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"record_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"subject_digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"action":{"enum":["PREPARE","APPROVE","REQUEST_CHANGES","RECONCILE","RELEASE"]},"policy_decision_id":{"type":"string","format":"uuid","pattern":"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"},"execution_authorized":{"const":false},"completion_credit":{"const":false}},"required":["schema_version","record_id","record_digest","subject_digest","action","policy_decision_id","execution_authorized","completion_credit"]}\'::jsonb ELSE NULL END $$;'

GUARD_SQL = "CREATE OR REPLACE FUNCTION curve_scope_reopening_catalog() RETURNS jsonb LANGUAGE sql STABLE\n SET search_path=pg_catalog,public AS $catalog$\nSELECT jsonb_build_object(\n 'tables', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind,c.relpersistence AS persistence,\n   c.relrowsecurity AS row_security,c.relforcerowsecurity AS force_row_security\n  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','v','m','f')\n   AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'columns', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,position),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,row_number() OVER (PARTITION BY n.nspname,c.relname ORDER BY a.attnum) AS position,a.attname AS name,\n   format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull AS not_null,a.attidentity AS identity_kind,\n   a.attgenerated AS generated_kind,pg_get_expr(d.adbin,d.adrelid,true) AS default_expression,\n   co.collname AS collation\n  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid\n  LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','v','m','f')\n   AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND a.attnum>0 AND NOT a.attisdropped) r),\n 'constraints', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,k.conname AS name,k.contype AS kind,\n   pg_get_constraintdef(k.oid,true) AS definition,k.condeferrable AS deferrable,\n   k.condeferred AS initially_deferred,k.convalidated AS validated,k.connoinherit AS no_inherit\n  FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'triggers', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name,definition,constraint_name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,\n   CASE WHEN t.tgisinternal THEN '<internal>' ELSE t.tgname END AS name,t.tgisinternal AS internal,\n   t.tgenabled AS enabled,CASE WHEN t.tgisinternal THEN regexp_replace(pg_get_triggerdef(t.oid,true),\n    'TRIGGER \"?RI_ConstraintTrigger_[ac]_[0-9]+\"?', 'TRIGGER <internal>') ELSE pg_get_triggerdef(t.oid,true) END AS definition,\n   k.conname AS constraint_name,pn.nspname AS function_schema,p.proname AS function_name,\n   pg_get_function_identity_arguments(p.oid) AS function_identity_arguments\n  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace\n  JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace\n  LEFT JOIN pg_constraint k ON k.oid=t.tgconstraint\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'indexes', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,i.relname AS name,pg_get_indexdef(i.oid) AS definition,\n   x.indisunique AS unique,x.indisprimary AS primary_key,x.indisvalid AS valid,x.indisready AS ready\n  FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid\n  JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'functions', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,name,identity_arguments),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,p.proname AS name,pg_get_function_identity_arguments(p.oid) AS identity_arguments,\n   pg_get_functiondef(p.oid) AS definition,p.proconfig AS configuration\n  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE p.prokind IN ('f','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'\n   AND (p.proname LIKE 'curve\\_%' ESCAPE '\\' OR EXISTS(\n    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid\n     WHERE t.tgfoid=p.oid AND c.relname LIKE 'curve\\_%' ESCAPE '\\'))) r)\n)\n$catalog$;\nCREATE FUNCTION curve_mg2_record_insert() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE p jsonb:=NEW.payload; q jsonb:=NEW.request_payload; s jsonb; k text; actor jsonb;\n init curve_initiative; ctl curve_manual_gate2_control_v2; draft curve_manual_plan_revision_v2;\n original curve_manual_gate2_record_v2; prior curve_manual_gate2_record_v2; expected_tasks jsonb;\nBEGIN\n PERFORM curve_scope_reopening_verify_coverage();\n IF NOT curve_mpd2_shape(p,curve_mg2_schema('record')) OR NOT curve_mpd2_shape(q,curve_mg2_schema('command'))\n  OR octet_length(curve_sprd_canonical(p))>2097152 OR octet_length(curve_sprd_canonical(q))>65536\n  OR curve_sprd_digest(p-'digest') IS DISTINCT FROM NEW.digest OR p->>'digest' IS DISTINCT FROM NEW.digest\n  OR p->>'request_digest' IS DISTINCT FROM NEW.request_digest\n  OR curve_sprd_digest(jsonb_build_object('initiative_id',NEW.initiative_id::text,'expected_version',NEW.initiative_version-1,'payload',q)) IS DISTINCT FROM NEW.request_digest THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_RECORD_INVALID' USING ERRCODE='23514';\n END IF;\n FOR k IN SELECT unnest(ARRAY['id','workspace_id','product_id','initiative_id','initiative_version','predecessor_id','action','subject_id','subject_digest','draft_revision_id','policy_decision_id','command_receipt_id']) LOOP\n  IF to_jsonb(NEW)->k IS DISTINCT FROM p->k THEN RAISE EXCEPTION 'MANUAL_GATE2_RECORD_SUBSTITUTION' USING ERRCODE='23514'; END IF;\n END LOOP;\n IF p->>'actor_id' IS DISTINCT FROM NEW.created_by::text OR (p->>'sequence')::bigint<>NEW.version\n  OR (p->>'recorded_at')::timestamptz IS DISTINCT FROM NEW.recorded_at OR NOT isfinite(NEW.recorded_at) OR NEW.recorded_at>clock_timestamp()\n  OR q->>'action' IS DISTINCT FROM NEW.action OR q->>'draft_revision_id' IS DISTINCT FROM NEW.draft_revision_id::text\n  OR q->'rationale_ref' IS DISTINCT FROM p->'rationale_ref'\n  OR (q->'subject_ref'='null'::jsonb) IS DISTINCT FROM (NEW.action='PREPARE')\n  OR (q->'rationale_ref'='null'::jsonb) IS DISTINCT FROM (NEW.action='PREPARE')\n  OR (q->'reconciliation_ref'<>'null'::jsonb) IS DISTINCT FROM (NEW.action='RELEASE')\n  OR (jsonb_array_length(q->'claims')>0) IS DISTINCT FROM (NEW.action IN ('RECONCILE','RELEASE'))\n  OR (p->'subject_metadata'<>'null'::jsonb) IS DISTINCT FROM (NEW.action='PREPARE')\n  OR (p->'reconciliation_id'<>'null'::jsonb) IS DISTINCT FROM (NEW.action='RELEASE') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_REQUEST_SUBSTITUTION' USING ERRCODE='23514';\n END IF;\n SELECT * INTO init FROM curve_initiative WHERE workspace_id=NEW.workspace_id AND id=NEW.initiative_id FOR UPDATE;\n IF NOT FOUND OR init.product_id<>NEW.product_id OR init.mode<>'STANDALONE' OR init.pending_scope_reopening_id IS NOT NULL\n  OR init.version+1<>NEW.initiative_version OR init.state NOT IN ('PLANNING','PAUSED','CANCELLED')\n  OR (NEW.action NOT IN ('RECONCILE','RELEASE') AND init.state<>'PLANNING')\n  OR NOT EXISTS(SELECT 1 FROM curve_product WHERE id=NEW.product_id AND workspace_id=NEW.workspace_id AND state='ACTIVE') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_INITIATIVE_MISMATCH' USING ERRCODE='23514';\n END IF;\n SELECT * INTO draft FROM curve_manual_plan_revision_v2 WHERE id=NEW.draft_revision_id AND workspace_id=NEW.workspace_id\n  AND initiative_id=NEW.initiative_id AND product_id=NEW.product_id;\n IF NOT FOUND THEN RAISE EXCEPTION 'MANUAL_GATE2_DRAFT_REQUIRED' USING ERRCODE='23514'; END IF;\n SELECT * INTO ctl FROM curve_manual_gate2_control_v2 WHERE initiative_id=NEW.initiative_id FOR UPDATE;\n IF FOUND THEN\n  SELECT * INTO prior FROM curve_manual_gate2_record_v2 WHERE id=ctl.current_record_id;\n  IF ctl.id<>NEW.control_id OR ctl.workspace_id<>NEW.workspace_id OR ctl.product_id<>NEW.product_id\n   OR ctl.version+1<>NEW.version OR NEW.predecessor_id IS DISTINCT FROM prior.id\n   OR prior.control_id<>ctl.id OR prior.version<>ctl.version OR prior.initiative_version>=NEW.initiative_version OR prior.recorded_at>NEW.recorded_at THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_INVALID' USING ERRCODE='23514';\n  END IF;\n ELSIF NEW.action<>'PREPARE' OR NEW.version<>1 OR NEW.predecessor_id IS NOT NULL\n  OR EXISTS(SELECT 1 FROM curve_manual_gate2_record_v2 WHERE initiative_id=NEW.initiative_id OR control_id=NEW.control_id) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_INVALID' USING ERRCODE='23514';\n END IF;\n IF NEW.action='PREPARE' THEN\n  s:=p->'subject_metadata';\n  IF NEW.subject_id<>NEW.id OR curve_sprd_digest(s) IS DISTINCT FROM NEW.subject_digest\n   OR s->'input_identity' IS DISTINCT FROM draft.original_input_identity\n   OR s->>'draft_revision_id' IS DISTINCT FROM draft.id::text OR s->>'draft_digest' IS DISTINCT FROM draft.digest\n   OR (s->>'draft_revision')::bigint<>draft.version OR s->>'validation_receipt_digest' IS DISTINCT FROM draft.validation_receipt_digest\n   OR s->>'validator_edition' IS DISTINCT FROM draft.validation_receipt->>'validator_edition'\n   OR s->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text OR s->>'product_id' IS DISTINCT FROM NEW.product_id::text\n   OR s->>'initiative_id' IS DISTINCT FROM NEW.initiative_id::text OR s->>'controlling_prd_decision_id' IS DISTINCT FROM init.controlling_prd_decision_id::text\n   OR s->>'risk_tier' IS DISTINCT FROM init.risk_tier\n   OR (ctl.id IS NOT NULL AND (ctl.approved_record_id IS NOT NULL OR ctl.state NOT IN ('PLAN_REVIEW','CHANGES_REQUESTED')))\n   OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2 WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND current_revision_id=draft.id)\n   OR EXISTS(SELECT 1 FROM curve_manual_gate2_record_v2 WHERE initiative_id=NEW.initiative_id AND action='PREPARE' AND draft_revision_id=draft.id) THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_SUBJECT_INVALID' USING ERRCODE='23514';\n  END IF;\n  SELECT jsonb_agg(jsonb_build_object('workspace_id',i.workspace_id::text,'installation_id',i.provider_installation_id::text,'issue_id',i.source_issue_id::text) ORDER BY i.provider_installation_id,i.source_issue_id)\n   INTO expected_tasks FROM curve_scope_proposal_item i WHERE i.workspace_id=NEW.workspace_id\n    AND i.revision_id=(draft.original_input_identity->'scope_revision_ref'->>'entity_id')::uuid AND i.purpose='PROPOSED_DELIVERY';\n  IF expected_tasks IS NULL OR s->'tasks' IS DISTINCT FROM expected_tasks THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_TASK_SET_INVALID' USING ERRCODE='23514';\n  END IF;\n ELSE\n  SELECT * INTO original FROM curve_manual_gate2_record_v2 WHERE id=NEW.subject_id AND workspace_id=NEW.workspace_id;\n  IF NOT FOUND OR original.action<>'PREPARE' OR original.subject_id<>original.id OR original.initiative_id<>NEW.initiative_id\n   OR original.product_id<>NEW.product_id OR original.draft_revision_id<>draft.id OR original.subject_digest<>NEW.subject_digest\n   OR q->'subject_ref' IS DISTINCT FROM jsonb_build_object('entity_id',original.id::text,'digest',original.subject_digest)\n   OR ctl.subject_id IS DISTINCT FROM original.id OR original.payload->'subject_metadata'->>'controlling_prd_decision_id' IS DISTINCT FROM init.controlling_prd_decision_id::text THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_SUBJECT_SUBSTITUTION' USING ERRCODE='23514';\n  END IF;\n  s:=original.payload->'subject_metadata';\n  IF NEW.action IN ('APPROVE','REQUEST_CHANGES') THEN\n   IF ctl.state<>'PLAN_REVIEW' OR ctl.approved_record_id IS NOT NULL\n    OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_draft_v2 WHERE initiative_id=NEW.initiative_id AND current_revision_id=draft.id)\n    OR s->>'risk_tier' IS DISTINCT FROM init.risk_tier\n    OR NOT EXISTS(SELECT 1 FROM curve_gate_assignment a, jsonb_array_elements(draft.original_input_identity->'gate_assignments') retained_gate\n     WHERE a.workspace_id=NEW.workspace_id AND a.initiative_id=NEW.initiative_id AND a.gate_type='PLAN_APPROVAL'\n      AND a.id=(retained_gate->>'gate_assignment_id')::uuid AND a.approver_user_id=(retained_gate->>'approver_user_id')::uuid\n      AND a.approver_user_id=NEW.created_by AND retained_gate->>'gate_type'='PLAN_APPROVAL' AND a.valid_from<=clock_timestamp() AND (a.valid_until IS NULL OR a.valid_until>clock_timestamp())) THEN\n    RAISE EXCEPTION 'MANUAL_GATE2_CURRENT_REVIEW_REQUIRED' USING ERRCODE='23514';\n   END IF;\n  ELSIF ctl.state<>'MANUAL_APPROVED' OR ctl.approved_record_id IS NULL THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_APPROVAL_REQUIRED' USING ERRCODE='23514';\n  END IF;\n END IF;\n IF NOT EXISTS(SELECT 1 FROM curve_scoped_prd_subject sp JOIN curve_scoped_prd_decision d ON d.scoped_subject_id=sp.id\n  JOIN curve_prd_review_decision b ON b.id=d.decision_id\n  WHERE sp.workspace_id=NEW.workspace_id AND sp.initiative_id=NEW.initiative_id AND sp.product_id=NEW.product_id\n   AND sp.id=(draft.payload->'approved_subject_ref'->>'entity_id')::uuid AND sp.digest=draft.payload->'approved_subject_ref'->>'digest'\n   AND sp.checkpoint_id=init.current_prd_checkpoint_id AND d.workspace_id=NEW.workspace_id AND d.initiative_id=NEW.initiative_id\n   AND b.workspace_id=NEW.workspace_id AND b.initiative_id=NEW.initiative_id AND d.decision_id=init.controlling_prd_decision_id\n   AND d.payload->>'state'='APPROVED' AND b.state='APPROVED') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_APPROVED_PRD_REQUIRED' USING ERRCODE='23514';\n END IF;\n IF NEW.action<>'PREPARE' AND (SELECT count(*) FROM curve_gate_assignment WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id\n  AND gate_type='PLAN_APPROVAL' AND approver_user_id=NEW.created_by AND valid_from<=clock_timestamp() AND (valid_until IS NULL OR valid_until>clock_timestamp()))<>1 THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_APPROVER_REQUIRED' USING ERRCODE='23514';\n END IF;\n IF (NEW.action IN ('PREPARE','REQUEST_CHANGES','RECONCILE') AND p->'claims'<>'[]'::jsonb)\n  OR (NEW.action NOT IN ('RECONCILE','RELEASE') AND p->'observations'<>'[]'::jsonb)\n  OR (NEW.action IN ('APPROVE','RELEASE') AND jsonb_array_length(p->'claims')=0) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_SET_INVALID' USING ERRCODE='23514';\n END IF;\n IF NEW.action='APPROVE' AND (SELECT jsonb_agg(jsonb_build_object('workspace_id',NEW.workspace_id::text,'installation_id',c->>'installation_id','issue_id',c->>'issue_id') ORDER BY c->>'installation_id',c->>'issue_id') FROM jsonb_array_elements(p->'claims') c) IS DISTINCT FROM s->'tasks' THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_SET_INVALID' USING ERRCODE='23514';\n END IF;\n IF NEW.action IN ('RECONCILE','RELEASE') THEN\n  IF (SELECT jsonb_agg(jsonb_build_object('claim_id',c->>'claim_id','generation',c->'generation') ORDER BY c->>'claim_id') FROM jsonb_array_elements(p->'observations') c) IS DISTINCT FROM q->'claims'\n   OR (SELECT count(DISTINCT c->>'claim_id') FROM jsonb_array_elements(p->'observations') c)<>jsonb_array_length(p->'observations') THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_OBSERVATIONS_INVALID' USING ERRCODE='23514';\n  END IF;\n  PERFORM 1 FROM curve_manual_task_claim_v2 c WHERE c.workspace_id=NEW.workspace_id AND c.id IN (SELECT (x->>'claim_id')::uuid FROM jsonb_array_elements(q->'claims') x) ORDER BY c.id FOR UPDATE;\n  IF EXISTS(SELECT 1 FROM jsonb_array_elements(p->'observations') o WHERE NOT EXISTS(SELECT 1 FROM curve_manual_task_claim_v2 c\n   WHERE c.workspace_id=NEW.workspace_id AND c.id=(o->>'claim_id')::uuid AND c.initiative_id=NEW.initiative_id AND c.subject_id=NEW.subject_id\n    AND c.generation=(o->>'generation')::bigint AND c.installation_id=(o->>'installation_id')::uuid AND c.issue_id=(o->>'issue_id')::uuid AND c.state='ACTIVE')) THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_GENERATION_CONFLICT' USING ERRCODE='23514';\n  END IF;\n END IF;\n IF NEW.action='RELEASE' THEN\n  SELECT * INTO prior FROM curve_manual_gate2_record_v2 WHERE id=(q->'reconciliation_ref'->>'entity_id')::uuid;\n  IF NOT FOUND OR prior.workspace_id<>NEW.workspace_id OR prior.initiative_id<>NEW.initiative_id OR prior.subject_id<>NEW.subject_id\n   OR prior.action<>'RECONCILE' OR prior.created_by<>NEW.created_by OR prior.digest IS DISTINCT FROM q->'reconciliation_ref'->>'digest'\n   OR prior.id::text IS DISTINCT FROM p->>'reconciliation_id' OR prior.payload->'native_fence_digest' IS DISTINCT FROM p->'native_fence_digest'\n   OR prior.payload->'rationale_ref' IS DISTINCT FROM p->'rationale_ref' OR prior.payload->'observations' IS DISTINCT FROM p->'observations'\n   OR prior.request_payload->'claims' IS DISTINCT FROM q->'claims'\n   OR (SELECT jsonb_agg(jsonb_build_object('claim_id',c->>'claim_id','generation',c->'generation') ORDER BY c->>'claim_id') FROM jsonb_array_elements(p->'claims') c) IS DISTINCT FROM q->'claims' THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_RECONCILIATION_REQUIRED' USING ERRCODE='23514';\n  END IF;\n END IF;\n actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);\n IF NOT EXISTS(SELECT 1 FROM curve_policy_decision WHERE workspace_id=NEW.workspace_id AND id=NEW.policy_decision_id\n  AND action='CURVE.MANUAL_GATE2.'||NEW.action||'_V2' AND effect='ALLOW' AND policy_key='CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2'\n  AND policy_version=2 AND policy_manifest_digest='sha256:b77e1c16465b9ebdea65ffa37915bee9239a616f667a72f8e6ad978df8833514' AND resource_type='INITIATIVE' AND resource_id=NEW.initiative_id AND resource_version=init.version\n  AND input_digest=curve_sprd_digest(jsonb_build_object('request_digest',NEW.request_digest,'native_fence_digest',p->>'native_fence_digest'))\n  AND subject=actor AND effective_principal=actor AND permitted_projection='[\"MANUAL_GATE2_METADATA_V2\"]'::jsonb\n  AND curve_sprd_created_here('curve_policy_decision',workspace_id,id)) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_POLICY_REQUIRED' USING ERRCODE='23514';\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER curve_mg2r_insert BEFORE INSERT ON curve_manual_gate2_record_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_record_insert();\nCREATE TRIGGER curve_mg2r_stamp AFTER INSERT ON curve_manual_gate2_record_v2 FOR EACH ROW EXECUTE FUNCTION curve_sprd_stamp();\n\nCREATE FUNCTION curve_mg2_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE r curve_manual_gate2_record_v2;\nBEGIN\n SELECT * INTO r FROM curve_manual_gate2_record_v2 WHERE id=NEW.current_record_id;\n IF NOT FOUND OR r.workspace_id<>NEW.workspace_id OR r.initiative_id<>NEW.initiative_id OR r.product_id<>NEW.product_id\n  OR r.control_id<>NEW.id OR r.version<>NEW.version OR r.subject_id<>NEW.subject_id\n  OR NOT curve_sprd_created_here('curve_manual_gate2_record_v2',r.workspace_id,r.id)\n  OR (r.action='PREPARE' AND NEW.state<>'PLAN_REVIEW') OR (r.action='REQUEST_CHANGES' AND NEW.state<>'CHANGES_REQUESTED')\n  OR (r.action IN ('APPROVE','RECONCILE') AND NEW.state<>'MANUAL_APPROVED') OR (r.action='RELEASE' AND NEW.state NOT IN ('MANUAL_APPROVED','RELEASED')) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_HEAD_INVALID' USING ERRCODE='23514';\n END IF;\n IF TG_OP='INSERT' THEN\n  IF NEW.version<>1 OR r.action<>'PREPARE' OR NEW.approved_record_id IS NOT NULL THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_HEAD_INVALID' USING ERRCODE='23514'; END IF;\n ELSE\n  IF (to_jsonb(NEW)-ARRAY['version','current_record_id','subject_id','state','approved_record_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','current_record_id','subject_id','state','approved_record_id'])\n   OR NEW.version<>OLD.version+1 OR r.predecessor_id IS DISTINCT FROM OLD.current_record_id\n   OR (r.action='APPROVE' AND (OLD.approved_record_id IS NOT NULL OR NEW.approved_record_id IS DISTINCT FROM r.id))\n   OR (r.action<>'APPROVE' AND NEW.approved_record_id IS DISTINCT FROM OLD.approved_record_id)\n   OR (r.action<>'PREPARE' AND NEW.subject_id IS DISTINCT FROM OLD.subject_id) THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_HEAD_REWRITE' USING ERRCODE='23514'; END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER curve_mg2c_head BEFORE INSERT OR UPDATE ON curve_manual_gate2_control_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_head_guard();\n\nCREATE FUNCTION curve_mg2_claim_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE r curve_manual_gate2_record_v2; expected jsonb;\nBEGIN\n SELECT * INTO r FROM curve_manual_gate2_record_v2 WHERE workspace_id=NEW.workspace_id AND id=NEW.current_record_id;\n expected:=jsonb_build_object('claim_id',NEW.id::text,'history_id',NEW.current_history_id::text,'installation_id',NEW.installation_id::text,'issue_id',NEW.issue_id::text,\n  'initiative_id',NEW.initiative_id::text,'subject_id',NEW.subject_id::text,'generation',NEW.generation,'state',NEW.state,'record_id',NEW.current_record_id::text);\n IF NOT FOUND OR r.action NOT IN ('APPROVE','RELEASE') OR r.initiative_id<>NEW.initiative_id OR r.subject_id<>NEW.subject_id\n  OR NOT curve_sprd_created_here('curve_manual_gate2_record_v2',r.workspace_id,r.id)\n  OR (SELECT count(*) FROM jsonb_array_elements(r.payload->'claims') v WHERE v=expected)<>1\n  OR NOT EXISTS(SELECT 1 FROM issues WHERE workspace_id=NEW.workspace_id AND id=NEW.issue_id) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_INVALID' USING ERRCODE='23514';\n END IF;\n PERFORM 1 FROM issues WHERE workspace_id=NEW.workspace_id AND id=NEW.issue_id FOR UPDATE;\n IF TG_OP='INSERT' THEN\n  IF r.action<>'APPROVE' OR NEW.generation<>1 OR NEW.state<>'ACTIVE' THEN RAISE EXCEPTION 'MANUAL_GATE2_FIRST_CLAIM_INVALID' USING ERRCODE='23514'; END IF;\n ELSE\n  IF (to_jsonb(NEW)-ARRAY['initiative_id','subject_id','generation','state','current_record_id','current_history_id']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['initiative_id','subject_id','generation','state','current_record_id','current_history_id'])\n   OR NEW.current_record_id=OLD.current_record_id OR NEW.current_history_id=OLD.current_history_id THEN\n   RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_IDENTITY_IMMUTABLE' USING ERRCODE='23514'; END IF;\n  IF r.action='APPROVE' THEN\n   IF OLD.state<>'RELEASED' OR NEW.state<>'ACTIVE' OR NEW.generation<>OLD.generation+1 THEN RAISE EXCEPTION 'MANUAL_GATE2_CLAIM_OCCUPIED' USING ERRCODE='23514'; END IF;\n  ELSE\n   IF OLD.state<>'ACTIVE' OR NEW.state<>'RELEASED' OR NEW.generation<>OLD.generation OR NEW.initiative_id<>OLD.initiative_id OR NEW.subject_id<>OLD.subject_id THEN\n    RAISE EXCEPTION 'MANUAL_GATE2_RELEASE_CONFLICT' USING ERRCODE='23514'; END IF;\n  END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER curve_mtc2_head BEFORE INSERT OR UPDATE ON curve_manual_task_claim_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_claim_guard();\n\nCREATE FUNCTION curve_mg2_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE r curve_manual_gate2_record_v2; c curve_manual_task_claim_v2; p jsonb:=NEW.payload;\nBEGIN\n SELECT * INTO r FROM curve_manual_gate2_record_v2 WHERE id=NEW.record_id AND workspace_id=NEW.workspace_id;\n SELECT * INTO c FROM curve_manual_task_claim_v2 WHERE id=NEW.claim_id AND workspace_id=NEW.workspace_id;\n IF r.id IS NULL OR c.id IS NULL OR NOT curve_sprd_created_here('curve_manual_gate2_record_v2',r.workspace_id,r.id)\n  OR (SELECT count(*) FROM jsonb_array_elements(r.payload->'claims') v WHERE v=p)<>1\n  OR c.current_history_id<>NEW.id OR c.current_record_id<>r.id OR c.initiative_id<>NEW.initiative_id OR c.generation<>NEW.generation OR c.state<>NEW.state\n  OR p->>'claim_id' IS DISTINCT FROM c.id::text OR p->>'history_id' IS DISTINCT FROM NEW.id::text\n  OR p->>'record_id' IS DISTINCT FROM r.id::text OR p->>'installation_id' IS DISTINCT FROM c.installation_id::text\n  OR p->>'issue_id' IS DISTINCT FROM c.issue_id::text OR p->>'subject_id' IS DISTINCT FROM c.subject_id::text\n  OR p->>'initiative_id' IS DISTINCT FROM c.initiative_id::text OR (p->>'generation')::bigint IS DISTINCT FROM c.generation OR p->>'state' IS DISTINCT FROM c.state THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_HISTORY_INVALID' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER curve_mtch2_insert BEFORE INSERT ON curve_manual_task_claim_history_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_history_guard();\n\nCREATE FUNCTION curve_mg2_commit_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nDECLARE init curve_initiative; ctl curve_manual_gate2_control_v2; e curve_domain_event; ref jsonb; v_actor jsonb; v_response text; expected_event jsonb;\nBEGIN\n SELECT * INTO init FROM curve_initiative WHERE id=NEW.initiative_id AND workspace_id=NEW.workspace_id;\n SELECT * INTO ctl FROM curve_manual_gate2_control_v2 WHERE id=NEW.control_id AND workspace_id=NEW.workspace_id;\n v_actor:=jsonb_build_object('actor_type','HUMAN','actor_id',NEW.created_by::text);\n IF init.id IS NULL OR ctl.id IS NULL OR init.version<>NEW.initiative_version OR init.updated_by IS DISTINCT FROM v_actor\n  OR init.product_id<>NEW.product_id OR init.state NOT IN ('PLANNING','PAUSED','CANCELLED')\n  OR ctl.current_record_id<>NEW.id OR ctl.version<>NEW.version OR ctl.initiative_id<>NEW.initiative_id\n  OR (NEW.action='APPROVE' AND ctl.approved_record_id IS DISTINCT FROM NEW.id)\n  OR (NEW.action='RELEASE' AND ((ctl.state='RELEASED') IS DISTINCT FROM NOT EXISTS(SELECT 1 FROM curve_manual_task_claim_v2 WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND subject_id=NEW.subject_id AND state='ACTIVE')))\n  OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.payload->'claims') c WHERE NOT EXISTS(SELECT 1 FROM curve_manual_task_claim_history_v2 h JOIN curve_manual_task_claim_v2 t ON t.id=h.claim_id AND t.workspace_id=h.workspace_id\n   WHERE h.id=(c->>'history_id')::uuid AND h.workspace_id=NEW.workspace_id AND h.record_id=NEW.id AND h.payload=c\n    AND t.current_history_id=h.id AND t.current_record_id=NEW.id))\n  OR (SELECT count(*) FROM curve_manual_task_claim_history_v2 WHERE record_id=NEW.id)<>jsonb_array_length(NEW.payload->'claims') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_GRAPH_INCOMPLETE' USING ERRCODE='23514';\n END IF;\n expected_event:=jsonb_build_object('schema_version','curve.manual-gate2.event/v2-candidate','record_id',NEW.id::text,'record_digest',NEW.digest,\n  'subject_digest',NEW.subject_digest,'action',NEW.action,'policy_decision_id',NEW.policy_decision_id::text,'execution_authorized',false,'completion_credit',false);\n SELECT * INTO e FROM curve_domain_event WHERE id=NEW.command_receipt_id AND workspace_id=NEW.workspace_id;\n IF NOT FOUND OR e.event_type<>'CURVE.MANUAL_GATE2_RECORDED_V2' OR e.schema_version<>'1.0' OR e.initiative_id IS DISTINCT FROM NEW.initiative_id OR e.workflow_version_id IS DISTINCT FROM init.workflow_version_id OR e.aggregate_type<>'MANUAL_GATE2_CONTROL_V2'\n  OR e.aggregate_id<>NEW.control_id OR e.aggregate_version<>NEW.version OR e.sequence<>NEW.version OR e.payload IS DISTINCT FROM expected_event\n  OR NOT curve_mpd2_shape(e.payload,curve_mg2_schema('event')) OR e.actor IS DISTINCT FROM v_actor OR e.effective_principal IS DISTINCT FROM v_actor\n  OR e.payload_schema<>'https://curve.example.invalid/candidates/manual-gate2-v2/event.schema.json'\n  OR NOT curve_sprd_created_here('curve_domain_event',NEW.workspace_id,e.id)\n  OR NOT EXISTS(SELECT 1 FROM curve_outbox_event WHERE workspace_id=NEW.workspace_id AND event_id=e.id AND destination='curve-local-manual-gate2-v2'\n   AND curve_sprd_created_here('curve_outbox_event',workspace_id,id)) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_EVENT_INCOMPLETE' USING ERRCODE='23514';\n END IF;\n ref:=jsonb_build_object('resource_type','MANUAL_GATE2_RECORD_V2','resource_id',NEW.id::text,'resource_version',NEW.version);\n v_response:=curve_sprd_digest(jsonb_build_object('response_status',201,'response_resource_ref',ref));\n IF NOT EXISTS(SELECT 1 FROM curve_idempotency_record i WHERE i.workspace_id=NEW.workspace_id\n  AND i.principal_scope='HUMAN:'||NEW.created_by::text AND i.command_scope='CURVE.MANUAL_GATE2.'||NEW.action||'_V2:'||NEW.initiative_id::text\n  AND i.key_digest=e.idempotency_key_digest AND i.request_digest=NEW.request_digest AND i.state='COMPLETED'\n  AND i.response_status=201 AND i.response_resource_ref=ref AND i.response_digest=v_response\n  AND curve_sprd_created_here('curve_idempotency_record',i.workspace_id,i.id)) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_IDEMPOTENCY_INCOMPLETE' USING ERRCODE='23514';\n END IF;\n IF (SELECT count(*) FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id AND a.policy_decision_ref->>'resource_id'=NEW.policy_decision_id::text)<>1\n  OR NOT EXISTS(SELECT 1 FROM curve_audit_event a WHERE a.workspace_id=NEW.workspace_id AND a.action='CURVE.MANUAL_GATE2.'||NEW.action||'_V2'\n   AND a.target_type='MANUAL_GATE2_RECORD_V2' AND a.target_id=NEW.id AND a.target_ref=ref AND a.outcome='SUCCEEDED' AND a.actor=v_actor AND a.effective_principal=v_actor\n   AND a.idempotency_key_digest=e.idempotency_key_digest AND a.after_digest=v_response\n   AND a.policy_decision_ref=jsonb_build_object('resource_type','POLICY_DECISION','resource_id',NEW.policy_decision_id::text,'resource_version',1)\n   AND curve_sprd_created_here('curve_audit_event',a.workspace_id,a.id)) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_AUDIT_INCOMPLETE' USING ERRCODE='23514';\n END IF;\n RETURN NULL;\nEND $$;\nCREATE CONSTRAINT TRIGGER curve_mg2r_commit AFTER INSERT ON curve_manual_gate2_record_v2 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION curve_mg2_commit_guard();\n\nCREATE FUNCTION curve_mg2_preplan_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN\n IF EXISTS(SELECT 1 FROM curve_manual_gate2_control_v2 WHERE workspace_id=NEW.workspace_id AND initiative_id=NEW.initiative_id AND approved_record_id IS NOT NULL) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_PREPLAN_CLOSED' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER curve_mg2_draft_closed BEFORE INSERT ON curve_manual_plan_revision_v2 FOR EACH ROW EXECUTE FUNCTION curve_mg2_preplan_guard();\nCREATE TRIGGER curve_mg2_reopen_closed BEFORE INSERT ON curve_scope_reopening FOR EACH ROW EXECUTE FUNCTION curve_mg2_preplan_guard();\nCREATE TRIGGER curve_mg2_scope_closed BEFORE INSERT ON curve_scope_proposal_revision FOR EACH ROW EXECUTE FUNCTION curve_mg2_preplan_guard();\nCREATE FUNCTION curve_mg2_initiative_guard() RETURNS trigger LANGUAGE plpgsql AS $$\nBEGIN\n IF EXISTS(SELECT 1 FROM curve_manual_gate2_control_v2 WHERE workspace_id=OLD.workspace_id AND initiative_id=OLD.id AND approved_record_id IS NOT NULL)\n AND (NEW.state NOT IN ('PLANNING','PAUSED','CANCELLED')\n  OR (to_jsonb(NEW)-ARRAY['version','state','paused_from_state','updated_at','updated_by']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['version','state','paused_from_state','updated_at','updated_by'])) THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_APPROVED_CONTEXT_IMMUTABLE' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER curve_mg2_init_closed BEFORE UPDATE ON curve_initiative FOR EACH ROW EXECUTE FUNCTION curve_mg2_initiative_guard();\n\nCREATE TABLE curve_manual_gate2_v2_coverage(edition text PRIMARY KEY, catalog_digest text NOT NULL);\nCREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$\nDECLARE expected text; actual text;\nBEGIN\n IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage\n  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7')\n  OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_manual_plan_v2_coverage\n  WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2' AND catalog_digest='sha256:4f0c5e4b1ba7c5e00a3cf35fa55092cb71f571fa34a564f2859af7a46b0b67e8') THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514'; END IF;\n SELECT catalog_digest INTO expected FROM curve_manual_gate2_v2_coverage WHERE edition='CURVE_MANUAL_GATE2_RECONSTRUCTION_V2';\n actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');\n IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_gate2_v2_coverage)<>1 THEN\n  RAISE EXCEPTION 'MANUAL_GATE2_COVERAGE_UNAVAILABLE' USING ERRCODE='23514'; END IF;\nEND $$;\n\nALTER TABLE curve_manual_gate2_control_v2 ADD CONSTRAINT curve_mg2c_init_fk FOREIGN KEY(workspace_id,initiative_id) REFERENCES curve_initiative(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_record_v2 ADD CONSTRAINT curve_mg2r_control_fk FOREIGN KEY(workspace_id,control_id) REFERENCES curve_manual_gate2_control_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_control_v2 ADD CONSTRAINT curve_mg2c_record_fk FOREIGN KEY(workspace_id,current_record_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_control_v2 ADD CONSTRAINT curve_mg2c_subject_fk FOREIGN KEY(workspace_id,subject_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_control_v2 ADD CONSTRAINT curve_mg2c_approval_fk FOREIGN KEY(workspace_id,approved_record_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_record_v2 ADD CONSTRAINT curve_mg2r_draft_fk FOREIGN KEY(workspace_id,draft_revision_id) REFERENCES curve_manual_plan_revision_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_record_v2 ADD CONSTRAINT curve_mg2r_prev_fk FOREIGN KEY(workspace_id,predecessor_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_record_v2 ADD CONSTRAINT curve_mg2r_subject_fk FOREIGN KEY(workspace_id,subject_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_record_v2 ADD CONSTRAINT curve_mg2r_policy_fk FOREIGN KEY(policy_decision_id) REFERENCES curve_policy_decision(id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_gate2_record_v2 ADD CONSTRAINT curve_mg2r_event_fk FOREIGN KEY(command_receipt_id) REFERENCES curve_domain_event(id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_task_claim_v2 ADD CONSTRAINT curve_mtc2_record_fk FOREIGN KEY(workspace_id,current_record_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_task_claim_v2 ADD CONSTRAINT curve_mtc2_history_fk FOREIGN KEY(workspace_id,current_history_id) REFERENCES curve_manual_task_claim_history_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_task_claim_history_v2 ADD CONSTRAINT curve_mtch2_record_fk FOREIGN KEY(workspace_id,record_id) REFERENCES curve_manual_gate2_record_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nALTER TABLE curve_manual_task_claim_history_v2 ADD CONSTRAINT curve_mtch2_claim_fk FOREIGN KEY(workspace_id,claim_id) REFERENCES curve_manual_task_claim_v2(workspace_id,id) DEFERRABLE INITIALLY DEFERRED;\nCREATE TRIGGER curve_mg2c_immutable BEFORE DELETE ON curve_manual_gate2_control_v2 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mg2c_no_truncate BEFORE TRUNCATE ON curve_manual_gate2_control_v2 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mg2r_immutable BEFORE UPDATE OR DELETE ON curve_manual_gate2_record_v2 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mg2r_no_truncate BEFORE TRUNCATE ON curve_manual_gate2_record_v2 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mtc2_immutable BEFORE DELETE ON curve_manual_task_claim_v2 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mtc2_no_truncate BEFORE TRUNCATE ON curve_manual_task_claim_v2 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mtch2_immutable BEFORE UPDATE OR DELETE ON curve_manual_task_claim_history_v2 FOR EACH ROW EXECUTE FUNCTION curve_mpd2_immutable();\nCREATE TRIGGER curve_mtch2_no_truncate BEFORE TRUNCATE ON curve_manual_task_claim_history_v2 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"

REVERSE_SQL = "DROP TRIGGER curve_mg2r_insert ON curve_manual_gate2_record_v2;\nDROP TRIGGER curve_mg2r_stamp ON curve_manual_gate2_record_v2;\nDROP TRIGGER curve_mg2c_head ON curve_manual_gate2_control_v2;\nDROP TRIGGER curve_mtc2_head ON curve_manual_task_claim_v2;\nDROP TRIGGER curve_mtch2_insert ON curve_manual_task_claim_history_v2;\nDROP TRIGGER curve_mg2r_commit ON curve_manual_gate2_record_v2;\nDROP TRIGGER curve_mg2_draft_closed ON curve_manual_plan_revision_v2;\nDROP TRIGGER curve_mg2_reopen_closed ON curve_scope_reopening;\nDROP TRIGGER curve_mg2_scope_closed ON curve_scope_proposal_revision;\nDROP TRIGGER curve_mg2_init_closed ON curve_initiative;\nDROP TRIGGER curve_mg2c_immutable ON curve_manual_gate2_control_v2;\nDROP TRIGGER curve_mg2c_no_truncate ON curve_manual_gate2_control_v2;\nDROP TRIGGER curve_mg2r_immutable ON curve_manual_gate2_record_v2;\nDROP TRIGGER curve_mg2r_no_truncate ON curve_manual_gate2_record_v2;\nDROP TRIGGER curve_mtc2_immutable ON curve_manual_task_claim_v2;\nDROP TRIGGER curve_mtc2_no_truncate ON curve_manual_task_claim_v2;\nDROP TRIGGER curve_mtch2_immutable ON curve_manual_task_claim_history_v2;\nDROP TRIGGER curve_mtch2_no_truncate ON curve_manual_task_claim_history_v2;\nDROP TABLE curve_manual_gate2_v2_coverage;\nDROP FUNCTION curve_mg2_record_insert();\nDROP FUNCTION curve_mg2_head_guard();\nDROP FUNCTION curve_mg2_claim_guard();\nDROP FUNCTION curve_mg2_history_guard();\nDROP FUNCTION curve_mg2_commit_guard();\nDROP FUNCTION curve_mg2_preplan_guard();\nDROP FUNCTION curve_mg2_initiative_guard();\nDROP FUNCTION curve_mg2_schema(text);\nALTER TABLE curve_manual_gate2_control_v2 DROP CONSTRAINT curve_mg2c_init_fk;\nALTER TABLE curve_manual_gate2_record_v2 DROP CONSTRAINT curve_mg2r_control_fk;\nALTER TABLE curve_manual_gate2_control_v2 DROP CONSTRAINT curve_mg2c_record_fk;\nALTER TABLE curve_manual_gate2_control_v2 DROP CONSTRAINT curve_mg2c_subject_fk;\nALTER TABLE curve_manual_gate2_control_v2 DROP CONSTRAINT curve_mg2c_approval_fk;\nALTER TABLE curve_manual_gate2_record_v2 DROP CONSTRAINT curve_mg2r_draft_fk;\nALTER TABLE curve_manual_gate2_record_v2 DROP CONSTRAINT curve_mg2r_prev_fk;\nALTER TABLE curve_manual_gate2_record_v2 DROP CONSTRAINT curve_mg2r_subject_fk;\nALTER TABLE curve_manual_gate2_record_v2 DROP CONSTRAINT curve_mg2r_policy_fk;\nALTER TABLE curve_manual_gate2_record_v2 DROP CONSTRAINT curve_mg2r_event_fk;\nALTER TABLE curve_manual_task_claim_v2 DROP CONSTRAINT curve_mtc2_record_fk;\nALTER TABLE curve_manual_task_claim_v2 DROP CONSTRAINT curve_mtc2_history_fk;\nALTER TABLE curve_manual_task_claim_history_v2 DROP CONSTRAINT curve_mtch2_record_fk;\nALTER TABLE curve_manual_task_claim_history_v2 DROP CONSTRAINT curve_mtch2_claim_fk;\nCREATE OR REPLACE FUNCTION curve_scope_reopening_verify_coverage() RETURNS void LANGUAGE plpgsql AS $$\nDECLARE expected text; actual text;\nBEGIN\n IF (SELECT count(*) FROM curve_scope_reopening_coverage)<>1 OR NOT EXISTS(SELECT 1 FROM curve_scope_reopening_coverage\n  WHERE edition='CURVE_PRE_PLAN_C2B_V1' AND catalog_digest='sha256:e44c580ea214e03b315c2b14c038cb14ae5d99fa8a60115e82d6b5841ac177a7') THEN\n  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_PREDECESSOR_SEAL_INVALID' USING ERRCODE='23514';\n END IF;\n SELECT catalog_digest INTO expected FROM curve_manual_plan_v2_coverage WHERE edition='CURVE_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V2';\n actual:='sha256:'||encode(sha256(convert_to(curve_scope_reopening_catalog()::text,'UTF8')),'hex');\n IF expected IS NULL OR expected IS DISTINCT FROM actual OR (SELECT count(*) FROM curve_manual_plan_v2_coverage)<>1 THEN\n  RAISE EXCEPTION 'MANUAL_PLAN_DRAFT_COVERAGE_UNAVAILABLE' USING ERRCODE='23514';\n END IF;\nEND $$;\n\nCREATE OR REPLACE FUNCTION curve_scope_reopening_catalog() RETURNS jsonb LANGUAGE sql STABLE\n SET search_path=pg_catalog,public AS $catalog$\nSELECT jsonb_build_object(\n 'tables', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind,c.relpersistence AS persistence,\n   c.relrowsecurity AS row_security,c.relforcerowsecurity AS force_row_security\n  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','v','m','f')\n   AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'columns', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,position),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,row_number() OVER (PARTITION BY n.nspname,c.relname ORDER BY a.attnum) AS position,a.attname AS name,\n   format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull AS not_null,a.attidentity AS identity_kind,\n   a.attgenerated AS generated_kind,pg_get_expr(d.adbin,d.adrelid,true) AS default_expression,\n   co.collname AS collation\n  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid\n  LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND c.relkind IN ('r','p','v','m','f')\n   AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND a.attnum>0 AND NOT a.attisdropped) r),\n 'constraints', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,k.conname AS name,k.contype AS kind,\n   pg_get_constraintdef(k.oid,true) AS definition,k.condeferrable AS deferrable,\n   k.condeferred AS initially_deferred,k.convalidated AS validated,k.connoinherit AS no_inherit\n  FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'triggers', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name,definition),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,\n   CASE WHEN t.tgisinternal THEN '<internal>' ELSE t.tgname END AS name,t.tgisinternal AS internal,\n   t.tgenabled AS enabled,CASE WHEN t.tgisinternal THEN regexp_replace(pg_get_triggerdef(t.oid,true),\n    'TRIGGER \"?RI_ConstraintTrigger_[ac]_[0-9]+\"?', 'TRIGGER <internal>') ELSE pg_get_triggerdef(t.oid,true) END AS definition,\n   k.conname AS constraint_name,pn.nspname AS function_schema,p.proname AS function_name,\n   pg_get_function_identity_arguments(p.oid) AS function_identity_arguments\n  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace\n  JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace\n  LEFT JOIN pg_constraint k ON k.oid=t.tgconstraint\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'indexes', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,c.relname AS table_name,i.relname AS name,pg_get_indexdef(i.oid) AS definition,\n   x.indisunique AS unique,x.indisprimary AS primary_key,x.indisvalid AS valid,x.indisready AS ready\n  FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid\n  JOIN pg_namespace n ON n.oid=c.relnamespace\n  WHERE c.relname LIKE 'curve\\_%' ESCAPE '\\' AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema') r),\n 'functions', (SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,name,identity_arguments),'[]'::jsonb) FROM (\n  SELECT n.nspname AS schema,p.proname AS name,pg_get_function_identity_arguments(p.oid) AS identity_arguments,\n   pg_get_functiondef(p.oid) AS definition,p.proconfig AS configuration\n  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace\n  WHERE p.prokind IN ('f','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'\n   AND (p.proname LIKE 'curve\\_%' ESCAPE '\\' OR EXISTS(\n    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid\n     WHERE t.tgfoid=p.oid AND c.relname LIKE 'curve\\_%' ESCAPE '\\'))) r)\n)\n$catalog$;"

SEAL_SQL = "CREATE TRIGGER curve_mg2_coverage_immutable BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON curve_manual_gate2_v2_coverage FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();"


def _catalog(cursor):
    cursor.execute("SELECT to_regclass('curve_manual_gate2_control_v2')")
    sql = (
        CATALOG_SQL
        if cursor.fetchone()[0] is not None
        else import_module("plane.curve.migrations.0023_scope_reopening").CATALOG_SQL
    )
    cursor.execute("SHOW search_path")
    previous_path = cursor.fetchone()[0]
    cursor.execute("SET LOCAL search_path = pg_catalog, public")
    cursor.execute(
        "SELECT 'sha256:' || encode(sha256(convert_to(("
        + sql
        + ")::text, 'UTF8')), 'hex')"
    )
    result = cursor.fetchone()[0]
    cursor.execute("SELECT set_config('search_path', %s, true)", [previous_path])
    return result


def verify_predecessor(apps, schema_editor):
    if (
        CURRENT_CATALOG_DIGEST is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", CURRENT_CATALOG_DIGEST) is None
    ):
        raise RuntimeError("MANUAL_GATE2_POSTGRESQL_QUALIFICATION_REQUIRED")
    directory = Path(__file__).parent
    for name, expected in PREDECESSOR_MIGRATIONS.items():
        if (
            "sha256:" + hashlib.sha256((directory / name).read_bytes()).hexdigest()
            != expected
        ):
            raise RuntimeError("MANUAL_GATE2_PREDECESSOR_BYTES_CHANGED")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM django_migrations WHERE app='curve' ORDER BY name"
        )
        if [row[0] + ".py" for row in cursor.fetchall()] != sorted(
            PREDECESSOR_MIGRATIONS
        ):
            raise RuntimeError("MANUAL_GATE2_PREDECESSOR_MIGRATIONS_CHANGED")
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_GATE2_PREDECESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def install_seal(apps, schema_editor):
    if CURRENT_CATALOG_DIGEST is None:
        raise RuntimeError("MANUAL_GATE2_POSTGRESQL_QUALIFICATION_REQUIRED")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO curve_manual_gate2_v2_coverage(edition,catalog_digest) VALUES (%s,%s)",
            ["CURVE_MANUAL_GATE2_RECONSTRUCTION_V2", CURRENT_CATALOG_DIGEST],
        )


def verify_successor(apps, schema_editor):
    for statement in schema_editor.deferred_sql:
        schema_editor.execute(statement)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != CURRENT_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_GATE2_SUCCESSOR_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


def require_empty_reverse(apps, schema_editor):
    if not schema_editor.connection.in_atomic_block:
        raise RuntimeError("MANUAL_GATE2_ATOMIC_REVERSAL_REQUIRED")
    with schema_editor.connection.cursor() as cursor:
        # Prevent evidence from appearing between the emptiness check and DDL.
        # Locks remain held by the enclosing atomic migration until completion.
        cursor.execute("""LOCK TABLE curve_audit_event, curve_domain_event, curve_idempotency_record,
          curve_manual_gate2_control_v2, curve_manual_gate2_record_v2, curve_manual_task_claim_v2,
          curve_manual_task_claim_history_v2, curve_outbox_event, curve_policy_decision IN ACCESS EXCLUSIVE MODE""")
        cursor.execute("""SELECT EXISTS(SELECT 1 FROM curve_manual_gate2_control_v2)
          OR EXISTS(SELECT 1 FROM curve_manual_gate2_record_v2) OR EXISTS(SELECT 1 FROM curve_manual_task_claim_v2)
          OR EXISTS(SELECT 1 FROM curve_manual_task_claim_history_v2)
          OR EXISTS(SELECT 1 FROM curve_policy_decision WHERE policy_key='CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2')
          OR EXISTS(SELECT 1 FROM curve_domain_event WHERE event_type='CURVE.MANUAL_GATE2_RECORDED_V2')
          OR EXISTS(SELECT 1 FROM curve_audit_event WHERE action LIKE 'CURVE.MANUAL_GATE2.%')
          OR EXISTS(SELECT 1 FROM curve_idempotency_record WHERE command_scope LIKE 'CURVE.MANUAL_GATE2.%')
          OR EXISTS(SELECT 1 FROM curve_outbox_event WHERE destination='curve-local-manual-gate2-v2')""")
        if cursor.fetchone()[0]:
            raise RuntimeError("MANUAL_GATE2_RETAINED_EVIDENCE_PREVENTS_REVERSE")


def verify_empty_predecessor(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if _catalog(cursor) != BASELINE_CATALOG_DIGEST:
            raise RuntimeError("MANUAL_GATE2_REVERSE_CATALOG_CHANGED")
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("curve", "0024_manual_draft_reconstruction")]
    operations = [
        migrations.RunPython(verify_predecessor, verify_empty_predecessor),
        migrations.CreateModel(
            name="ManualGate2ControlV2",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("product_id", models.UUIDField(editable=False)),
                ("initiative_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(editable=False)),
                ("current_record_id", models.UUIDField(editable=False)),
                ("subject_id", models.UUIDField(editable=False)),
                ("state", models.CharField(editable=False, max_length=24)),
                ("approved_record_id", models.UUIDField(editable=False, null=True)),
            ],
            options={
                "db_table": "curve_manual_gate2_control_v2",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "id"), name="curve_mg2c_ws_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "initiative_id"),
                        name="curve_mg2c_init_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("version__gte", 1), ("version__lte", 9007199254740991)
                        ),
                        name="curve_mg2c_ver_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "state__in",
                                [
                                    "PLAN_REVIEW",
                                    "CHANGES_REQUESTED",
                                    "MANUAL_APPROVED",
                                    "RELEASED",
                                ],
                            )
                        ),
                        name="curve_mg2c_state_ck",
                    ),
                ],
                "indexes": [],
            },
        ),
        migrations.CreateModel(
            name="ManualGate2RecordV2",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("product_id", models.UUIDField(editable=False)),
                ("initiative_id", models.UUIDField(db_index=True, editable=False)),
                ("control_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(editable=False)),
                ("initiative_version", models.PositiveBigIntegerField(editable=False)),
                ("predecessor_id", models.UUIDField(editable=False, null=True)),
                ("action", models.CharField(editable=False, max_length=24)),
                ("subject_id", models.UUIDField(editable=False)),
                ("subject_digest", models.CharField(editable=False, max_length=71)),
                ("draft_revision_id", models.UUIDField(editable=False)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("payload", models.JSONField(editable=False)),
                ("request_payload", models.JSONField(editable=False)),
                ("request_digest", models.CharField(editable=False, max_length=71)),
                ("policy_decision_id", models.UUIDField(editable=False)),
                ("command_receipt_id", models.UUIDField(editable=False)),
                ("created_by", models.UUIDField(editable=False)),
                (
                    "recorded_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
            ],
            options={
                "db_table": "curve_manual_gate2_record_v2",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "id"), name="curve_mg2r_ws_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "control_id", "version"),
                        name="curve_mg2r_seq_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "command_receipt_id"),
                        name="curve_mg2r_event_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "policy_decision_id"),
                        name="curve_mg2r_policy_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("version__gte", 1), ("version__lte", 9007199254740991)
                        ),
                        name="curve_mg2r_ver_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("initiative_version__gte", 2),
                            ("initiative_version__lte", 9007199254740991),
                        ),
                        name="curve_mg2r_init_ver_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "action__in",
                                [
                                    "PREPARE",
                                    "APPROVE",
                                    "REQUEST_CHANGES",
                                    "RECONCILE",
                                    "RELEASE",
                                ],
                            )
                        ),
                        name="curve_mg2r_action_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")),
                        name="curve_mg2r_digest_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("subject_digest__regex", "^sha256:[0-9a-f]{64}$")
                        ),
                        name="curve_mg2r_subject_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("request_digest__regex", "^sha256:[0-9a-f]{64}$")
                        ),
                        name="curve_mg2r_request_ck",
                    ),
                ],
                "indexes": [],
            },
        ),
        migrations.CreateModel(
            name="ManualTaskClaimV2",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("installation_id", models.UUIDField(editable=False)),
                ("issue_id", models.UUIDField(editable=False)),
                ("initiative_id", models.UUIDField(db_index=True, editable=False)),
                ("subject_id", models.UUIDField(editable=False)),
                ("generation", models.PositiveBigIntegerField(editable=False)),
                ("state", models.CharField(editable=False, max_length=16)),
                ("current_record_id", models.UUIDField(editable=False)),
                ("current_history_id", models.UUIDField(editable=False)),
            ],
            options={
                "db_table": "curve_manual_task_claim_v2",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "id"), name="curve_mtc2_ws_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "installation_id", "issue_id"),
                        name="curve_mtc2_task_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("generation__gte", 1),
                            ("generation__lte", 9007199254740991),
                        ),
                        name="curve_mtc2_gen_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("state__in", ["ACTIVE", "RELEASED"])),
                        name="curve_mtc2_state_ck",
                    ),
                ],
                "indexes": [],
            },
        ),
        migrations.CreateModel(
            name="ManualTaskClaimHistoryV2",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("claim_id", models.UUIDField(editable=False)),
                ("record_id", models.UUIDField(editable=False)),
                ("initiative_id", models.UUIDField(db_index=True, editable=False)),
                ("generation", models.PositiveBigIntegerField(editable=False)),
                ("state", models.CharField(editable=False, max_length=16)),
                ("payload", models.JSONField(editable=False)),
            ],
            options={
                "db_table": "curve_manual_task_claim_history_v2",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace_id", "id"), name="curve_mtch2_ws_id_uq"
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "claim_id", "record_id"),
                        name="curve_mtch2_event_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("generation__gte", 1),
                            ("generation__lte", 9007199254740991),
                        ),
                        name="curve_mtch2_gen_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("state__in", ["ACTIVE", "RELEASED"])),
                        name="curve_mtch2_state_ck",
                    ),
                ],
                "indexes": [],
            },
        ),
        migrations.RemoveConstraint(
            model_name="policydecision", name="curve_policy_identity_ck"
        ),
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
                    | models.Q(
                        policy_key="CURVE_CORE_POLICY", policy_version__in=[1, 2]
                    )
                    | models.Q(policy_key="CURVE_PRODUCT_POLICY", policy_version=1)
                    | models.Q(policy_key="CURVE_INITIATIVE_POLICY", policy_version=1)
                    | models.Q(
                        policy_key="CURVE_PRD_POLICY",
                        policy_version=1,
                        policy_manifest_digest="sha256:ad38408f0e4450c615025debdf3361965f3a7361ad392aaf9aeb4219b910cb4c",
                    )
                    | models.Q(
                        policy_key="CURVE_MANUAL_PLAN_DRAFT_POLICY_V2",
                        policy_version=2,
                        policy_manifest_digest="sha256:cd960f017b8209b5e4a26a624cfb3549577f946c5a9682c593dec5908d6ab2f0",
                    )
                )
                | models.Q(
                    policy_key="CURVE.LOCAL_MANUAL_GATE2_RECONSTRUCTION_V2",
                    policy_version=2,
                    policy_manifest_digest="sha256:b77e1c16465b9ebdea65ffa37915bee9239a616f667a72f8e6ad978df8833514",
                ),
                name="curve_policy_identity_ck",
            ),
        ),
        migrations.RunSQL(SCHEMA_SQL + GUARD_SQL, REVERSE_SQL),
        migrations.RunPython(install_seal, migrations.RunPython.noop),
        migrations.RunSQL(
            SEAL_SQL,
            "DROP TRIGGER curve_mg2_coverage_immutable ON curve_manual_gate2_v2_coverage;",
        ),
        migrations.RunPython(verify_successor, require_empty_reverse),
    ]
