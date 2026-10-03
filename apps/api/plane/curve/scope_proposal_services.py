# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bounded whole-manifest replacement. Every item is explicit and non-controlling."""

import json
import uuid
from dataclasses import dataclass

from django.db import IntegrityError
from django.utils import timezone

from .models import AuditOutcome, DomainEvent, IdempotencyState, IdempotencyRecord, OutboxEvent
from .policy_services import CurvePolicyResourceNotFound
from .product_services import _command_identity, _load_or_create_idempotency
from .project_association_services import _uuid, _version, _idempotency, AssociationCommandError
from .scope_proposal_contracts import validate_scope_contract
from .scope_proposal_models import ScopeProposal, ScopeProposalRevision, ScopeProposalItem, ScopePurpose
from .scope_proposal_policy import REPLACE, READ, append_scope_audit, execute_scope_action, authorize_scope_items
from .scope_proposal_serialization import serialize_scope_item, serialize_scope_revision, scope_membership_digest
from .services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    canonical_json_bytes,
    operation_response_digest,
    idempotency_key_digest,
    sha256_digest,
)

MAX_MEMBERS = 100
MAX_REQUEST_BYTES = 65536
EVENT_SCHEMA = "https://curve.example.invalid/candidates/scope-proposal-event-v1.schema.json"
OUTBOX_DESTINATION = "CURVE_SCOPE_PROPOSAL_LOCAL_V1"


class ScopeCommandError(ValueError):
    def __init__(self, code="SCOPE_PROPOSAL_REQUEST_INVALID", status=422):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class ScopeResult:
    data: dict
    response_status: int
    replayed: bool = False


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScopeCommandError()
        result[key] = value
    return result


def _constant(_):
    raise ScopeCommandError()


def parse_scope_body(body):
    if type(body) is not bytes:
        raise ScopeCommandError()
    if len(body) > MAX_REQUEST_BYTES:
        raise ScopeCommandError("SCOPE_PROPOSAL_REQUEST_TOO_LARGE", 413)
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ScopeCommandError() from None
    return validate_scope_payload(payload)


def validate_scope_payload(payload):
    if type(payload) is dict and set(payload) == {"items"}:
        raise ScopeCommandError("SCOPE_PROPOSAL_PRECONDITION_REQUIRED", 428)
    if type(payload) is not dict or set(payload) != {"expected_scope_revision", "items"}:
        raise ScopeCommandError()
    expected = payload["expected_scope_revision"]
    if expected is None:
        raise ScopeCommandError("SCOPE_PROPOSAL_PRECONDITION_REQUIRED", 428)
    if type(expected) is not int or not 0 <= expected <= 9007199254740991:
        raise ScopeCommandError()
    items = payload["items"]
    if type(items) is not list or len(items) > MAX_MEMBERS:
        raise ScopeCommandError()
    selections, seen = [], set()
    for item in items:
        if type(item) is not dict or set(item) != {
            "association_id",
            "association_version",
            "source_issue_id",
            "purpose",
        }:
            raise ScopeCommandError()
        try:
            association = str(_uuid(item["association_id"], "association_id"))
            issue = str(_uuid(item["source_issue_id"], "source_issue_id"))
            version = _version(item["association_version"], "association_version")
        except AssociationCommandError as error:
            raise ScopeCommandError(status=error.status_code) from None
        if item["purpose"] not in ScopePurpose.values or issue in seen:
            raise ScopeCommandError()
        seen.add(issue)
        selections.append(
            dict(
                association_id=association, association_version=version, source_issue_id=issue, purpose=item["purpose"]
            )
        )
    return {"expected_scope_revision": expected, "items": sorted(selections, key=lambda item: item["source_issue_id"])}


def selection_for_item(item):
    return {
        "association_id": str(item.association_id),
        "association_version": item.association_version,
        "source_issue_id": str(item.source_issue_id),
        "purpose": item.purpose,
    }


def load_scope_revision(context, revision_id=None):
    head = context.head
    if head is None:
        if ScopeProposalRevision.objects.filter(
            workspace_id=context.workspace.id, initiative_id=context.initiative.id
        ).exists():
            raise CurvePolicyResourceNotFound
        return None, []
    revision = ScopeProposalRevision.objects.find_by_id(
        workspace_id=context.workspace.id, record_id=revision_id or head.current_revision_id, for_update=True
    )
    if (
        head.product_id != context.product.id
        or revision is None
        or revision.proposal_id != head.id
        or revision.initiative_id != context.initiative.id
        or revision.product_id != context.product.id
        or revision.version > head.version
        or (revision_id is None and revision.version != head.version)
    ):
        raise CurvePolicyResourceNotFound
    items = list(
        ScopeProposalItem.objects.select_for_update()
        .filter(workspace_id=context.workspace.id, revision_id=revision.id)
        .order_by("source_issue_id")
    )
    if (
        revision.item_count != len(items)
        or revision.delivery_count != sum(item.purpose == "PROPOSED_DELIVERY" for item in items)
        or len(items) > MAX_MEMBERS
        or len({item.source_issue_id for item in items}) != len(items)
        or revision.membership_digest != scope_membership_digest([serialize_scope_item(item) for item in items])
    ):
        raise CurvePolicyResourceNotFound
    return revision, items


def _authorize_revision(receipt, context, revision, items):
    observed = authorize_scope_items(receipt, context, [selection_for_item(item) for item in items])
    for original, fresh in zip(items, observed):
        if (
            str(original.provider_installation_id) != fresh["provider_installation_id"]
            or str(original.source_project_id) != fresh["source_project_id"]
        ):
            raise CurvePolicyResourceNotFound


def _ref(revision):
    return {
        "resource_type": "SCOPE_PROPOSAL_REVISION",
        "resource_id": str(revision.id),
        "resource_version": revision.version,
    }


def _replay(receipt, context, record):
    reference = record.response_resource_ref or {}
    if reference.get("resource_type") != "SCOPE_PROPOSAL_REVISION":
        raise ReplayResourceUnavailable
    revision, items = load_scope_revision(context, reference.get("resource_id"))
    if revision is None or revision.version != reference.get("resource_version"):
        raise ReplayResourceUnavailable
    _authorize_revision(receipt, context, revision, items)
    data = serialize_scope_revision(revision, items)
    validate_scope_contract("scope-proposal-revision-v1", data)
    event = DomainEvent.objects.filter(
        workspace_id=context.workspace.id,
        id=revision.command_receipt_id,
        aggregate_type="SCOPE_PROPOSAL",
        aggregate_id=revision.proposal_id,
        aggregate_version=revision.version,
    ).first()
    if event is None or event.payload.get("revision") != data:
        raise ReplayResourceUnavailable
    append_scope_audit(receipt, target_ref=_ref(revision), outcome=AuditOutcome.NO_EFFECT, key_digest=record.key_digest)
    return ScopeResult(data, record.response_status, True)


_NO_EFFECT = (
    ScopeCommandError,
    IdempotencyConflict,
    CommandAlreadyInProgress,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    IntegrityError,
)


def replace_scope_proposal(*, request, workspace_slug, initiative_id, payload, expected_version, raw_idempotency_key):
    payload = validate_scope_payload(payload)
    # Direct services cannot bypass the same size/count bounds as HTTP.
    if len(canonical_json_bytes(payload)) > MAX_REQUEST_BYTES:
        raise ScopeCommandError("SCOPE_PROPOSAL_REQUEST_TOO_LARGE", 413)
    try:
        _version(expected_version)
        _idempotency(raw_idempotency_key)
    except AssociationCommandError as error:
        raise ScopeCommandError(status=error.status_code) from None
    validate_scope_contract("scope-proposal-replace-v1", payload)
    subject = dict(payload, initiative_id=str(initiative_id), expected_initiative_version=expected_version)

    def resolve_subject(context):
        load_scope_revision(context)
        existing = (
            IdempotencyRecord.objects.select_for_update()
            .filter(
                workspace_id=context.workspace.id,
                principal_scope=f"HUMAN:{context.user.id}",
                command_scope=f"{REPLACE}:{initiative_id}",
                key_digest=idempotency_key_digest(raw_idempotency_key),
                request_digest=sha256_digest(canonical_json_bytes(subject)),
                state__in=IdempotencyRecord.TERMINAL_STATES,
            )
            .first()
        )
        if existing is not None:
            reference = existing.response_resource_ref or {}
            if reference.get("resource_type") != "SCOPE_PROPOSAL_REVISION":
                raise CurvePolicyResourceNotFound
            revision, items = load_scope_revision(context, reference.get("resource_id"))
            if revision is None or revision.version != reference.get("resource_version"):
                raise CurvePolicyResourceNotFound
            return [selection_for_item(item) for item in items], revision.id
        return payload["items"], None

    def callback(receipt, context):
        previous, _ = load_scope_revision(context)
        identity = _command_identity(
            receipt,
            command_scope=f"{REPLACE}:{initiative_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_json_bytes(subject),
        )
        record, _, replay = _load_or_create_idempotency(workspace_id=context.workspace.id, identity=identity)
        if replay:
            return _replay(receipt, context, record)
        initiative = context.initiative
        if (
            initiative.version != expected_version
            or (context.head.version if context.head else 0) != payload["expected_scope_revision"]
        ):
            raise OptimisticConcurrencyError
        if initiative.state != "DRAFT" or context.product.state != "ACTIVE":
            raise ScopeCommandError("SCOPE_PROPOSAL_STATE_CONFLICT", 409)
        observations = authorize_scope_items(receipt, context, payload["items"])
        receipt.proposal_id = context.head.id if context.head else uuid.uuid4()
        receipt.revision_id = uuid.uuid4()
        event_id = uuid.uuid4()
        items = [
            ScopeProposalItem(
                workspace_id=context.workspace.id,
                revision_id=receipt.revision_id,
                **{
                    key: uuid.UUID(value)
                    if key in {"association_id", "provider_installation_id", "source_project_id", "source_issue_id"}
                    else value
                    for key, value in item.items()
                },
            )
            for item in observations
        ]
        receipt.authorized_items = {str(item.source_issue_id): serialize_scope_item(item) for item in items}
        revision = ScopeProposalRevision(
            id=receipt.revision_id,
            workspace_id=context.workspace.id,
            proposal_id=receipt.proposal_id,
            initiative_id=initiative.id,
            product_id=context.product.id,
            version=(context.head.version if context.head else 0) + 1,
            initiative_version=initiative.version + 1,
            predecessor_id=previous.id if previous else None,
            item_count=len(items),
            delivery_count=sum(item.purpose == "PROPOSED_DELIVERY" for item in items),
            membership_digest=scope_membership_digest([serialize_scope_item(item) for item in items]),
            created_by=context.user.id,
            command_receipt_id=event_id,
        )
        receipt.final_initiative_version = revision.initiative_version
        revision.save()
        for item in items:
            item.save()
        initiative.version += 1
        initiative.updated_by = receipt.actor
        initiative.save(update_fields=["version", "updated_by", "updated_at"])
        head = context.head or ScopeProposal(
            id=receipt.proposal_id,
            workspace_id=context.workspace.id,
            initiative_id=initiative.id,
            product_id=context.product.id,
        )
        head.version, head.current_revision_id = revision.version, revision.id
        head.save()
        data = serialize_scope_revision(revision, items)
        validate_scope_contract("scope-proposal-revision-v1", data)
        event = DomainEvent.objects.create(
            id=event_id,
            workspace_id=context.workspace.id,
            event_type="CURVE.SCOPE_PROPOSAL.REPLACED",
            aggregate_type="SCOPE_PROPOSAL",
            aggregate_id=head.id,
            aggregate_version=revision.version,
            sequence=revision.version,
            actor=receipt.actor,
            effective_principal=receipt.actor,
            correlation_id=receipt.correlation_id,
            idempotency_key_digest=record.key_digest,
            classification="INTERNAL",
            payload_schema=EVENT_SCHEMA,
            payload={
                "schema_version": "1.0",
                "event_type": "CURVE.SCOPE_PROPOSAL.REPLACED",
                "revision": data,
                "policy_decision_id": str(receipt.decision_id),
            },
            occurred_at=timezone.now(),
        )
        validate_scope_contract("scope-proposal-event-v1", event.payload)
        OutboxEvent.objects.create(workspace_id=context.workspace.id, event_id=event.id, destination=OUTBOX_DESTINATION)
        reference = _ref(revision)
        digest = operation_response_digest(response_status=201, resource_ref=reference)
        append_scope_audit(
            receipt,
            target_ref=reference,
            outcome=AuditOutcome.SUCCEEDED,
            key_digest=record.key_digest,
            after_digest=digest,
        )
        record.state, record.response_status, record.response_resource_ref = IdempotencyState.COMPLETED, 201, reference
        record.response_digest, record.completed_at = digest, timezone.now()
        record.save(
            update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"]
        )
        return ScopeResult(data, 201)

    return execute_scope_action(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action=REPLACE,
        subject=subject,
        resolve_subject=resolve_subject,
        callback=callback,
        no_effect_exceptions=_NO_EFFECT,
    )


def read_scope_proposal(*, request, workspace_slug, initiative_id, revision_id=None):
    def resolve_subject(context):
        load_scope_revision(context)
        revision, items = load_scope_revision(context, revision_id)
        if revision is None:
            raise CurvePolicyResourceNotFound
        return [selection_for_item(item) for item in items], revision.id

    def callback(receipt, context):
        # Validate current head even when returning a historical revision.
        load_scope_revision(context)
        revision, items = load_scope_revision(context, revision_id)
        if revision is None:
            raise CurvePolicyResourceNotFound
        _authorize_revision(receipt, context, revision, items)
        append_scope_audit(receipt, target_ref=_ref(revision), outcome=AuditOutcome.ALLOWED)
        data = serialize_scope_revision(revision, items)
        validate_scope_contract("scope-proposal-revision-v1", data)
        return ScopeResult(data, 200)

    return execute_scope_action(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action=READ,
        resolve_subject=resolve_subject,
        subject={"revision_id": str(revision_id) if revision_id else None},
        callback=callback,
    )
