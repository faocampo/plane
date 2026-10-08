# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Additive immutable scoped PRD metadata, independent of legacy accepted rows."""

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

from .scoped_prd_commands import parse_scoped_prd_command
from .prd_metadata_validation import MAX_SAFE_INTEGER, require_metadata
from .prd_models import PrdImmutableModel, PrdImmutableQuerySet
from .prd_review_rationale import RATIONALE_MEDIA_TYPE


class ScopedPrdImmutableModel(PrdImmutableModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from .scoped_prd_repository import assert_scoped_write

        assert_scoped_write(self)
        return super().save(*args, **kwargs)


class ScopedPrdCommandQuerySet(PrdImmutableQuerySet):
    def find_by_id(self, *, workspace_id, record_id, for_update=False):
        queryset = self.for_workspace(workspace_id)
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.filter(operation_id=record_id).first()


class ScopedPrdAcceptedCommand(ScopedPrdImmutableModel):
    objects = models.Manager.from_queryset(ScopedPrdCommandQuerySet)()
    operation = models.OneToOneField("curve.Operation", primary_key=True, on_delete=models.PROTECT)
    workspace_id = models.UUIDField(editable=False)
    initiative = models.ForeignKey("curve.Initiative", on_delete=models.PROTECT)
    actor_id = models.UUIDField(editable=False)
    edition = models.CharField(max_length=64, default="curve.scoped-prd/v1-candidate", editable=False)
    action = models.CharField(max_length=32, editable=False)
    expected_version = models.PositiveBigIntegerField(editable=False)
    request_digest = models.CharField(max_length=71, editable=False)
    subject = models.JSONField(editable=False)
    accepted_at = models.DateTimeField(default=timezone.now, editable=False)
    rationale_object_id = models.UUIDField(null=True, editable=False)
    rationale_digest = models.CharField(max_length=71, null=True, editable=False)
    rationale_size_bytes = models.PositiveIntegerField(null=True, editable=False)
    rationale_access_envelope_id = models.UUIDField(null=True, editable=False)
    rationale_retention_policy_version_id = models.UUIDField(null=True, editable=False)

    class Meta:
        db_table = "curve_scoped_prd_accepted_command"
        constraints = [
            models.UniqueConstraint(fields=["workspace_id", "initiative", "operation"], name="curve_sprd_cmd_scope_uq"),
            models.CheckConstraint(
                condition=models.Q(edition="curve.scoped-prd/v1-candidate"), name="curve_sprd_cmd_edition_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action__in=[
                        "CURVE.PRD.SUBMIT",
                        "CURVE.PRD.APPROVE",
                        "CURVE.PRD.REQUEST_CHANGES",
                        "CURVE.PRD.REJECT",
                    ]
                ),
                name="curve_sprd_cmd_action_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(expected_version__gte=1, expected_version__lte=MAX_SAFE_INTEGER),
                name="curve_sprd_cmd_version_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^sha256:[0-9a-f]{64}$"), name="curve_sprd_cmd_digest_ck"
            ),
        ]

    @classmethod
    def from_command(
        cls, *, command, operation, rationale_ref=None, access_envelope_id=None, retention_policy_version_id=None
    ):
        """Build after independent storage authorization and byte promotion.

        Reference consistency does not prove existence, access or retention
        approval. Acceptance must commit this row with the Operation and outbox.
        """
        values = dict(
            operation=operation,
            workspace_id=operation.workspace_id,
            initiative_id=uuid.UUID(operation.target["resource_id"]),
            actor_id=uuid.UUID(operation.created_by["actor_id"]),
            action=command.action,
            expected_version=command.expected_version,
            request_digest=command.request_digest,
            subject=command.subject_metadata(),
        )
        if command.rationale_bytes is None:
            require_metadata(
                rationale_ref is None and access_envelope_id is None and retention_policy_version_id is None,
                "PRD_COMMAND_RATIONALE_UNEXPECTED",
            )
        else:
            require_metadata(
                type(rationale_ref) is dict
                and set(rationale_ref) == {"object_id", "digest", "size_bytes", "media_type"}
                and rationale_ref["media_type"] == RATIONALE_MEDIA_TYPE
                and type(rationale_ref["size_bytes"]) is int
                and rationale_ref["size_bytes"] == len(command.rationale_bytes)
                and rationale_ref["digest"] == "sha256:" + hashlib.sha256(command.rationale_bytes).hexdigest(),
                "PRD_COMMAND_RATIONALE_MISMATCH",
            )
            values.update(
                rationale_object_id=uuid.UUID(str(rationale_ref["object_id"])),
                rationale_digest=rationale_ref["digest"],
                rationale_size_bytes=rationale_ref["size_bytes"],
                rationale_access_envelope_id=uuid.UUID(str(access_envelope_id)),
                rationale_retention_policy_version_id=uuid.UUID(str(retention_policy_version_id)),
            )
        record = cls(**values)
        record.verified_payload(rationale_bytes=command.rationale_bytes)
        return record

    def verified_payload(self, *, rationale_bytes):
        """Reconstruct only after current command/source/evidence/body authorization.

        The transient result contains rationale. Never log or place it in an
        Operation, event, audit record or workflow history. No storage read occurs.
        """
        body = deepcopy(self.subject)
        if self.action == "CURVE.PRD.SUBMIT":
            require_metadata(rationale_bytes is None, "PRD_COMMAND_RATIONALE_UNEXPECTED")
            route = "submit"
        else:
            require_metadata(
                type(rationale_bytes) is bytes
                and len(rationale_bytes) == self.rationale_size_bytes
                and "sha256:" + hashlib.sha256(rationale_bytes).hexdigest() == self.rationale_digest,
                "PRD_COMMAND_RATIONALE_MISMATCH",
            )
            try:
                body["rationale"] = rationale_bytes.decode("utf-8", errors="strict")
            except UnicodeError:
                raise ValidationError("PRD_COMMAND_RATIONALE_MISMATCH", code="PRD_COMMAND_RATIONALE_MISMATCH") from None
            route = "approve" if self.action == "CURVE.PRD.APPROVE" else "return-for-revision"
        # The header key is irrelevant to payload identity and is not retained.
        parsed = parse_scoped_prd_command(
            route=route,
            body=json.dumps(body).encode(),
            if_match=f'"{self.expected_version}"',
            idempotency_key="internal-verification",
        )
        require_metadata(
            parsed.action == self.action and parsed.request_digest == self.request_digest, "PRD_COMMAND_DIGEST_MISMATCH"
        )
        return body

    def validate_metadata(self):
        require_metadata(self.edition == "curve.scoped-prd/v1-candidate", "SCOPED_PRD_EDITION_INVALID")
        # Validate the closed subject without retaining/reconstructing protected
        # rationale. The full request digest is independently checked on capture/read.
        body = deepcopy(self.subject)
        submit = self.action == "CURVE.PRD.SUBMIT"
        if not submit:
            body["rationale"] = "Validation placeholder"
        route = "submit" if submit else ("approve" if self.action == "CURVE.PRD.APPROVE" else "return-for-revision")
        parsed = parse_scoped_prd_command(
            route=route,
            body=json.dumps(body).encode(),
            if_match=f'"{self.expected_version}"',
            idempotency_key="internal-validation",
        )
        require_metadata(
            parsed.action == self.action and parsed.subject_metadata() == self.subject, "PRD_COMMAND_SUBJECT_INVALID"
        )
        values = (
            self.rationale_object_id,
            self.rationale_digest,
            self.rationale_size_bytes,
            self.rationale_access_envelope_id,
            self.rationale_retention_policy_version_id,
        )
        require_metadata(
            all(value is None for value in values) if submit else all(value is not None for value in values),
            "PRD_COMMAND_RATIONALE_INVALID",
        )


class ScopedPrdPayloadModel(ScopedPrdImmutableModel):
    """The closed payload is authoritative; typed columns must match it exactly."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    product_id = models.UUIDField(db_index=True, editable=False)
    initiative_id = models.UUIDField(db_index=True, editable=False)
    digest = models.CharField(max_length=71, db_index=True, editable=False)
    payload = models.JSONField(editable=False)
    contract_name = None

    class Meta:
        abstract = True

    @classmethod
    def from_payload(cls, payload, **extra):
        values = {"payload": deepcopy(payload)}
        for field in cls._meta.concrete_fields:
            if field.name == "payload" or field.name not in payload:
                continue
            value = payload[field.name]
            if isinstance(field, models.UUIDField):
                value = uuid.UUID(value)
            elif isinstance(field, models.DateTimeField):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            values[field.name] = value
        # Operation receipts are deliberately outside the public closed payload.
        require_metadata(not set(extra).intersection(values), "SCOPED_PRD_RECORD_SUBSTITUTION")
        values.update(extra)
        return cls(**values)

    def as_record(self):
        return deepcopy(self.payload)

    def validate_metadata(self):
        from .scoped_prd_contracts import metadata_digest, validate_scoped_contract

        record = self.as_record()
        validate_scoped_contract(self.contract_name, record)
        require_metadata(metadata_digest(record) == self.digest == record["digest"], "SCOPED_PRD_DIGEST_INVALID")
        for field in self._meta.concrete_fields:
            if field.name == "payload" or field.name not in record:
                continue
            value = getattr(self, field.attname)
            if isinstance(field, models.UUIDField):
                matches = str(value) == record[field.name]
            elif isinstance(field, models.DateTimeField):
                matches = value == datetime.fromisoformat(record[field.name].replace("Z", "+00:00"))
            else:
                matches = value == record[field.name]
            require_metadata(matches, "SCOPED_PRD_RECORD_SUBSTITUTION")


def _record_constraints(prefix):
    return [
        models.UniqueConstraint(fields=["workspace_id", "initiative_id", "id"], name=f"curve_sprd_{prefix}_scope_uq"),
        models.CheckConstraint(
            condition=models.Q(digest__regex=r"^sha256:[0-9a-f]{64}$"), name=f"curve_sprd_{prefix}_digest_ck"
        ),
    ]


class ScopedPrdObservation(ScopedPrdPayloadModel):
    contract_name = "Observation"
    proposal_id = models.UUIDField(db_index=True, editable=False)
    scope_revision_id = models.UUIDField(db_index=True, editable=False)
    created_by = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_scoped_prd_observation"
        constraints = _record_constraints("obs")


class ScopedPrdReadiness(ScopedPrdPayloadModel):
    contract_name = "Readiness"
    base_readiness_id = models.UUIDField(unique=True, editable=False)
    observation_set_id = models.UUIDField(db_index=True, editable=False)

    class Meta:
        db_table = "curve_scoped_prd_readiness"
        constraints = _record_constraints("ready")


class ScopedPrdSubject(ScopedPrdPayloadModel):
    contract_name = "Subject"
    checkpoint_id = models.UUIDField(unique=True, editable=False)
    observation_set_id = models.UUIDField(db_index=True, editable=False)
    scoped_readiness_id = models.UUIDField(unique=True, editable=False)
    submission_operation_id = models.UUIDField(unique=True, editable=False)
    created_by = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_scoped_prd_subject"
        constraints = _record_constraints("subj")


class ScopedPrdDecision(ScopedPrdPayloadModel):
    contract_name = "Decision"
    decision_id = models.UUIDField(unique=True, editable=False)
    scoped_subject_id = models.UUIDField(unique=True, editable=False)
    review_operation_id = models.UUIDField(unique=True, editable=False)
    created_by = models.UUIDField(editable=False)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "curve_scoped_prd_decision"
        constraints = _record_constraints("dec")
