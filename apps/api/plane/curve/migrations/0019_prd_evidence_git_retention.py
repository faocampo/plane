# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import migrations


# Frozen original guard: reversal restores its exact behavior without importing
# application code or changing historical JSON records and envelope digests.
LEGACY_GUARD = """
CREATE OR REPLACE FUNCTION curve_prd_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb := NEW.record;
BEGIN
 IF NOT curve_prd_closed_keys(item, ARRAY['schema_version','id','workspace_id','created_at','version',
  'source','source_version','retrieved_at','effective_principal','content','content_digest','classification',
  'access_envelope','trust_flags','redaction_state','retention_policy_version_id']) OR
  item->>'schema_version' IS DISTINCT FROM '1.0-candidate' OR
  item->>'id' IS DISTINCT FROM NEW.evidence_id::text OR
  item->>'workspace_id' IS DISTINCT FROM NEW.workspace_id::text OR
  (item->>'version')::bigint IS DISTINCT FROM NEW.version OR
  item#>>'{source,provider_connection_id}' IS DISTINCT FROM NEW.provider_connection_id::text OR
  item#>>'{access_envelope,workspace_id}' IS DISTINCT FROM NEW.workspace_id::text OR
  NEW.envelope_digest !~ '^sha256:[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'PRD evidence metadata identity conflict' USING ERRCODE = '23514';
 END IF;
 IF NOT curve_prd_closed_keys(item->'source',
  ARRAY['provider_connection_id','resource_id','resource_type','source_ref'])
  OR NOT curve_prd_closed_keys((item->'source'->'source_ref') - 'resource_version',
   ARRAY['resource_type','resource_id'])
  OR NOT curve_prd_closed_keys((item->'access_envelope') - ARRAY['expires_at','revoked_at','transformation_refs'],
    ARRAY['schema_version','id','workspace_id','source_refs','effective_principal','source_authorization_digest',
     'classification','allowed_audiences','allowed_destinations','retention_policy_ref','redaction_state',
     'legal_hold','created_at'])
  OR (item->'content' <> 'null'::jsonb AND NOT curve_prd_object_ref_valid(item->'content'))
  OR item->>'content_digest' !~ '^sha256:[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'PRD evidence stores closed metadata and object references only' USING ERRCODE = '23514';
 END IF;
 IF (item->>'retrieved_at')::timestamptz > (item->>'created_at')::timestamptz OR
    (item#>>'{access_envelope,created_at}')::timestamptz > (item->>'created_at')::timestamptz THEN
  RAISE EXCEPTION 'PRD evidence chronology conflict' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END;
$$;
"""

V2_CHECKS = """
 IF item->>'schema_version' = '2.0-candidate' THEN
  IF item#>>'{access_envelope,schema_version}' IS DISTINCT FROM '2.0'
   OR jsonb_typeof(item->'retention_policy_version_id') IS DISTINCT FROM 'string'
   OR length(item->>'retention_policy_version_id') IS DISTINCT FROM 40
   OR NOT COALESCE(item->>'retention_policy_version_id' ~ '^[0-9a-f]{40}$', false)
   OR NOT curve_prd_closed_keys(item#>'{access_envelope,retention_policy_ref}', ARRAY['resource_type','resource_id'])
   OR item#>>'{access_envelope,retention_policy_ref,resource_type}' IS DISTINCT FROM 'RETENTION_POLICY_VERSION'
   OR item#>'{access_envelope,retention_policy_ref,resource_id}' IS DISTINCT FROM item->'retention_policy_version_id'
   OR item#>'{access_envelope,effective_principal}' IS DISTINCT FROM item->'effective_principal'
   OR item#>>'{effective_principal,actor_type}' IS DISTINCT FROM 'HUMAN'
   OR item#>'{access_envelope,classification}' IS DISTINCT FROM item->'classification'
   OR item#>'{access_envelope,redaction_state}' IS DISTINCT FROM item->'redaction_state'
   OR NOT COALESCE(item#>'{access_envelope,source_refs}' @> jsonb_build_array(item#>'{source,source_ref}'), false) THEN
   RAISE EXCEPTION 'PRD evidence Git retention envelope conflict' USING ERRCODE = '23514';
  END IF;
 END IF;
"""

FORWARD_GUARD = LEGACY_GUARD.replace(
    "item->>'schema_version' IS DISTINCT FROM '1.0-candidate'",
    "NOT COALESCE(item->>'schema_version' IN ('1.0-candidate', '2.0-candidate'), false)",
).replace(" RETURN NEW;", V2_CHECKS + " RETURN NEW;")

REVERSE_GUARD = (
    """
LOCK TABLE curve_prd_evidence_item_version IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM curve_prd_evidence_item_version
           WHERE record->>'schema_version' IS DISTINCT FROM '1.0-candidate') THEN
  RAISE EXCEPTION 'Retained Git evidence records require a preservation migration';
 END IF;
END $$;
"""
    + LEGACY_GUARD
)


class Migration(migrations.Migration):
    dependencies = [("curve", "0018_prd_rationale_git_retention")]
    operations = [migrations.RunSQL(FORWARD_GUARD, REVERSE_GUARD)]
