# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Current-owner document preparation with recoverable native command receipts."""

from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder
from plane.curve.item_creation_material import ItemScopeRequirement
from plane.curve.item_local_material import ItemMaterialUnavailable, LocalItemMaterialResolver
from plane.curve.item_scope_authority import resolve_item_scope_facts, scope_preparation_reason
from plane.curve.item_scope_preparation import normalize_scope_document, prepare_scope_document
from plane.curve.item_scope_results import prepared_scope_result, validate_retained_scope
from plane.curve.models import (
    AuditOutcome,
    DomainEvent,
    IdempotencyRecord,
    IdempotencyState,
    OutboxEvent,
    PolicyDecision,
)
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    _next_policy_sequence,
    correlation_id_for_request,
)
from plane.curve.product_services import (
    ProductValidationError,
    _command_identity,
    _load_or_create_idempotency,
    _validate_expected_version,
)
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    _append_audit_event,
    canonical_json_bytes,
    operation_response_digest,
)
from plane.db.models import Workspace


_POLICY_PATH = Path(__file__).parent / "items/scope-preparation-policy-v1.json"
POLICY = json.loads(_POLICY_PATH.read_bytes())
POLICY_DIGEST = "sha256:" + hashlib.sha256(canonical_json_bytes(POLICY)).hexdigest()
ACTION = "CURVE.ITEM.PREPARE_ITEM_SCOPE"
NO_EFFECT = (
    ProductValidationError,
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    ItemMaterialUnavailable,
)


@dataclass(frozen=True, slots=True)
class ItemScopeResult:
    resource_ref: dict
    response_status: int
    response_digest: str
    replayed: bool


def _capture(resolver, facts, ref):
    context = facts.storage_context()
    return resolver.capture(
        workspace_id=context.workspace_id,
        product_id=context.product_id,
        roadmap_id=context.roadmap_id,
        actor_id=context.actor_id,
        membership_id=context.membership_id,
        membership_generation=context.membership_generation,
        requirements=(ItemScopeRequirement(ref),),
    )


def _audit(decision, actor, correlation, target, outcome, *, key=None, digest=None, replay=False):
    return _append_audit_event(
        workspace_id=decision.workspace_id,
        action=ACTION + (".IDEMPOTENT_REPLAY" if replay else ""),
        target_ref=target,
        outcome=outcome,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation,
        key_digest=key,
        after_digest=digest,
        policy_decision_ref={
            "resource_type": "POLICY_DECISION",
            "resource_id": str(decision.id),
            "resource_version": 1,
        },
    )


def execute_item_scope_preparation(
    *, request, workspace_slug, product_id, roadmap_id, payload, expected_version, raw_idempotency_key
):
    raw = normalize_scope_document(payload)
    # Detach caller-owned input before any wait or mutation.
    payload = {"body": json.loads(raw)["body"]}
    _validate_expected_version(expected_version)
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    try:
        product_id, roadmap_id = UUID(str(product_id)), UUID(str(roadmap_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error
    actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
    correlation = correlation_id_for_request(request)
    result = error = None
    with ExitStack() as materials:
        with transaction.atomic(durable=True):
            from plane.curve.scope_reopening_qualification import require_item_scope_qualification

            require_item_scope_qualification()
            workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
            if workspace is None:
                raise CurvePolicyResourceNotFound
            facts = retained = resolver = captured = identity = None
            reason = "RESOURCE_UNAVAILABLE"
            try:
                facts = resolve_item_scope_facts(
                    workspace_slug=workspace_slug,
                    product_id=product_id,
                    roadmap_id=roadmap_id,
                    actor_id=user.id,
                )
                reason = scope_preparation_reason(facts)
            except CurvePolicyResourceNotFound:
                pass
            if reason == "ALLOW" and (
                getattr(settings, "CURVE_ENVIRONMENT", None) != "LOCAL"
                or getattr(settings, "CURVE_ITEM_SCOPE_PREPARATION_ENABLED", False) is not True
            ):
                reason = "LOCAL_SCOPE_PREPARATION_DISABLED"
            if reason == "ALLOW":
                try:
                    identity = _command_identity(
                        SimpleNamespace(actor=actor),
                        command_scope=f"{ACTION}:{product_id}:{roadmap_id}",
                        raw_idempotency_key=raw_idempotency_key,
                        canonical_request=canonical_json_bytes(
                            {
                                "action": ACTION,
                                "workspace_id": str(workspace.id),
                                "product_id": str(product_id),
                                "roadmap_id": str(roadmap_id),
                                "expected_version": expected_version,
                                "body_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                            }
                        ),
                    )
                    retained = (
                        IdempotencyRecord.objects.select_for_update()
                        .filter(
                            workspace_id=workspace.id,
                            principal_scope=identity["principal_scope"],
                            command_scope=identity["command_scope"],
                            key_digest=identity["key_digest"],
                        )
                        .first()
                    )
                    reference = None
                    if retained is not None:
                        if retained.request_digest != identity["request_digest"]:
                            raise IdempotencyConflict
                        if retained.state not in IdempotencyRecord.TERMINAL_STATES:
                            raise CommandAlreadyInProgress
                        reference = validate_retained_scope(retained, payload=payload)
                    elif facts.roadmap_version != expected_version:
                        raise OptimisticConcurrencyError
                    resolver = materials.enter_context(LocalItemMaterialResolver.from_settings())
                    if reference is not None:
                        materials.enter_context(resolver.lease())
                        captured = _capture(resolver, facts, reference)
                except ItemMaterialUnavailable:
                    reason = "PROTECTED_MATERIAL_UNAVAILABLE"
                except NO_EFFECT as caught:
                    error = caught
            parent = {"resource_type": "ROADMAP", "resource_id": str(roadmap_id)}
            if facts:
                parent["resource_version"] = facts.roadmap_version
            at = timezone.now()
            decision = PolicyDecision.objects.create(
                workspace_id=workspace.id,
                sequence=_next_policy_sequence(
                    workspace_id=workspace.id, resource_type="ROADMAP", resource_id=roadmap_id
                ),
                action=ACTION,
                resource_type="ROADMAP",
                resource_id=roadmap_id,
                resource_version=parent.get("resource_version"),
                subject=actor,
                effective_principal=actor,
                effect="ALLOW" if reason == "ALLOW" else "DENY",
                reason_codes=[reason],
                policy_key=POLICY["policy_key"],
                policy_version=1,
                policy_manifest_digest=POLICY_DIGEST,
                input_digest="sha256:"
                + hashlib.sha256(
                    json.dumps(
                        {
                            "facts": asdict(facts) if facts else None,
                            "reason": reason,
                            "action": ACTION,
                            "request_digest": identity["request_digest"] if identity else None,
                            "materials": [dict(value) for value in captured.observations] if captured else [],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode()
                ).hexdigest(),
                normalized_classification="RESTRICTED",
                permitted_projection=["PREPARED_ITEM_SCOPE_REFERENCE"] if reason == "ALLOW" else [],
                correlation_id=correlation,
                evaluated_at=at,
                recorded_at=at,
                recorded_by=curve_policy_recorder(),
            )
            if reason != "ALLOW":
                _audit(decision, actor, correlation, parent, AuditOutcome.DENIED)
                error = CurvePolicyDenied(reason_codes=(reason,), decision_id=decision.id)
            elif error is not None:
                _audit(decision, actor, correlation, parent, AuditOutcome.NO_EFFECT)
            else:
                try:
                    with transaction.atomic():
                        record, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
                        if replay:
                            if retained is None or retained.id != record.id or captured is None:
                                raise ReplayResourceUnavailable
                            ref = prepared_scope_result(validate_retained_scope(record, payload=payload))
                            _audit(
                                decision,
                                actor,
                                correlation,
                                ref,
                                AuditOutcome.NO_EFFECT,
                                key=record.key_digest,
                                replay=True,
                            )
                            result = ItemScopeResult(ref, record.response_status, record.response_digest, True)
                        else:
                            if retained is not None:
                                raise ReplayResourceUnavailable
                            reference = prepare_scope_document(
                                resolver, context=facts.storage_context(), payload=payload
                            )
                            materials.enter_context(resolver.lease())
                            captured = _capture(resolver, facts, reference)
                            ref = prepared_scope_result(reference)
                            digest = operation_response_digest(response_status=201, resource_ref=ref)
                            event = DomainEvent.objects.create(
                                workspace_id=workspace.id,
                                event_type="curve.item_scope.prepared",
                                aggregate_type="PREPARED_ITEM_SCOPE",
                                aggregate_id=UUID(ref["resource_id"]),
                                aggregate_version=1,
                                sequence=1,
                                actor=actor,
                                effective_principal=actor,
                                correlation_id=correlation,
                                idempotency_key_digest=record.key_digest,
                                classification="RESTRICTED",
                                payload_schema="https://curve.example.invalid/contracts/candidates/item-scope-prepared-v1.schema.json",
                                payload={
                                    "schema_version": "1.0",
                                    "workspace_id": str(workspace.id),
                                    "product_id": str(product_id),
                                    "roadmap_id": str(roadmap_id),
                                    "result": ref,
                                },
                                occurred_at=timezone.now(),
                            )
                            OutboxEvent.objects.create(
                                workspace_id=workspace.id, event_id=event.id, destination="CURVE_ITEM_LOCAL_V1"
                            )
                            _audit(
                                decision,
                                actor,
                                correlation,
                                ref,
                                AuditOutcome.SUCCEEDED,
                                key=record.key_digest,
                                digest=digest,
                            )
                            record.state = IdempotencyState.COMPLETED
                            record.response_status, record.response_digest, record.response_resource_ref = (
                                201,
                                digest,
                                ref,
                            )
                            record.completed_at = timezone.now()
                            record.save(
                                update_fields=[
                                    "state",
                                    "response_status",
                                    "response_digest",
                                    "response_resource_ref",
                                    "completed_at",
                                ]
                            )
                            result = ItemScopeResult(ref, 201, digest, False)
                        resolver.revalidate(captured)
                except NO_EFFECT as caught:
                    _audit(decision, actor, correlation, parent, AuditOutcome.NO_EFFECT)
                    error = caught
    if error is not None:
        raise error
    return result
