# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Atomic ProductApprover reopening and finite full replacement, before any plan."""

from datetime import timedelta
import json
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import DomainEvent, OutboxEvent, IdempotencyState, PrdReviewDecision
from .policy_services import policy_decision_ref_for_receipt, correlation_id_for_request
from .prd_acceptance import PrdRuntimeUnavailable
from .prd_commands import PrdCommandError, _object
from .product_services import _load_or_create_idempotency
from .scope_proposal_models import ScopeProposalItem, ScopeProposalRevision
from .scope_proposal_services import ScopeResult, ScopeCommandError, validate_scope_payload
from .scope_proposal_serialization import serialize_scope_item, serialize_scope_revision, scope_membership_digest
from .scope_reopening_contracts import (
    SCHEMA_VERSION,
    POLICY_EDITION,
    REVISION_EDITION,
    ACTION,
    MAX_COMMAND_BYTES,
    canonical,
    digest,
    metadata_digest,
    validate_reopening_contract,
)
from .scope_reopening_models import ScopeReopening
from .scope_reopening_policy import (
    build_reopening_policy_context,
    require_reopening_current,
    execute_reopening_action,
    revalidate_reopening_authority,
    ReopeningAuthorityDenied,
)
from .scope_reopening_repository import reopening_write, require_reopened_revision
from .services import (
    _append_audit_event,
    idempotency_key_digest,
    sha256_digest,
    operation_response_digest,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    ReplayResourceUnavailable,
)

OUTBOX_DESTINATION = "CURVE_SCOPE_REOPENING_LOCAL_V1"
EVENT_SCHEMA = "https://curve.example.invalid/candidates/scope-reopening-v1/scope-reopening-event-v1.schema.json"
_ERRORS = (
    PrdCommandError,
    PrdRuntimeUnavailable,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    ReplayResourceUnavailable,
)


def validate_scope_reopening_payload(payload):
    validate_reopening_contract("scope-reopening-command-v1", payload)
    try:
        if type(payload) is not dict or not payload["reason"].strip() or len(canonical(payload)) > MAX_COMMAND_BYTES:
            raise ValueError
        selection = validate_scope_payload(
            {"expected_scope_revision": payload["expected_scope_revision"], "items": payload["items"]}
        )
        return dict(payload, items=selection["items"])
    except (ScopeCommandError, ValueError, TypeError, UnicodeError, RecursionError):
        raise PrdCommandError("SCOPE_REOPENING_INVALID", 422) from None


def parse_scope_reopening_body(body):
    if type(body) is not bytes:
        raise PrdCommandError("SCOPE_REOPENING_INVALID", 422)
    if len(body) > MAX_COMMAND_BYTES:
        raise PrdCommandError("SCOPE_REOPENING_TOO_LARGE", 413)
    try:
        payload = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        return validate_scope_reopening_payload(payload)
    except PrdCommandError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PrdCommandError("SCOPE_REOPENING_INVALID", 422) from None


def _headers(expected_version, key):
    if type(expected_version) is not int or not 1 <= expected_version <= 9007199254740991:
        raise PrdCommandError("VERSION_CONFLICT", 412)
    if (
        type(key) is not str
        or not 1 <= len(key) <= 255
        or not key.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in key)
    ):
        raise PrdCommandError("IDEMPOTENCY_KEY_INVALID", 422)
    try:
        key.encode("utf-8", errors="strict")
    except UnicodeError:
        raise PrdCommandError("IDEMPOTENCY_KEY_INVALID", 422) from None


def reopen_and_replace_scope(*, request, workspace_slug, initiative_id, payload, expected_version, raw_idempotency_key):
    payload = validate_scope_reopening_payload(payload)
    _headers(expected_version, raw_idempotency_key)
    runtime = getattr(settings, "CURVE_PRD_ACCEPTANCE_RUNTIME", None)
    if not callable(getattr(runtime, "resolve_acl", None)):
        raise PrdRuntimeUnavailable
    actor = {"actor_type": "HUMAN", "actor_id": str(request.user.id)}
    correlation = correlation_id_for_request(request)
    request_digest = digest(
        dict(edition=SCHEMA_VERSION, action=ACTION, expected_version=expected_version, payload=payload)
    )

    def context_builder():
        return build_reopening_policy_context(
            request=request,
            workspace_slug=workspace_slug,
            initiative_id=initiative_id,
            acl_resolver=runtime.resolve_acl,
        )

    def current_resolver():
        from plane.db.models import Workspace

        workspace = Workspace.objects.only("id").get(slug=workspace_slug)
        return require_reopening_current(
            workspace_id=workspace.id,
            initiative_id=initiative_id,
            actor_id=request.user.id,
            selections=payload["items"],
        )

    def callback(receipt, context):
        def audit(outcome, reference=None, key_digest=None, after_digest=None):
            _append_audit_event(
                workspace_id=receipt.workspace_id,
                action=ACTION,
                target_ref=reference or dict(receipt.resource_ref),
                outcome=outcome,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation,
                key_digest=key_digest,
                after_digest=after_digest,
                policy_decision_ref=policy_decision_ref_for_receipt(receipt),
            )

        try:
            with transaction.atomic():
                identity = dict(
                    principal_scope=f"HUMAN:{request.user.id}",
                    command_scope=f"{ACTION}:{initiative_id}",
                    key_digest=idempotency_key_digest(raw_idempotency_key),
                    request_digest=request_digest,
                    expires_at=timezone.now() + timedelta(days=1),
                )
                idem, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=identity)
                if replay:
                    reference = idem.response_resource_ref or {}
                    if reference.get("resource_type") != "SCOPE_REOPENING" or reference.get("resource_version") != 1:
                        raise ReplayResourceUnavailable
                    reopening = ScopeReopening.objects.find_by_id(
                        workspace_id=receipt.workspace_id, record_id=reference.get("resource_id"), for_update=True
                    )
                    if not (
                        reopening is not None
                        and reopening.created_by == request.user.id
                        and reopening.request_digest == request_digest
                        and reopening.initiative_id == context.initiative.id
                        and reopening.scope_revision_id == context.revision.id
                        and context.initiative.pending_scope_reopening_id == reopening.id
                        and context.initiative.state == "ALIGNING"
                        and context.initiative.version == reopening.previous_initiative_version + 1
                    ):
                        raise ReplayResourceUnavailable
                    data = reopening.as_record()
                    observed = [
                        {k: v for k, v in item.items() if k != "source_observed_at"}
                        for item in context.observed_members
                    ]
                    retained = [
                        {k: v for k, v in item.items() if k != "source_observed_at"}
                        for item in data["revision"]["items"]
                    ]
                    if observed != retained:
                        raise ReplayResourceUnavailable
                    require_reopened_revision(
                        context.revision,
                        list(
                            ScopeProposalItem.objects.filter(revision_id=context.revision.id).order_by(
                                "source_issue_id"
                            )
                        ),
                    )
                    if idem.response_status != 201 or idem.response_digest != operation_response_digest(
                        response_status=201, resource_ref=reference
                    ):
                        raise ReplayResourceUnavailable
                else:
                    if (
                        context.initiative.version != expected_version
                        or context.head.version != payload["expected_scope_revision"]
                    ):
                        raise PrdCommandError("VERSION_CONFLICT", 412)
                    if context.initiative.state not in {"ALIGNING", "PRD_REVIEW", "PLANNING"}:
                        raise PrdCommandError("SCOPE_REOPENING_STATE_CONFLICT", 409)
                    reopening, data = _write_reopening(
                        receipt, context, request_digest, payload["reason"], actor, correlation, idem
                    )
                    reference = dict(resource_type="SCOPE_REOPENING", resource_id=str(reopening.id), resource_version=1)
                    idem.state, idem.response_status, idem.response_resource_ref = (
                        IdempotencyState.COMPLETED,
                        201,
                        reference,
                    )
                    idem.response_digest = operation_response_digest(response_status=201, resource_ref=reference)
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
                # An ACL callback is not retained permission and may mutate source state;
                # repeat every database/native predicate after it under the same fences.
                fresh = revalidate_reopening_authority(
                    context_builder=context_builder, current_resolver=current_resolver, expected=context
                )
                if (
                    fresh.fence != context.fence
                    or fresh.initiative.state != "ALIGNING"
                    or fresh.initiative.pending_scope_reopening_id != reopening.id
                    or fresh.revision.id != reopening.scope_revision_id
                    or fresh.initiative.version != reopening.previous_initiative_version + 1
                ):
                    raise PrdCommandError("SCOPE_REOPENING_SUBJECT_CHANGED", 409)
                audit("NO_EFFECT" if replay else "SUCCEEDED", reference, idem.key_digest, idem.response_digest)
                # Audit hooks run inside the same transaction; no callback after
                # this final exact fence may produce or retain current authority.
                final = revalidate_reopening_authority(
                    context_builder=context_builder, current_resolver=current_resolver, expected=fresh
                )
                if (
                    final.initiative.pending_scope_reopening_id != reopening.id
                    or final.initiative.version != reopening.previous_initiative_version + 1
                    or final.revision.id != reopening.scope_revision_id
                    or final.initiative.state != "ALIGNING"
                ):
                    raise ReopeningAuthorityDenied
                return ScopeResult(data, 201, replay)
        except ReopeningAuthorityDenied:
            raise
        except Exception as error:
            audit("NO_EFFECT")
            if isinstance(error, _ERRORS):
                raise
            raise PrdRuntimeUnavailable from None

    return execute_reopening_action(
        context_builder=context_builder,
        current_resolver=current_resolver,
        mutation_callback=callback,
        request_digest=request_digest,
        no_effect_exceptions=_ERRORS,
    )


def _write_reopening(receipt, context, request_digest, reason, actor, correlation, idem):
    initiative = context.initiative
    event_id, revision_id, reopening_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    items = [
        ScopeProposalItem(
            workspace_id=context.workspace.id,
            revision_id=revision_id,
            **{
                key: uuid.UUID(value)
                if key in {"association_id", "provider_installation_id", "source_project_id", "source_issue_id"}
                else value
                for key, value in item.items()
            },
        )
        for item in context.observed_members
    ]
    revision = ScopeProposalRevision(
        id=revision_id,
        workspace_id=context.workspace.id,
        proposal_id=context.head.id,
        initiative_id=initiative.id,
        product_id=context.product.id,
        version=context.head.version + 1,
        initiative_version=initiative.version + 1,
        predecessor_id=context.revision.id,
        item_count=len(items),
        delivery_count=sum(item.purpose == "PROPOSED_DELIVERY" for item in items),
        membership_digest=scope_membership_digest([serialize_scope_item(item) for item in items]),
        created_by=context.actor_id,
        command_receipt_id=event_id,
        policy_edition=REVISION_EDITION,
    )
    prior_approved = bool(
        initiative.controlling_prd_decision_id
        and PrdReviewDecision.objects.filter(
            workspace_id=context.workspace.id,
            initiative_id=initiative.id,
            id=initiative.controlling_prd_decision_id,
            state="APPROVED",
        ).exists()
    )
    data = dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        id=str(reopening_id),
        workspace_id=str(context.workspace.id),
        product_id=str(context.product.id),
        initiative_id=str(initiative.id),
        previous_initiative_version=initiative.version,
        initiative_version=initiative.version + 1,
        previous_state=initiative.state,
        state="ALIGNING",
        revision=serialize_scope_revision(revision, items),
        reason_digest=sha256_digest(reason.encode("utf-8")),
        historical_checkpoint_status="RETAINED_STALE" if initiative.current_prd_checkpoint_id else "NONE",
        approval_invalidated=prior_approved,
        prd_authority="REQUIRES_FRESH_SCOPED_SUBMISSION",
        created_by=str(context.actor_id),
        recorded_at=revision.recorded_at.isoformat(),
        policy_decision_id=str(receipt.decision_id),
        command_receipt_id=str(event_id),
        controlling=False,
    )
    data["digest"] = metadata_digest(data)
    validate_reopening_contract("scope-reopening-receipt-v1", data)
    reopening = ScopeReopening(
        id=reopening_id,
        workspace_id=context.workspace.id,
        product_id=context.product.id,
        initiative_id=initiative.id,
        proposal_id=context.head.id,
        scope_revision_id=revision_id,
        predecessor_revision_id=context.revision.id,
        previous_initiative_version=initiative.version,
        previous_state=initiative.state,
        previous_checkpoint_id=initiative.current_prd_checkpoint_id,
        previous_decision_id=initiative.controlling_prd_decision_id,
        previous_pending_reopening_id=initiative.pending_scope_reopening_id,
        created_by=context.actor_id,
        reason_digest=data["reason_digest"],
        request_digest=request_digest,
        policy_decision_id=receipt.decision_id,
        command_receipt_id=event_id,
        recorded_at=revision.recorded_at,
        digest=data["digest"],
        payload=data,
    )
    with reopening_write(receipt, context, reopening=reopening, revision=revision, items=items):
        reopening.save()
        revision.save()
        for item in items:
            item.save()
        initiative.state = "ALIGNING"
        initiative.controlling_prd_decision_id = None
        initiative.pending_scope_reopening_id = reopening.id
        initiative.version += 1
        initiative.updated_by = actor
        initiative.save(
            update_fields=[
                "state",
                "controlling_prd_decision_id",
                "pending_scope_reopening_id",
                "version",
                "updated_by",
                "updated_at",
            ]
        )
        head = context.head
        head.version, head.current_revision_id = revision.version, revision.id
        head.save()
    event_payload = dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        event_type="CURVE.SCOPE.REOPENED_AND_REPLACED",
        reopening_id=str(reopening.id),
        reopening_digest=reopening.digest,
        initiative_id=str(initiative.id),
        scope_revision_id=str(revision.id),
        policy_decision_id=str(receipt.decision_id),
    )
    validate_reopening_contract("scope-reopening-event-v1", event_payload)
    event = DomainEvent.objects.create(
        id=event_id,
        workspace_id=context.workspace.id,
        event_type=event_payload["event_type"],
        aggregate_type="SCOPE_PROPOSAL",
        aggregate_id=head.id,
        aggregate_version=revision.version,
        sequence=revision.version,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation,
        idempotency_key_digest=idem.key_digest,
        classification="INTERNAL",
        payload_schema=EVENT_SCHEMA,
        payload=event_payload,
        occurred_at=timezone.now(),
    )
    OutboxEvent.objects.create(workspace_id=context.workspace.id, event_id=event.id, destination=OUTBOX_DESTINATION)
    return reopening, data
