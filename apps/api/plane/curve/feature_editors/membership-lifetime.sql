-- Transactional membership lifetime tracking installed by the additive migration.
-- Command authorization and runtime activation retain their separate gates.
-- Keep lifetimes after hard deletion so reusing a membership UUID cannot revive grants.
CREATE TABLE curve_feature_membership_lifetime (
    membership_id uuid PRIMARY KEY,
    generation bigint NOT NULL CHECK (generation >= 0)
);
INSERT INTO curve_feature_membership_lifetime (membership_id, generation)
SELECT id, 0 FROM workspace_members;

CREATE FUNCTION curve_feature_membership_lifetime_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') OR pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'FEATURE_MEMBERSHIP_LIFETIME_DIRECT_WRITE';
    END IF;
    IF TG_OP = 'UPDATE' AND
       (NEW.membership_id IS DISTINCT FROM OLD.membership_id OR NEW.generation <> OLD.generation + 1) THEN
        RAISE EXCEPTION 'FEATURE_MEMBERSHIP_LIFETIME_INVALID_ADVANCE';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER curve_feature_membership_lifetime_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON curve_feature_membership_lifetime
FOR EACH ROW EXECUTE FUNCTION curve_feature_membership_lifetime_guard();
CREATE TRIGGER curve_feature_membership_lifetime_truncate_guard
BEFORE TRUNCATE ON curve_feature_membership_lifetime
FOR EACH STATEMENT EXECUTE FUNCTION curve_feature_membership_lifetime_guard();

CREATE FUNCTION curve_feature_membership_lifetime_track() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        UPDATE curve_feature_membership_lifetime lifetime
        SET generation = lifetime.generation + 1
        FROM workspace_members membership WHERE membership.id = lifetime.membership_id;
        RETURN NULL;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'FEATURE_MEMBERSHIP_ID_IMMUTABLE';
    END IF;
    IF TG_OP = 'INSERT' THEN
        INSERT INTO curve_feature_membership_lifetime VALUES (NEW.id, 0)
        ON CONFLICT (membership_id) DO UPDATE
        SET generation = curve_feature_membership_lifetime.generation + 1;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' OR
       (OLD.is_active AND NOT NEW.is_active) OR
       (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL) OR
       (OLD.workspace_id IS DISTINCT FROM NEW.workspace_id) OR
       (OLD.member_id IS DISTINCT FROM NEW.member_id) THEN
        INSERT INTO curve_feature_membership_lifetime VALUES (OLD.id, 1)
        ON CONFLICT (membership_id) DO UPDATE
        SET generation = curve_feature_membership_lifetime.generation + 1;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER curve_feature_membership_lifetime_track
BEFORE INSERT OR UPDATE OR DELETE ON workspace_members
FOR EACH ROW EXECUTE FUNCTION curve_feature_membership_lifetime_track();
CREATE TRIGGER curve_feature_membership_lifetime_track_truncate
BEFORE TRUNCATE ON workspace_members
FOR EACH STATEMENT EXECUTE FUNCTION curve_feature_membership_lifetime_track();
