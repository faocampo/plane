# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


FORWARD_GUARDS = """
ALTER TABLE curve_document_checkpoint ADD CONSTRAINT curve_cp_initiative_fk
 FOREIGN KEY (workspace_id, initiative_id) REFERENCES curve_initiative(workspace_id, id);
ALTER TABLE curve_document_checkpoint ADD CONSTRAINT curve_cp_binding_fk
 FOREIGN KEY (workspace_id, external_document_binding_id) REFERENCES curve_external_document_binding(workspace_id, id);
ALTER TABLE curve_document_checkpoint ADD CONSTRAINT curve_cp_version_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_version_id)
 REFERENCES curve_prd_artifact_version(workspace_id, initiative_id, id);
ALTER TABLE curve_document_checkpoint ADD CONSTRAINT curve_cp_snapshot_fk
 FOREIGN KEY (workspace_id, initiative_id, artifact_version_id, evidence_snapshot_id)
 REFERENCES curve_prd_evidence_snapshot(workspace_id, initiative_id, artifact_version_id, id);
ALTER TABLE curve_document_checkpoint ADD CONSTRAINT curve_cp_predecessor_fk
 FOREIGN KEY (workspace_id, initiative_id, external_document_binding_id, predecessor_id)
 REFERENCES curve_document_checkpoint(workspace_id, initiative_id, external_document_binding_id, id);
ALTER TABLE curve_document_checkpoint ADD CONSTRAINT curve_cp_provider_fk
 FOREIGN KEY (workspace_id, provider_connection_id) REFERENCES curve_provider_connection(workspace_id, id);

CREATE TRIGGER curve_checkpoint_immutable BEFORE UPDATE OR DELETE ON curve_document_checkpoint
 FOR EACH ROW EXECUTE FUNCTION curve_prd_immutable();

CREATE FUNCTION curve_checkpoint_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE binding_record curve_external_document_binding; version_record curve_prd_artifact_version;
 snapshot_record curve_prd_evidence_snapshot; artifact_record curve_prd_artifact;
 previous_record curve_document_checkpoint;
BEGIN
 SELECT * INTO binding_record FROM curve_external_document_binding
  WHERE workspace_id = NEW.workspace_id AND id = NEW.external_document_binding_id FOR UPDATE;
 IF NOT FOUND OR binding_record.initiative_id <> NEW.initiative_id OR
    binding_record.provider_connection_id <> NEW.provider_connection_id OR
    binding_record.provider_file_id <> NEW.provider_file_id THEN
  RAISE EXCEPTION 'CHECKPOINT_BINDING_MISMATCH' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO version_record FROM curve_prd_artifact_version
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id AND id = NEW.artifact_version_id;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'CHECKPOINT_ARTIFACT_MISMATCH' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO artifact_record FROM curve_prd_artifact WHERE id = version_record.artifact_id FOR UPDATE;
 IF NOT FOUND OR artifact_record.current_version_id IS DISTINCT FROM NEW.artifact_version_id THEN
  RAISE EXCEPTION 'CHECKPOINT_ARTIFACT_NOT_CURRENT' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO snapshot_record FROM curve_prd_evidence_snapshot
  WHERE workspace_id = NEW.workspace_id AND initiative_id = NEW.initiative_id AND id = NEW.evidence_snapshot_id;
 IF NOT FOUND OR snapshot_record.artifact_version_id <> version_record.id OR
    version_record.evidence_snapshot_id <> NEW.evidence_snapshot_id THEN
  RAISE EXCEPTION 'CHECKPOINT_EVIDENCE_MISMATCH' USING ERRCODE = '23514';
 END IF;
 IF ROW(NEW.body_object_id, NEW.content_digest, NEW.body_size_bytes, NEW.normalization_schema_version,
        NEW.access_envelope_id, NEW.retention_policy_version_id, NEW.submitted_or_approved_by)
    IS DISTINCT FROM
    ROW(version_record.body_object_id, version_record.body_digest, version_record.body_size_bytes,
        version_record.body_schema_id, version_record.access_envelope_id,
        version_record.retention_policy_version_id, version_record.created_by) THEN
  RAISE EXCEPTION 'CHECKPOINT_VERSION_SUBJECT_MISMATCH' USING ERRCODE = '23514';
 END IF;
 IF NOT isfinite(NEW.recorded_at) OR binding_record.created_at > NEW.recorded_at OR
    snapshot_record.created_at > version_record.created_at OR version_record.created_at > NEW.recorded_at THEN
  RAISE EXCEPTION 'CHECKPOINT_CHRONOLOGY_INVALID' USING ERRCODE = '23514';
 END IF;
 SELECT * INTO previous_record FROM curve_document_checkpoint
  WHERE workspace_id = NEW.workspace_id AND external_document_binding_id = NEW.external_document_binding_id
  ORDER BY checkpoint_number DESC LIMIT 1;
 IF NOT FOUND THEN
  IF NEW.predecessor_id IS NOT NULL OR NEW.checkpoint_number <> 1 OR
     version_record.parent_version_id IS NOT NULL OR version_record.version_number <> 1 THEN
   RAISE EXCEPTION 'CHECKPOINT_PREDECESSOR_REQUIRED' USING ERRCODE = '23514';
  END IF;
 ELSE
  IF NEW.predecessor_id IS DISTINCT FROM previous_record.id
     OR NEW.checkpoint_number <> previous_record.checkpoint_number + 1
     OR version_record.parent_version_id IS DISTINCT FROM previous_record.artifact_version_id
     OR NEW.recorded_at < previous_record.recorded_at THEN
   RAISE EXCEPTION 'CHECKPOINT_PREDECESSOR_CONFLICT' USING ERRCODE = '23514';
  END IF;
 END IF;
 IF NEW.checkpoint_number <> version_record.version_number THEN
  RAISE EXCEPTION 'CHECKPOINT_VERSION_NUMBER_MISMATCH' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER curve_checkpoint_insert_guard BEFORE INSERT ON curve_document_checkpoint
 FOR EACH ROW EXECUTE FUNCTION curve_checkpoint_insert_guard();
"""

REVERSE_GUARDS = """
LOCK TABLE curve_document_checkpoint IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM curve_document_checkpoint) THEN
  RAISE EXCEPTION 'Nonempty checkpoints require a preservation migration';
 END IF;
END $$;
DROP TRIGGER curve_checkpoint_insert_guard ON curve_document_checkpoint;
DROP FUNCTION curve_checkpoint_insert_guard();
DROP TRIGGER curve_checkpoint_immutable ON curve_document_checkpoint;
ALTER TABLE curve_document_checkpoint DROP CONSTRAINT curve_cp_provider_fk;
ALTER TABLE curve_document_checkpoint DROP CONSTRAINT curve_cp_predecessor_fk;
ALTER TABLE curve_document_checkpoint DROP CONSTRAINT curve_cp_snapshot_fk;
ALTER TABLE curve_document_checkpoint DROP CONSTRAINT curve_cp_version_fk;
ALTER TABLE curve_document_checkpoint DROP CONSTRAINT curve_cp_binding_fk;
ALTER TABLE curve_document_checkpoint DROP CONSTRAINT curve_cp_initiative_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("curve", "0010_prd_artifact_evidence"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentCheckpoint",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("workspace_id", models.UUIDField(editable=False)),
                ("checkpoint_number", models.PositiveBigIntegerField(editable=False)),
                ("provider_file_id", models.CharField(editable=False, max_length=512)),
                ("provider_container_id", models.CharField(editable=False, max_length=512)),
                ("provider_version", models.CharField(editable=False, max_length=512)),
                ("revision_id", models.CharField(blank=True, editable=False, max_length=512, null=True)),
                ("body_object_id", models.UUIDField(editable=False)),
                ("content_digest", models.CharField(editable=False, max_length=71)),
                ("body_size_bytes", models.PositiveBigIntegerField(editable=False)),
                ("normalization_schema_version", models.CharField(editable=False, max_length=255)),
                ("access_evaluation_id", models.UUIDField(editable=False)),
                ("completeness_check_id", models.UUIDField(editable=False)),
                ("retention_policy_version_id", models.UUIDField(editable=False)),
                ("access_envelope_id", models.UUIDField(editable=False)),
                ("submitted_or_approved_by", models.JSONField(editable=False)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "artifact_version",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.prdartifactversion"),
                ),
                (
                    "evidence_snapshot",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.prdevidencesnapshot"),
                ),
                (
                    "external_document_binding",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.externaldocumentbinding"),
                ),
                ("initiative", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.initiative")),
                (
                    "predecessor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="curve.documentcheckpoint",
                    ),
                ),
                (
                    "provider_connection",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="curve.providerconnection"),
                ),
            ],
            options={
                "db_table": "curve_document_checkpoint",
                "constraints": [
                    models.UniqueConstraint(fields=("workspace_id", "initiative", "id"), name="curve_cp_scope_uq"),
                    models.UniqueConstraint(
                        fields=("workspace_id", "initiative", "external_document_binding", "id"),
                        name="curve_cp_binding_scope_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "external_document_binding", "checkpoint_number"),
                        name="curve_cp_number_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("workspace_id", "artifact_version"), name="curve_cp_artifact_ver_uq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("checkpoint_number__gte", 1), ("checkpoint_number__lte", 9007199254740991)),
                        name="curve_cp_number_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("body_size_bytes__gte", 1), ("body_size_bytes__lte", 9007199254740991)),
                        name="curve_cp_size_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("content_digest__regex", "^sha256:[0-9a-f]{64}$")),
                        name="curve_cp_digest_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("normalization_schema_version", ""), _negated=True),
                        name="curve_cp_schema_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("provider_file_id__regex", "^[A-Za-z0-9._~-]+$")), name="curve_cp_file_ck"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("provider_container_id__regex", "^[A-Za-z0-9._~-]+$")),
                        name="curve_cp_container_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("provider_version__regex", "^[A-Za-z0-9._~-]+$")),
                        name="curve_cp_source_ver_ck",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision_id__regex", "^[A-Za-z0-9._~-]+$")), name="curve_cp_revision_ck"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD_GUARDS, REVERSE_GUARDS),
    ]
