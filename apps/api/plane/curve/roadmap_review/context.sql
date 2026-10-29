CREATE FUNCTION curve_local_roadmap_review_context(p jsonb, workspace uuid, initiative uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS (
  SELECT 1 FROM curve_initiative i
  JOIN curve_product prod ON prod.workspace_id=i.workspace_id AND prod.id=i.product_id
  JOIN curve_roadmap_item item ON item.workspace_id=i.workspace_id
   AND item.product_id=i.product_id AND item.id=i.roadmap_item_id
   AND item.defining_initiative_id=i.id
  JOIN curve_roadmap roadmap ON roadmap.workspace_id=item.workspace_id
   AND roadmap.product_id=item.product_id AND roadmap.id=item.roadmap_id
  JOIN curve_feature feature ON feature.workspace_id=item.workspace_id
   AND feature.product_id=item.product_id AND feature.id=item.feature_id
  JOIN curve_milestone milestone ON milestone.workspace_id=item.workspace_id
   AND milestone.product_id=item.product_id AND milestone.roadmap_id=item.roadmap_id
   AND milestone.id=item.milestone_id
  WHERE i.workspace_id=workspace AND i.id=initiative
   AND i.schema_version='1.2' AND i.mode='ROADMAP'
   AND prod.schema_version='1.0' AND prod.state='ACTIVE'
   AND item.schema_version='1.0' AND item.tombstoned_at IS NULL
   AND roadmap.schema_version='1.0' AND roadmap.tombstoned_at IS NULL
   AND feature.schema_version='1.0' AND feature.tombstoned_at IS NULL
   AND milestone.schema_version='1.0' AND milestone.tombstoned_at IS NULL
   AND i.current_prd_checkpoint_id IS NULL AND i.controlling_prd_decision_id IS NULL
   AND i.pending_scope_reopening_id IS NULL
   AND prod.id::text=p->>'product_id' AND to_jsonb(prod.version)=p->'product_version'
   AND i.business_intent IS NOT DISTINCT FROM p->>'business_intent'
   AND item.id::text=p->>'roadmap_item_id' AND item.scope_body=p->'roadmap_item_scope'
   AND NOT EXISTS(SELECT 1 FROM curve_scope_proposal h
    WHERE h.workspace_id=workspace AND h.initiative_id=initiative)
   AND NOT EXISTS(SELECT 1 FROM curve_scope_proposal_revision h
    WHERE h.workspace_id=workspace AND h.initiative_id=initiative)
   AND NOT EXISTS(SELECT 1 FROM curve_local_prd_submission h
    WHERE h.workspace_id=workspace AND h.initiative_id=initiative
     AND h.payload->>'schema_version' IS DISTINCT FROM 'curve.local-prd-submission/v3-roadmap-candidate')
 );
$$;
