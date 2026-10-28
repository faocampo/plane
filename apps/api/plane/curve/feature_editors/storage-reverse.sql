-- Execute in the same atomic migration transaction. Lock the membership table
-- first, matching command lock order and blocking new lifetime/grant writes.
LOCK TABLE workspace_members IN ACCESS EXCLUSIVE MODE;
LOCK TABLE curve_feature_membership_lifetime IN ACCESS EXCLUSIVE MODE;
LOCK TABLE curve_feature_editor_grant IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM curve_feature_editor_grant) THEN
        RAISE EXCEPTION 'FEATURE_EDITOR_RETAINED_GRANTS_PREVENT_REVERSE';
    END IF;
END;
$$;
DROP TABLE curve_feature_editor_grant;
DROP FUNCTION curve_feature_editor_grant_guard();
DROP TRIGGER curve_feature_membership_lifetime_track ON workspace_members;
DROP TRIGGER curve_feature_membership_lifetime_track_truncate ON workspace_members;
DROP TABLE curve_feature_membership_lifetime;
DROP FUNCTION curve_feature_membership_lifetime_track();
DROP FUNCTION curve_feature_membership_lifetime_guard();
DROP FUNCTION curve_feature_editor_external_catalog();
