-- Product-scoped Feature editor storage installed by the additive migration.
-- Application commands must supply current owner/admin authorization and receipts.
CREATE TABLE curve_feature_editor_grant (
    id uuid PRIMARY KEY,
    version bigint NOT NULL DEFAULT 1,
    workspace_id uuid NOT NULL,
    product_id uuid NOT NULL,
    member_id uuid NOT NULL,
    membership_id uuid NOT NULL REFERENCES curve_feature_membership_lifetime(membership_id),
    membership_generation bigint NOT NULL CHECK (membership_generation >= 0),
    granted_by uuid NOT NULL,
    granted_at timestamptz NOT NULL,
    revoked_by uuid,
    revoked_at timestamptz,
    CONSTRAINT curve_feature_editor_product_fk FOREIGN KEY (workspace_id, product_id)
        REFERENCES curve_product(workspace_id, id),
    CONSTRAINT curve_feature_editor_version_ck CHECK
        ((revoked_at IS NULL AND version=1) OR (revoked_at IS NOT NULL AND version=2)),
    CONSTRAINT curve_feature_editor_revocation_pair_ck CHECK
        ((revoked_by IS NULL AND revoked_at IS NULL) OR (revoked_by IS NOT NULL AND revoked_at IS NOT NULL))
);
CREATE UNIQUE INDEX curve_feature_editor_active_uq ON curve_feature_editor_grant
    (workspace_id, product_id, member_id, membership_id, membership_generation)
    WHERE revoked_at IS NULL;

CREATE FUNCTION curve_feature_editor_grant_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_member workspace_members%ROWTYPE;
    current_generation bigint;
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'FEATURE_EDITOR_GRANT_HISTORY_RETAINED';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - 'revoked_by' - 'revoked_at' - 'version') IS DISTINCT FROM
           (to_jsonb(OLD) - 'revoked_by' - 'revoked_at' - 'version') OR
           OLD.version <> 1 OR NEW.version <> 2 OR
           OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL THEN
            RAISE EXCEPTION 'FEATURE_EDITOR_GRANT_IMMUTABLE';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.version <> 1 OR NEW.revoked_at IS NOT NULL OR NEW.revoked_by IS NOT NULL THEN
        RAISE EXCEPTION 'FEATURE_EDITOR_GRANT_MUST_START_ACTIVE';
    END IF;
    SELECT * INTO current_member FROM workspace_members WHERE id=NEW.membership_id FOR UPDATE;
    IF NOT FOUND OR NOT current_member.is_active OR current_member.deleted_at IS NOT NULL OR
       current_member.workspace_id IS DISTINCT FROM NEW.workspace_id OR
       current_member.member_id IS DISTINCT FROM NEW.member_id THEN
        RAISE EXCEPTION 'FEATURE_EDITOR_GRANT_MEMBERSHIP_UNAVAILABLE';
    END IF;
    SELECT generation INTO current_generation FROM curve_feature_membership_lifetime
        WHERE membership_id=NEW.membership_id FOR UPDATE;
    IF NOT FOUND OR current_generation IS DISTINCT FROM NEW.membership_generation THEN
        RAISE EXCEPTION 'FEATURE_EDITOR_GRANT_MEMBERSHIP_STALE';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER curve_feature_editor_grant_guard
BEFORE INSERT OR UPDATE OR DELETE ON curve_feature_editor_grant
FOR EACH ROW EXECUTE FUNCTION curve_feature_editor_grant_guard();
CREATE TRIGGER curve_feature_editor_grant_truncate_guard
BEFORE TRUNCATE ON curve_feature_editor_grant
FOR EACH STATEMENT EXECUTE FUNCTION curve_feature_editor_grant_guard();
