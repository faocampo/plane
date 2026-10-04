# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Audited, idempotent metadata capture, separate from frozen C1 selection."""

from dataclasses import dataclass
from datetime import timedelta
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import DomainEvent, OutboxEvent, IdempotencyState
from .policy_services import execute_authorized_mutation, policy_decision_ref_for_receipt, correlation_id_for_request
from .prd_acceptance import PrdRuntimeUnavailable
from .prd_commands import PrdCommandError
from .prd_metadata_validation import instant
from .prd_policy_context import build_prd_policy_context
from .product_services import _load_or_create_idempotency
from .scoped_prd_commands import ScopedPrdCommand, validate_scoped_command
from .scoped_prd_contracts import SCHEMA_VERSION, POLICY_EDITION, validate_scoped_contract
from .scoped_prd_models import ScopedPrdObservation
from .scoped_prd_policy import require_scoped_current, scope_pins
from .scoped_prd_repository import scoped_write, entity, sealed
from .services import (
    _append_audit_event,
    idempotency_key_digest,
    operation_response_digest,
    sha256_digest,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    ReplayResourceUnavailable,
)


@dataclass(frozen=True)
class ObservationResult:
    data: dict
    response_status: int
    replayed: bool = False


_ERRORS = (
    PrdCommandError,
    PrdRuntimeUnavailable,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    ReplayResourceUnavailable,
)


def capture_scoped_prd_observation(*, request, workspace_slug, initiative_id, command):
    validate_scoped_command(command)
    if type(command) is not ScopedPrdCommand or command.action != "CURVE.SCOPED_PRD.OBSERVE":
        raise PrdCommandError("SCOPED_PRD_INVALID")
    runtime = getattr(settings, "CURVE_PRD_ACCEPTANCE_RUNTIME", None)
    if not callable(getattr(runtime, "resolve_acl", None)):
        raise PrdRuntimeUnavailable
    actor = dict(actor_type="HUMAN", actor_id=str(request.user.id))
    correlation = correlation_id_for_request(request)

    def context_builder():
        return build_prd_policy_context(
            request=request,
            workspace_slug=workspace_slug,
            initiative_id=initiative_id,
            action="CURVE.PRD.SUBMIT",
            acl_resolver=runtime.resolve_acl,
            for_update=True,
        )

    def callback(receipt, _):
        def audit(outcome, target=None):
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action="CURVE.SCOPED_PRD.OBSERVE",
                target_ref=target or dict(receipt.resource_ref),
                outcome=outcome,
                actor=actor,
                correlation_id=correlation,
                policy_decision_ref=policy_decision_ref_for_receipt(receipt),
            )

        try:
            with transaction.atomic():
                context = require_scoped_current(
                    workspace_id=receipt.workspace_id, initiative_id=initiative_id, actor_id=request.user.id
                )
                identity = dict(
                    principal_scope=f"HUMAN:{request.user.id}",
                    command_scope=f"SCOPED_PRD_V1_OBSERVE:{initiative_id}",
                    key_digest=idempotency_key_digest(command.idempotency_key),
                    request_digest=sha256_digest(command.operation_request_identity()),
                    expires_at=timezone.now() + timedelta(days=1),
                )
                idem, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=identity)
                if replay:
                    ref = idem.response_resource_ref or {}
                    if ref.get("resource_type") != "SCOPED_PRD_OBSERVATION":
                        raise ReplayResourceUnavailable
                    observation = ScopedPrdObservation.objects.find_by_id(
                        workspace_id=receipt.workspace_id, record_id=ref.get("resource_id"), for_update=True
                    )
                    if observation is None or observation.created_by != request.user.id:
                        raise ReplayResourceUnavailable
                    require_scoped_current(
                        workspace_id=receipt.workspace_id,
                        initiative_id=initiative_id,
                        actor_id=request.user.id,
                        observation=observation,
                    )
                    data = observation.as_record()
                else:
                    if context.initiative.version != command.expected_version:
                        raise PrdCommandError("VERSION_CONFLICT", 412)
                    if context.initiative.state not in {"ALIGNING", "PRD_REVIEW"}:
                        raise PrdCommandError("SCOPED_PRD_STATE_CONFLICT", 409)
                    if any(command.subject_metadata()[key] != value for key, value in scope_pins(context).items()):
                        raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
                    data = sealed(
                        dict(
                            entity(context, uuid.uuid4()),
                            initiative_version=context.initiative.version,
                            **scope_pins(context),
                            members=list(context.observed_members),
                            reviewers=list(context.reviewers),
                            created_by=str(request.user.id),
                            recorded_at=instant(timezone.now()),
                            controlling=False,
                        )
                    )
                    observation = ScopedPrdObservation.from_payload(data)
                    with scoped_write(receipt, context, action="CURVE.PRD.SUBMIT"):
                        observation.save()
                    payload = dict(
                        schema_version=SCHEMA_VERSION,
                        policy_edition=POLICY_EDITION,
                        event_type="CURVE.SCOPED_PRD.OBSERVATION_RECORDED",
                        observation_id=str(observation.id),
                        observation_digest=observation.digest,
                        initiative_id=str(initiative_id),
                        policy_decision_id=str(receipt.decision_id),
                    )
                    validate_scoped_contract("scoped-prd-observed-event-v1", payload)
                    event = DomainEvent.objects.create(
                        workspace_id=receipt.workspace_id,
                        event_type=payload["event_type"],
                        aggregate_type="SCOPED_PRD_OBSERVATION",
                        aggregate_id=observation.id,
                        aggregate_version=1,
                        sequence=1,
                        actor=actor,
                        effective_principal=actor,
                        correlation_id=correlation,
                        idempotency_key_digest=idem.key_digest,
                        classification="INTERNAL",
                        payload_schema="https://curve.example.invalid/candidates/scoped-prd-v1/scoped-prd-observed-event-v1.schema.json",
                        payload=payload,
                        occurred_at=timezone.now(),
                    )
                    OutboxEvent.objects.create(
                        workspace_id=receipt.workspace_id, event_id=event.id, destination="CURVE_SCOPED_PRD_METADATA_V1"
                    )
                    ref = dict(
                        resource_type="SCOPED_PRD_OBSERVATION", resource_id=str(observation.id), resource_version=1
                    )
                    idem.state, idem.response_status, idem.response_resource_ref = IdempotencyState.COMPLETED, 201, ref
                    idem.response_digest = operation_response_digest(response_status=201, resource_ref=ref)
                    idem.completed_at = timezone.now()
                    idem.save(
                        update_fields=[
                            "state",
                            "response_status",
                            "response_resource_ref",
                            "response_digest",
                            "completed_at",
                        ]
                    )
                fresh = require_scoped_current(
                    workspace_id=receipt.workspace_id,
                    initiative_id=initiative_id,
                    actor_id=request.user.id,
                    observation=observation,
                )
                if fresh.fence != context.fence:
                    raise PrdCommandError("SCOPED_PRD_SUBJECT_CHANGED", 409)
                audit("NO_EFFECT" if replay else "SUCCEEDED", ref)
                return ObservationResult(data, 201, replay)
        except Exception as error:
            audit("NO_EFFECT")
            if isinstance(error, _ERRORS):
                raise
            raise PrdRuntimeUnavailable from None

    return execute_authorized_mutation(
        context_builder=context_builder, mutation_callback=callback, no_effect_exceptions=_ERRORS
    )
