# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


FORWARD_GUARDS = """
ALTER TABLE curve_prd_artifact ADD CONSTRAINT curve_prd_art_init_fk
 FOREIGN KEY (workspace_id, initiative_id) REFERENCES curve_initiative(workspace_id, id);
ALTER TABLE curve_prd_artifact_version ADD CONSTRAINT curve_prd_ver_art_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_id)
 REFERENCES curve_prd_artifact(workspace_id, initiative_id, id);
ALTER TABLE curve_prd_artifact ADD CONSTRAINT curve_prd_art_current_fk
 FOREIGN KEY (workspace_id, initiative_id, id, current_version_id)
 REFERENCES curve_prd_artifact_version(workspace_id, initiative_id, artifact_id, id)
 DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_prd_artifact_version ADD CONSTRAINT curve_prd_ver_parent_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_id, parent_version_id)
 REFERENCES curve_prd_artifact_version(workspace_id, initiative_id, artifact_id, id)
 DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_prd_evidence_snapshot ADD CONSTRAINT curve_prd_snapshot_version_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_version_id)
 REFERENCES curve_prd_artifact_version(workspace_id, initiative_id, id)
 DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_prd_artifact_version ADD CONSTRAINT curve_prd_ver_snapshot_fk
 FOREIGN KEY (workspace_id, initiative_id, id, evidence_snapshot_id)
 REFERENCES curve_prd_evidence_snapshot(workspace_id, initiative_id, artifact_version_id, id)
 DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE curve_prd_evidence_item_version ADD CONSTRAINT curve_prd_evidence_provider_fk
 FOREIGN KEY (workspace_id, provider_connection_id) REFERENCES curve_provider_connection(workspace_id, id);

CREATE FUNCTION curve_prd_closed_keys(value jsonb, keys text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT COALESCE(jsonb_typeof(value) = 'object' AND value ?& keys AND value - keys = '{}'::jsonb, false);
$$;

CREATE FUNCTION curve_prd_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'PRD metadata is immutable; governed retention is required' USING ERRCODE = '23514';
END;
$$;
CREATE FUNCTION curve_prd_object_ref_valid(value jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT COALESCE(curve_prd_closed_keys(value, ARRAY['object_id','digest','size_bytes','media_type'])
  AND jsonb_typeof(value->'object_id') = 'string' AND (value->>'object_id')::uuid IS NOT NULL
  AND value->>'digest' ~ '^sha256:[0-9a-f]{64}$' AND jsonb_typeof(value->'size_bytes') = 'number'
  AND (value->>'size_bytes')::numeric BETWEEN 1 AND 9007199254740991
  AND trunc((value->>'size_bytes')::numeric) = (value->>'size_bytes')::numeric
  AND jsonb_typeof(value->'media_type') = 'string' AND length(value->>'media_type') BETWEEN 1 AND 255, false);
$$;
CREATE TRIGGER curve_prd_version_immutable BEFORE UPDATE OR DELETE ON curve_prd_artifact_version
 FOR EACH ROW EXECUTE FUNCTION curve_prd_immutable();
CREATE TRIGGER curve_prd_snapshot_immutable BEFORE UPDATE OR DELETE ON curve_prd_evidence_snapshot
 FOR EACH ROW EXECUTE FUNCTION curve_prd_immutable();
CREATE TRIGGER curve_prd_evidence_immutable BEFORE UPDATE OR DELETE ON curve_prd_evidence_item_version
 FOR EACH ROW EXECUTE FUNCTION curve_prd_immutable();

CREATE FUNCTION curve_prd_artifact_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE successor curve_prd_artifact_version;
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'PRD artifact requires governed retention' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'INSERT' THEN
  IF NEW.current_version_id IS NOT NULL THEN
   RAISE EXCEPTION 'PRD artifact must start without a version' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
 END IF;
 IF ROW(NEW.id, NEW.workspace_id, NEW.initiative_id, NEW.created_at) IS DISTINCT FROM
    ROW(OLD.id, OLD.workspace_id, OLD.initiative_id, OLD.created_at) THEN
  RAISE EXCEPTION 'PRD artifact identity is immutable' USING ERRCODE = '23514';
 END IF;
 IF NEW.current_version_id IS DISTINCT FROM OLD.current_version_id THEN
  SELECT * INTO successor FROM curve_prd_artifact_version WHERE id = NEW.current_version_id;
  IF NOT FOUND OR successor.artifact_id <> NEW.id OR
     successor.parent_version_id IS DISTINCT FROM OLD.current_version_id THEN
   RAISE EXCEPTION 'PRD current version must advance to its successor' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_prd_artifact_guard BEFORE INSERT OR UPDATE OR DELETE ON curve_prd_artifact
 FOR EACH ROW EXECUTE FUNCTION curve_prd_artifact_guard();

CREATE FUNCTION curve_prd_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_record curve_prd_artifact; parent_record curve_prd_artifact_version;
BEGIN
 SELECT * INTO owner_record FROM curve_prd_artifact WHERE id = NEW.artifact_id FOR UPDATE;
 IF NOT FOUND OR owner_record.workspace_id <> NEW.workspace_id OR owner_record.initiative_id <> NEW.initiative_id
    OR NEW.created_at < owner_record.created_at
    OR NEW.parent_version_id IS DISTINCT FROM owner_record.current_version_id THEN
  RAISE EXCEPTION 'PRD version scope, chronology or predecessor conflict' USING ERRCODE = '23514';
 END IF;
 IF NEW.parent_version_id IS NULL THEN
  IF NEW.version_number <> 1 THEN
   RAISE EXCEPTION 'PRD initial version must be one' USING ERRCODE = '23514';
  END IF;
 ELSE
  SELECT * INTO parent_record FROM curve_prd_artifact_version WHERE id = NEW.parent_version_id;
  IF NEW.version_number <> parent_record.version_number + 1 OR NEW.created_at < parent_record.created_at THEN
   RAISE EXCEPTION 'PRD successor number or chronology conflict' USING ERRCODE = '23514';
  END IF;
 END IF;
 IF NOT curve_prd_closed_keys(NEW.created_by, ARRAY['actor_type','actor_id']) OR
    NEW.created_by->>'actor_type' IS DISTINCT FROM 'HUMAN' OR
    jsonb_typeof(NEW.created_by->'actor_id') IS DISTINCT FROM 'string' OR
    length(NEW.created_by->>'actor_id') NOT BETWEEN 1 AND 255 THEN
  RAISE EXCEPTION 'PRD version requires bounded human attribution' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_prd_version_guard BEFORE INSERT ON curve_prd_artifact_version
 FOR EACH ROW EXECUTE FUNCTION curve_prd_version_guard();

CREATE FUNCTION curve_prd_version_commit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_record curve_prd_artifact_version; snapshot_record curve_prd_evidence_snapshot;
BEGIN
 SELECT v.* INTO current_record FROM curve_prd_artifact a JOIN curve_prd_artifact_version v
  ON v.id = a.current_version_id WHERE a.id = NEW.artifact_id;
 SELECT * INTO snapshot_record FROM curve_prd_evidence_snapshot WHERE id = NEW.evidence_snapshot_id;
 IF current_record.id IS NULL OR current_record.version_number < NEW.version_number OR
    snapshot_record.id IS NULL OR snapshot_record.created_at > NEW.created_at THEN
  RAISE EXCEPTION 'PRD version, current pointer and snapshot must commit together' USING ERRCODE = '23514';
 END IF;
 RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER curve_prd_version_commit_guard AFTER INSERT ON curve_prd_artifact_version
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION curve_prd_version_commit_guard();

CREATE FUNCTION curve_prd_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER curve_prd_evidence_guard BEFORE INSERT ON curve_prd_evidence_item_version
 FOR EACH ROW EXECUTE FUNCTION curve_prd_evidence_guard();

CREATE FUNCTION curve_prd_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE entry jsonb; ordinal integer := 0; evidence curve_prd_evidence_item_version; seen text[] := ARRAY[]::text[];
identity_key text;
BEGIN
 IF jsonb_typeof(NEW.items) IS DISTINCT FROM 'array' OR jsonb_array_length(NEW.items) > 10000 THEN
  RAISE EXCEPTION 'PRD snapshot items must be a bounded array' USING ERRCODE = '23514';
 END IF;
 FOR entry IN SELECT * FROM jsonb_array_elements(NEW.items) LOOP
  IF NOT curve_prd_closed_keys(entry, ARRAY['ordinal','evidence_item_id','evidence_item_version','content_digest',
   'source_version','access_envelope_id','access_envelope_digest','material','claim_refs','selected_excerpt_ref']) THEN
   RAISE EXCEPTION 'PRD snapshot entry shape is invalid' USING ERRCODE = '23514';
  END IF;
  identity_key := (entry->>'evidence_item_id') || ':' || (entry->>'evidence_item_version');
  SELECT * INTO evidence FROM curve_prd_evidence_item_version
   WHERE workspace_id = NEW.workspace_id AND evidence_id = (entry->>'evidence_item_id')::uuid
   AND version = (entry->>'evidence_item_version')::bigint FOR KEY SHARE;
  IF NOT FOUND OR (entry->>'ordinal')::integer IS DISTINCT FROM ordinal OR identity_key = ANY(seen) OR
   entry->>'content_digest' IS DISTINCT FROM evidence.record->>'content_digest' OR
   entry->>'source_version' IS DISTINCT FROM evidence.record->>'source_version' OR
   entry->>'access_envelope_id' IS DISTINCT FROM evidence.record#>>'{access_envelope,id}' OR
   entry->>'access_envelope_digest' IS DISTINCT FROM evidence.envelope_digest OR
   (evidence.record->>'created_at')::timestamptz > NEW.created_at OR
   jsonb_typeof(entry->'material') IS DISTINCT FROM 'boolean' OR
   jsonb_typeof(entry->'claim_refs') IS DISTINCT FROM 'array' THEN
   RAISE EXCEPTION 'PRD snapshot exact evidence membership conflict' USING ERRCODE = '23514';
  END IF;
  IF (entry->>'material')::boolean AND jsonb_array_length(entry->'claim_refs') = 0 THEN
   RAISE EXCEPTION 'PRD material evidence requires a claim reference' USING ERRCODE = '23514';
  END IF;
  IF entry->'selected_excerpt_ref' <> 'null'::jsonb
   AND NOT curve_prd_object_ref_valid(entry->'selected_excerpt_ref') THEN
   RAISE EXCEPTION 'PRD excerpt must be an object reference' USING ERRCODE = '23514';
  END IF;
  seen := array_append(seen, identity_key);
  ordinal := ordinal + 1;
 END LOOP;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_prd_snapshot_guard BEFORE INSERT ON curve_prd_evidence_snapshot
 FOR EACH ROW EXECUTE FUNCTION curve_prd_snapshot_guard();
"""

REVERSE_GUARDS = """
LOCK TABLE curve_prd_artifact, curve_prd_artifact_version, curve_prd_evidence_snapshot,
 curve_prd_evidence_item_version IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM curve_prd_artifact) OR EXISTS (SELECT 1 FROM curve_prd_artifact_version) OR
 EXISTS (SELECT 1 FROM curve_prd_evidence_snapshot) OR EXISTS (SELECT 1 FROM curve_prd_evidence_item_version) THEN
  RAISE EXCEPTION 'Retained PRD metadata requires a preservation migration';
 END IF;
END $$;
DROP TRIGGER curve_prd_snapshot_guard ON curve_prd_evidence_snapshot;
DROP TRIGGER curve_prd_evidence_guard ON curve_prd_evidence_item_version;
DROP TRIGGER curve_prd_version_commit_guard ON curve_prd_artifact_version;
DROP TRIGGER curve_prd_version_guard ON curve_prd_artifact_version;
DROP TRIGGER curve_prd_artifact_guard ON curve_prd_artifact;
DROP TRIGGER curve_prd_version_immutable ON curve_prd_artifact_version;
DROP TRIGGER curve_prd_snapshot_immutable ON curve_prd_evidence_snapshot;
DROP TRIGGER curve_prd_evidence_immutable ON curve_prd_evidence_item_version;
DROP FUNCTION curve_prd_snapshot_guard();
DROP FUNCTION curve_prd_evidence_guard();
DROP FUNCTION curve_prd_version_commit_guard();
DROP FUNCTION curve_prd_version_guard();
DROP FUNCTION curve_prd_artifact_guard();
DROP FUNCTION curve_prd_immutable();
DROP FUNCTION curve_prd_object_ref_valid(jsonb);
DROP FUNCTION curve_prd_closed_keys(jsonb, text[]);
ALTER TABLE curve_prd_artifact DROP CONSTRAINT curve_prd_art_init_fk;
ALTER TABLE curve_prd_artifact DROP CONSTRAINT curve_prd_art_current_fk;
ALTER TABLE curve_prd_artifact_version DROP CONSTRAINT curve_prd_ver_art_fk;
ALTER TABLE curve_prd_artifact_version DROP CONSTRAINT curve_prd_ver_parent_fk;
ALTER TABLE curve_prd_artifact_version DROP CONSTRAINT curve_prd_ver_snapshot_fk;
ALTER TABLE curve_prd_evidence_snapshot DROP CONSTRAINT curve_prd_snapshot_version_fk;
ALTER TABLE curve_prd_evidence_item_version DROP CONSTRAINT curve_prd_evidence_provider_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("curve", "0009_external_document_binding"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrdArtifact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
            ],
            options={
                "db_table": "curve_prd_artifact",
            },
        ),
        migrations.CreateModel(
            name="PrdArtifactVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("version_number", models.PositiveBigIntegerField(editable=False)),
                ("body_object_id", models.UUIDField(editable=False)),
                ("body_digest", models.CharField(editable=False, max_length=71)),
                ("body_size_bytes", models.PositiveBigIntegerField(editable=False)),
                ("body_schema_id", models.CharField(editable=False, max_length=512)),
                ("body_schema_version", models.PositiveBigIntegerField(editable=False)),
                ("access_envelope_id", models.UUIDField(editable=False)),
                ("retention_policy_version_id", models.UUIDField(editable=False)),
                ("created_by", models.JSONField(editable=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "artifact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="curve.prdartifact"
                    ),
                ),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "parent_version",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="curve.prdartifactversion",
                    ),
                ),
            ],
            options={
                "db_table": "curve_prd_artifact_version",
            },
        ),
        migrations.AddField(
            model_name="prdartifact",
            name="current_version",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="current_for_artifact",
                to="curve.prdartifactversion",
            ),
        ),
        migrations.CreateModel(
            name="PrdEvidenceItemVersion",
            fields=[
                ("envelope_digest", models.CharField(max_length=71, editable=False)),
                ("row_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("evidence_id", models.UUIDField(editable=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("version", models.PositiveBigIntegerField(editable=False)),
                ("record", models.JSONField(editable=False)),
                (
                    "provider_connection",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.providerconnection"),
                ),
            ],
            options={
                "db_table": "curve_prd_evidence_item_version",
            },
        ),
        migrations.CreateModel(
            name="PrdEvidenceSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("digest", models.CharField(editable=False, max_length=71)),
                ("items", models.JSONField(default=list, editable=False)),
                (
                    "artifact_version",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="snapshots",
                        to="curve.prdartifactversion",
                    ),
                ),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
            ],
            options={
                "db_table": "curve_prd_evidence_snapshot",
            },
        ),
        migrations.AddField(
            model_name="prdartifactversion",
            name="evidence_snapshot",
            field=models.ForeignKey(
                db_constraint=False, on_delete=django.db.models.deletion.PROTECT, to="curve.prdevidencesnapshot"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifact",
            constraint=models.UniqueConstraint(fields=("workspace_id", "initiative"), name="curve_prd_art_ws_init_uq"),
        ),
        migrations.AddConstraint(
            model_name="prdartifact",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "id"), name="curve_prd_art_scope_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdevidenceitemversion",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "evidence_id", "version"), name="curve_prd_evidence_ver_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdevidenceitemversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1), ("version__lte", 9007199254740991)),
                name="curve_prd_evidence_ver_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdevidencesnapshot",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "artifact_version"), name="curve_prd_snapshot_ver_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdevidencesnapshot",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "artifact_version", "id"), name="curve_prd_snapshot_scope_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdevidencesnapshot",
            constraint=models.CheckConstraint(
                condition=models.Q(("digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_prd_snapshot_digest_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "artifact", "version_number"), name="curve_prd_art_ver_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "artifact", "id"), name="curve_prd_ver_art_scope_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "id"), name="curve_prd_ver_scope_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("version_number__gte", 1), ("version_number__lte", 9007199254740991)),
                name="curve_prd_ver_number_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("body_size_bytes__gte", 1), ("body_size_bytes__lte", 9007199254740991)),
                name="curve_prd_ver_size_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("body_schema_version__gte", 1), ("body_schema_version__lte", 9007199254740991)),
                name="curve_prd_ver_schema_num_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("body_digest__regex", "^sha256:[0-9a-f]{64}$")), name="curve_prd_ver_digest_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="prdartifactversion",
            constraint=models.CheckConstraint(
                condition=models.Q(("body_schema_id", ""), _negated=True), name="curve_prd_ver_schema_id_ck"
            ),
        ),
        migrations.RunSQL(FORWARD_GUARDS, REVERSE_GUARDS),
    ]
