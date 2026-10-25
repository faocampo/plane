ALTER TABLE curve_roadmap ADD CONSTRAINT curve_rmap_product_fk
 FOREIGN KEY (workspace_id, product_id) REFERENCES curve_product (workspace_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_milestone ADD CONSTRAINT curve_mstone_product_fk
 FOREIGN KEY (workspace_id, product_id) REFERENCES curve_product (workspace_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_feature ADD CONSTRAINT curve_feature_product_fk
 FOREIGN KEY (workspace_id, product_id) REFERENCES curve_product (workspace_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_roadmap_item ADD CONSTRAINT curve_ritem_product_fk
 FOREIGN KEY (workspace_id, product_id) REFERENCES curve_product (workspace_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_milestone ADD CONSTRAINT curve_mstone_roadmap_fk
 FOREIGN KEY (workspace_id, product_id, roadmap_id) REFERENCES curve_roadmap (workspace_id, product_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_roadmap_item ADD CONSTRAINT curve_ritem_milestone_fk
 FOREIGN KEY (workspace_id, product_id, roadmap_id, milestone_id) REFERENCES curve_milestone (workspace_id, product_id, roadmap_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_roadmap_item ADD CONSTRAINT curve_ritem_feature_fk
 FOREIGN KEY (workspace_id, product_id, feature_id) REFERENCES curve_feature (workspace_id, product_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_roadmap_item ADD CONSTRAINT curve_ritem_initiative_fk
 FOREIGN KEY (workspace_id, product_id, defining_initiative_id, id) REFERENCES curve_initiative (workspace_id, product_id, id, roadmap_item_id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_initiative ADD CONSTRAINT curve_init_roadmap_item_fk
 FOREIGN KEY (workspace_id, product_id, id, roadmap_item_id) REFERENCES curve_roadmap_item (workspace_id, product_id, defining_initiative_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_roadmap_item_history ADD CONSTRAINT curve_rihist_item_fk
 FOREIGN KEY (workspace_id, product_id, roadmap_item_id) REFERENCES curve_roadmap_item (workspace_id, product_id, id)
 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
CREATE TRIGGER curve_roadmap_retained BEFORE DELETE OR TRUNCATE ON curve_roadmap
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_milestone_retained BEFORE DELETE OR TRUNCATE ON curve_milestone
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_feature_retained BEFORE DELETE OR TRUNCATE ON curve_feature
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_roadmap_item_retained BEFORE DELETE OR TRUNCATE ON curve_roadmap_item
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
CREATE TRIGGER curve_roadmap_item_history_retained BEFORE UPDATE OR DELETE OR TRUNCATE ON curve_roadmap_item_history
 FOR EACH STATEMENT EXECUTE FUNCTION curve_mpd2_immutable();
-- PostgreSQL assigns an OID-based name to a deferred UNIQUE recheck trigger.
-- Give this new constraint's trigger a stable name for exact catalog qualification.
DO $$
DECLARE trigger_name text;
BEGIN
 SELECT t.tgname INTO STRICT trigger_name FROM pg_trigger t
 JOIN pg_constraint c ON c.oid=t.tgconstraint
 WHERE c.conrelid='curve_milestone'::regclass AND c.conname='curve_mstone_position_uq'
 AND t.tgisinternal AND t.tgfoid='unique_key_recheck()'::regprocedure;
 EXECUTE format('ALTER TRIGGER %I ON curve_milestone RENAME TO curve_mstone_position_recheck', trigger_name);
END $$;
