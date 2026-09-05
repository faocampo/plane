# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Two-phase authenticated PRD acceptance with current-authorized replay.

The configured trusted runtime owns current provider, evidence, readiness and
protected-storage authority. No runtime is provided or activated by this module.
prepare() is a context manager outside DB locks; revalidate() is local/DB-only.
The preparation context cleans up unused objects according to its approved policy.
It observes committed_operation_id to retain a referenced rationale after commit.
"""

from dataclasses import dataclass, field
from datetime import datetime
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    DocumentCheckpoint,
    ExternalDocumentBinding,
    GateAssignment,
    IdempotencyRecord,
    Initiative,
    PrdAcceptedCommand,
)
from .policy_services import (
    execute_authorized_mutation,
    policy_decision_ref_for_receipt,
    correlation_id_for_request,
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
)
from .prd_command_repository import record_accepted_prd_command
from .prd_commands import PrdCommandError, check_prd_command_subject
from .prd_policy_context import build_prd_policy_context
from .services import (
    _append_audit_event,
    _create_operation_authorized,
    idempotency_key_digest,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    ReplayResourceUnavailable,
)


class PrdRuntimeUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("PRD_RUNTIME_UNAVAILABLE")


@dataclass(frozen=True)
class PrdAcceptanceScope:
    workspace_id: uuid.UUID
    initiative_id: uuid.UUID
    actor_id: uuid.UUID
    action: str
    expected_version: int
    request_digest: str


@dataclass
class PrdAcceptancePreparation:
    scope: PrdAcceptanceScope
    valid_from: datetime
    valid_until: datetime
    checks: dict = field(repr=False)
    rationale_ref: dict | None = field(default=None, repr=False)
    access_envelope_id: uuid.UUID | None = field(default=None, repr=False)
    retention_policy_version_id: uuid.UUID | None = field(default=None, repr=False)
    committed_operation_id: uuid.UUID | None = None


_CHECKS = frozenset(
    {"provider_capability", "storage_policy", "source_access", "evidence_access", "readiness", "worker_ready"}
)
_SAFE_ERRORS = (
    PrdCommandError,
    PrdRuntimeUnavailable,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    ReplayResourceUnavailable,
)


def _preflight(command, workspace_id, initiative_id):
    initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
    if initiative is None:
        raise PrdCommandError("PRD_SUBJECT_UNAVAILABLE", 404)
    subject = command.subject_metadata()
    records = {}
    if command.action == "CURVE.PRD.SUBMIT":
        records["binding"] = ExternalDocumentBinding.objects.find_by_id(
            workspace_id=workspace_id, record_id=subject["external_document_binding_id"], for_update=True
        )
    else:
        records["checkpoint"] = DocumentCheckpoint.objects.find_by_id(
            workspace_id=workspace_id, record_id=subject["checkpoint_id"], for_update=True
        )
        records["gate_assignment"] = GateAssignment.objects.find_by_id(
            workspace_id=workspace_id, record_id=subject["gate_assignment_id"], for_update=True
        )
    check_prd_command_subject(command=command, initiative=initiative, **records)


def accept_prd_command(*, request, workspace_slug, initiative_id, command):
    # Provider/storage preparation must never inherit a caller's DB transaction.
    if transaction.get_connection().in_atomic_block:
        raise PrdRuntimeUnavailable
    runtime = getattr(settings, "CURVE_PRD_ACCEPTANCE_RUNTIME", None)
    if runtime is None or any(
        not callable(getattr(runtime, name, None)) for name in ("resolve_acl", "prepare", "revalidate")
    ):
        raise PrdRuntimeUnavailable
    actor = {"actor_type": "HUMAN", "actor_id": str(request.user.id)}
    correlation_id = correlation_id_for_request(request)
    action_suffix = command.action.removeprefix("CURVE.PRD.")
    command_scope = f"PRD_{action_suffix}:{initiative_id}"

    def context():
        return build_prd_policy_context(
            request=request,
            workspace_slug=workspace_slug,
            initiative_id=initiative_id,
            action=command.action,
            acl_resolver=runtime.resolve_acl,
            for_update=True,
        )

    def phase(prepared=None, *, final=False):
        def callback(receipt, _):
            scope = PrdAcceptanceScope(
                receipt.workspace_id,
                uuid.UUID(str(initiative_id)),
                uuid.UUID(actor["actor_id"]),
                command.action,
                command.expected_version,
                command.request_digest,
            )

            def audit(action):
                _append_audit_event(
                    workspace_id=receipt.workspace_id,
                    action=action,
                    target_ref=dict(receipt.resource_ref),
                    outcome="NO_EFFECT",
                    actor=actor,
                    correlation_id=correlation_id,
                    policy_decision_ref=policy_decision_ref_for_receipt(receipt),
                )

            try:
                with transaction.atomic():
                    existing = IdempotencyRecord.objects.filter(
                        workspace_id=receipt.workspace_id,
                        principal_scope=f"HUMAN:{actor['actor_id']}",
                        command_scope=command_scope,
                        key_digest=idempotency_key_digest(command.idempotency_key),
                    ).exists()
                    if not existing:
                        _preflight(command, receipt.workspace_id, initiative_id)
                        if not final:
                            audit("CURVE.PRD.PREPARATION_AUTHORIZED")
                            return scope
                        now = timezone.now()
                        if (
                            type(prepared) is not PrdAcceptancePreparation
                            or prepared.scope != scope
                            or prepared.committed_operation_id is not None
                            or type(prepared.checks) is not dict
                            or set(prepared.checks) != _CHECKS
                            or any(value is not True for value in prepared.checks.values())
                            or not isinstance(prepared.valid_from, datetime)
                            or prepared.valid_from.utcoffset() is None
                            or not isinstance(prepared.valid_until, datetime)
                            or prepared.valid_until.utcoffset() is None
                            or not prepared.valid_from <= now < prepared.valid_until
                            or runtime.revalidate(prepared) is not True
                            or not prepared.valid_from <= timezone.now() < prepared.valid_until
                        ):
                            raise PrdRuntimeUnavailable
                    result = _create_operation_authorized(
                        authorization_receipt=receipt,
                        authorization_action=command.action,
                        workspace_id=receipt.workspace_id,
                        principal_scope=f"HUMAN:{actor['actor_id']}",
                        command_scope=command_scope,
                        raw_idempotency_key=command.idempotency_key,
                        canonical_request=command.operation_request_identity(),
                        operation_type="WORKFLOW_COMMAND",
                        command_type=f"PRD_{action_suffix}",
                        target=dict(receipt.resource_ref),
                        actor=actor,
                        correlation_id=correlation_id,
                        destination="CURVE_PRD_CANDIDATE_V1",
                    )
                    if result.replayed:
                        recorded = PrdAcceptedCommand.objects.find_by_id(
                            workspace_id=receipt.workspace_id, record_id=result.operation.id
                        )
                        if (
                            recorded is None
                            or recorded.request_digest != command.request_digest
                            or recorded.actor_id != scope.actor_id
                        ):
                            raise ReplayResourceUnavailable
                    else:
                        record_accepted_prd_command(
                            authorization_receipt=receipt,
                            command=command,
                            operation=result.operation,
                            rationale_ref=prepared.rationale_ref,
                            access_envelope_id=prepared.access_envelope_id,
                            retention_policy_version_id=prepared.retention_policy_version_id,
                        )
                    return result
            except Exception as error:
                audit("CURVE.PRD.ACCEPTANCE_REJECTED")
                if isinstance(error, _SAFE_ERRORS):
                    raise
                raise PrdRuntimeUnavailable from None

        return execute_authorized_mutation(
            context_builder=context, mutation_callback=callback, no_effect_exceptions=_SAFE_ERRORS
        )

    first = phase()
    if not isinstance(first, PrdAcceptanceScope):
        return first
    try:
        with runtime.prepare(scope=first, command=command) as prepared:
            result = phase(prepared, final=True)
            if not result.replayed:
                prepared.committed_operation_id = result.operation.id
            return result
    except (*_SAFE_ERRORS, CurvePolicyDenied, CurvePolicyResourceNotFound):
        raise
    except Exception:
        raise PrdRuntimeUnavailable from None
