# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


FORWARD_GUARDS = """
ALTER TABLE curve_external_document_binding
    ADD CONSTRAINT curve_doc_initiative_tenant_fk
    FOREIGN KEY (workspace_id, initiative_id)
    REFERENCES curve_initiative (workspace_id, id) ON DELETE RESTRICT;
ALTER TABLE curve_external_document_binding
    ADD CONSTRAINT curve_doc_connection_tenant_fk
    FOREIGN KEY (workspace_id, provider_connection_id)
    REFERENCES curve_provider_connection (workspace_id, id) ON DELETE RESTRICT;
ALTER TABLE curve_external_document_binding
    ADD CONSTRAINT curve_doc_creator_ck CHECK (COALESCE(
        jsonb_typeof(created_by) = 'object'
        AND created_by - ARRAY['actor_type', 'actor_id'] = '{}'::jsonb
        AND created_by->>'actor_type' = 'HUMAN'
        AND jsonb_typeof(created_by->'actor_id') = 'string'
        AND length(created_by->>'actor_id') BETWEEN 1 AND 255,
        false
    ));

CREATE FUNCTION curve_guard_document_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Document binding deletion requires a governed successor policy'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 THEN
            RAISE EXCEPTION 'Document binding must start at version one' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.id, NEW.workspace_id, NEW.initiative_id, NEW.artifact_kind,
           NEW.provider_connection_id, NEW.provider_file_id, NEW.schema_version,
           NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.workspace_id, OLD.initiative_id, OLD.artifact_kind,
           OLD.provider_connection_id, OLD.provider_file_id, OLD.schema_version,
           OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'Document binding identity and attribution are immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Document binding version conflict' USING ERRCODE = '23514';
    END IF;
    IF OLD.last_reconciled_at IS NOT NULL AND
       (NEW.last_reconciled_at IS NULL OR NEW.last_reconciled_at < OLD.last_reconciled_at) THEN
        RAISE EXCEPTION 'Document observation cannot regress' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER curve_document_binding_guard
    BEFORE INSERT OR UPDATE OR DELETE ON curve_external_document_binding
    FOR EACH ROW EXECUTE FUNCTION curve_guard_document_binding();
"""

REVERSE_GUARDS = """
LOCK TABLE curve_external_document_binding IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM curve_external_document_binding) THEN
        RAISE EXCEPTION 'Nonempty document bindings require a preservation migration';
    END IF;
END $$;
DROP TRIGGER curve_document_binding_guard ON curve_external_document_binding;
DROP FUNCTION curve_guard_document_binding();
ALTER TABLE curve_external_document_binding DROP CONSTRAINT curve_doc_creator_ck;
ALTER TABLE curve_external_document_binding DROP CONSTRAINT curve_doc_connection_tenant_fk;
ALTER TABLE curve_external_document_binding DROP CONSTRAINT curve_doc_initiative_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("curve", "0008_initiative_business_intent"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalDocumentBinding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("schema_version", models.CharField(default="1.0", editable=False, max_length=20)),
                ("workspace_id", models.UUIDField(db_index=True, editable=False)),
                ("artifact_kind", models.CharField(default="PRD", editable=False, max_length=16)),
                ("provider_file_id", models.CharField(editable=False, max_length=512)),
                ("provider_container_id", models.CharField(max_length=512)),
                ("canonical_url", models.URLField(max_length=2048)),
                ("current_provider_version", models.CharField(max_length=512)),
                ("current_revision_id", models.CharField(blank=True, max_length=512, null=True)),
                ("current_modified_at", models.DateTimeField()),
                (
                    "synchronization_status",
                    models.CharField(
                        choices=[
                            ("CURRENT", "Current"),
                            ("CHANGED_SINCE_SUBMISSION", "Changed since submission"),
                            ("CHANGED_SINCE_APPROVAL", "Changed since approval"),
                            ("ACCESS_REVOKED", "Access revoked"),
                            ("MOVED_OUTSIDE_POLICY", "Moved outside policy"),
                            ("DELETED", "Deleted"),
                            ("PROVIDER_UNAVAILABLE", "Provider unavailable"),
                            ("RECONCILIATION_REQUIRED", "Reconciliation required"),
                        ],
                        default="RECONCILIATION_REQUIRED",
                        max_length=32,
                    ),
                ),
                (
                    "access_status",
                    models.CharField(
                        choices=[("ALLOWED", "Allowed"), ("DENIED", "Denied"), ("UNKNOWN", "Unknown")],
                        default="UNKNOWN",
                        max_length=16,
                    ),
                ),
                ("last_reconciled_at", models.DateTimeField(blank=True, null=True)),
                ("version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("created_by", models.JSONField(editable=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ],
            options={
                "db_table": "curve_external_document_binding",
            },
        ),
        migrations.AddConstraint(
            model_name="initiative",
            constraint=models.UniqueConstraint(fields=("workspace_id", "id"), name="curve_init_ws_id_uq"),
        ),
        migrations.AddConstraint(
            model_name="providerconnection",
            constraint=models.UniqueConstraint(fields=("workspace_id", "id"), name="curve_pconn_ws_id_uq"),
        ),
        migrations.AddField(
            model_name="externaldocumentbinding",
            name="initiative",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="document_bindings", to="curve.initiative"
            ),
        ),
        migrations.AddField(
            model_name="externaldocumentbinding",
            name="provider_connection",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="document_bindings",
                to="curve.providerconnection",
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.UniqueConstraint(fields=("workspace_id", "id"), name="curve_doc_ws_id_uq"),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.UniqueConstraint(
                fields=("workspace_id", "initiative", "artifact_kind"), name="curve_doc_ws_init_kind_uq"
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("schema_version", "1.0")), name="curve_doc_schema_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(condition=models.Q(("artifact_kind", "PRD")), name="curve_doc_kind_ck"),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(condition=models.Q(("version__gte", 1)), name="curve_doc_version_ck"),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "synchronization_status__in",
                        [
                            "CURRENT",
                            "CHANGED_SINCE_SUBMISSION",
                            "CHANGED_SINCE_APPROVAL",
                            "ACCESS_REVOKED",
                            "MOVED_OUTSIDE_POLICY",
                            "DELETED",
                            "PROVIDER_UNAVAILABLE",
                            "RECONCILIATION_REQUIRED",
                        ],
                    )
                ),
                name="curve_doc_sync_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("access_status__in", ["ALLOWED", "DENIED", "UNKNOWN"])), name="curve_doc_access_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("canonical_url__regex", "^https://[^[:space:]]+$")), name="curve_doc_url_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider_file_id__regex", "^[A-Za-z0-9._~-]+$")), name="curve_doc_file_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("provider_container_id__regex", "^[A-Za-z0-9._~-]+$")),
                name="curve_doc_container_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("current_provider_version__regex", "^[A-Za-z0-9._~-]+$")),
                name="curve_doc_provider_version_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldocumentbinding",
            constraint=models.CheckConstraint(
                condition=models.Q(("current_revision_id__regex", "^[A-Za-z0-9._~-]+$")), name="curve_doc_revision_ck"
            ),
        ),
        migrations.RunSQL(FORWARD_GUARDS, REVERSE_GUARDS),
    ]
