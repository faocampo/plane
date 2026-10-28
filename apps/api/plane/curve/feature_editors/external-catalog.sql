-- Extend qualification to Curve triggers attached to the upstream membership table.
-- The historical Curve catalog function is preserved byte-for-byte.
CREATE FUNCTION curve_feature_editor_external_catalog() RETURNS jsonb
LANGUAGE sql STABLE AS $catalog$
SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY schema,table_name,name), '[]'::jsonb)
FROM (
    SELECT n.nspname AS schema, c.relname AS table_name, t.tgname AS name,
        t.tgenabled AS enabled, pg_get_triggerdef(t.oid,true) AS definition,
        pn.nspname AS function_schema, p.proname AS function_name,
        pg_get_function_identity_arguments(p.oid) AS function_identity_arguments,
        pg_get_functiondef(p.oid) AS function_definition
    FROM pg_trigger t
    JOIN pg_class c ON c.oid=t.tgrelid
    JOIN pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_proc p ON p.oid=t.tgfoid
    JOIN pg_namespace pn ON pn.oid=p.pronamespace
    WHERE c.relname='workspace_members'
      AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
      AND (t.tgname LIKE 'curve\_%' ESCAPE '\' OR p.proname LIKE 'curve\_%' ESCAPE '\')
) r
$catalog$;
