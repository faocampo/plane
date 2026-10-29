# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Serialize cancellation with creation; completed Items are never deleted."""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder
from plane.curve.item_cancellation_events import build_item_cancellation_event
from plane.curve.item_cancellation_results import cancellation_identity, cancellation_reference, validate_cancellation
from plane.curve.item_creation_services import _retained_pair
from plane.curve.item_recovery_rules import recovery_read_reason
from plane.curve.item_scope_authority import resolve_item_scope_facts
from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    DomainEvent,
    Feature,
    IdempotencyRecord,
    Milestone,
    OutboxEvent,
    PolicyDecision,
)
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.services import _append_audit_event, operation_response_digest, ReplayResourceUnavailable
from plane.db.models import Workspace

_POLICY_BYTES = (Path(__file__).parent / "items/cancellation-policy-v1.json").read_bytes()
if hashlib.sha256(_POLICY_BYTES).hexdigest() != "4395e921a8579dd08d09cb847bd41803ecd54822a80c88d49962865007504c53":
    raise RuntimeError("ITEM_CANCELLATION_POLICY_CONTRACT_CHANGED")
POLICY = json.loads(_POLICY_BYTES)
POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)


def _record_cancellation(*, workspace_id, action, ref, actor, correlation, reason, facts, identity):
    at = timezone.now()
    document = {
        "action": action,
        "resource_ref": ref,
        "actor": actor,
        "reason": reason,
        "native_facts": asdict(facts) if facts else None,
        "command_identity": identity,
    }
    allowed = reason == "ALLOW"
    decision = PolicyDecision.objects.create(
        workspace_id=workspace_id,
        sequence=_next_policy_sequence(
            workspace_id=workspace_id, resource_type=ref["resource_type"], resource_id=UUID(ref["resource_id"])
        ),
        action=f"CURVE.ITEM.{action}",
        resource_type=ref["resource_type"],
        resource_id=ref["resource_id"],
        resource_version=ref.get("resource_version"),
        subject=actor,
        effective_principal=actor,
        effect="ALLOW" if allowed else "DENY",
        reason_codes=[reason],
        policy_key=POLICY["policy_key"],
        policy_version=1,
        policy_manifest_digest=POLICY_DIGEST,
        input_digest="sha256:"
        + hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
        normalized_classification=DataClassification.INTERNAL,
        permitted_projection=POLICY["projection"] if allowed else [],
        correlation_id=correlation,
        evaluated_at=at,
        recorded_at=at,
        recorded_by=curve_policy_recorder(),
    )
    return decision


def cancel_item_creation(*, request, workspace_slug, product_id, roadmap_id, command_key):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    try:
        product_id, roadmap_id = UUID(str(product_id)), UUID(str(roadmap_id))
    except (ValueError, TypeError, AttributeError):
        raise CurvePolicyResourceNotFound from None
    result = error = None
    with transaction.atomic(durable=True):
        from plane.curve.scope_reopening_qualification import require_item_cancellation_qualification

        require_item_cancellation_qualification()
        # Creation takes this same native workspace lock before reserving a key.
        # The winner commits its terminal result before the other can inspect it.
        workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
        if workspace is None:
            raise CurvePolicyResourceNotFound
        actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
        correlation = correlation_id_for_request(request)
        parent = {"resource_type": "ROADMAP", "resource_id": str(roadmap_id)}
        facts = identity = retained = None
        reason = "RESOURCE_UNAVAILABLE"
        try:
            identity = cancellation_identity(
                workspace_id=workspace.id,
                product_id=product_id,
                roadmap_id=roadmap_id,
                actor_id=user.id,
                command_key=command_key,
            )
            facts = resolve_item_scope_facts(
                workspace_slug=workspace_slug, product_id=product_id, roadmap_id=roadmap_id, actor_id=user.id
            )
            reason = recovery_read_reason(
                facts,
                enabled=getattr(settings, "CURVE_ITEM_CANCELLATION_ENABLED", False) is True,
                local=getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL",
            )
            if reason == "ALLOW":
                parent["resource_version"] = facts.roadmap_version
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
                if retained is not None:
                    result = {"state": "UNRESOLVED"}
                    if retained.state == "FAILED_TERMINAL":
                        result = validate_cancellation(retained, workspace_id=workspace.id, identity=identity)
                    elif retained.state == "COMPLETED":
                        item = _retained_pair(
                            SimpleNamespace(workspace_id=workspace.id, product_id=product_id, roadmap_id=roadmap_id),
                            retained,
                        )
                        live = {
                            "workspace_id": workspace.id,
                            "product_id": product_id,
                            "tombstoned_at__isnull": True,
                            "schema_version": "1.0",
                        }
                        if (
                            not Feature.objects.select_for_update(no_key=True)
                            .filter(**live, id=item.feature_id)
                            .exists()
                        ):
                            raise CurvePolicyResourceNotFound
                        if (
                            not Milestone.objects.select_for_update(no_key=True)
                            .filter(**live, id=item.milestone_id, roadmap_id=roadmap_id)
                            .exists()
                        ):
                            raise CurvePolicyResourceNotFound
                        result = {"state": "COMPLETED", "resource_ref": deepcopy(retained.response_resource_ref)}
        except (CurvePolicyResourceNotFound, ReplayResourceUnavailable):
            reason = "RESOURCE_UNAVAILABLE"
        decision = _record_cancellation(
            workspace_id=workspace.id,
            action="CANCEL_ITEM_CREATION_ATTEMPT",
            ref=parent,
            actor=actor,
            correlation=correlation,
            reason=reason,
            facts=facts,
            identity=identity,
        )
        target = parent
        outcome = AuditOutcome.NO_EFFECT
        if reason != "ALLOW":
            outcome = AuditOutcome.DENIED
            error = CurvePolicyDenied(reason_codes=(reason,), decision_id=decision.id)
        elif retained is None:
            # Reserve the original creation key, not a replacement command key.
            # The original creation service rejects this different request digest
            # before any Item, Initiative, protected document or event effects.
            at = timezone.now()
            retained = IdempotencyRecord.objects.create(
                id=uuid4(), workspace_id=workspace.id, **identity, expires_at=at + timedelta(days=1)
            )
            target = cancellation_reference(retained.id)
            retained.state = "FAILED_TERMINAL"
            retained.response_status = 409
            retained.response_resource_ref = target
            retained.response_digest = operation_response_digest(response_status=409, resource_ref=target)
            retained.completed_at = timezone.now()
            retained.save(
                update_fields=["state", "response_status", "response_resource_ref", "response_digest", "completed_at"]
            )
            event = DomainEvent.objects.create(
                workspace_id=workspace.id,
                event_type="curve.item_creation.cancelled",
                aggregate_type="ROADMAP_ITEM_CREATION_CANCELLATION",
                aggregate_id=retained.id,
                aggregate_version=1,
                sequence=1,
                actor=actor,
                effective_principal=actor,
                correlation_id=correlation,
                idempotency_key_digest=retained.key_digest,
                classification="INTERNAL",
                payload_schema="https://curve.example.invalid/contracts/candidates/item-creation-cancelled-v1.schema.json",
                payload=build_item_cancellation_event(
                    workspace_id=workspace.id, product_id=product_id, roadmap_id=roadmap_id, record_id=retained.id
                ),
                occurred_at=timezone.now(),
            )
            OutboxEvent.objects.create(workspace_id=workspace.id, event_id=event.id, destination="CURVE_ITEM_LOCAL_V1")
            result = validate_cancellation(retained, workspace_id=workspace.id, identity=identity)
            outcome = AuditOutcome.SUCCEEDED
        _append_audit_event(
            workspace_id=workspace.id,
            action="CURVE.ITEM.CANCEL_ITEM_CREATION_ATTEMPT",
            target_ref=target,
            outcome=outcome,
            actor=actor,
            effective_principal=actor,
            correlation_id=correlation,
            key_digest=identity["key_digest"] if identity else None,
            policy_decision_ref={
                "resource_type": "POLICY_DECISION",
                "resource_id": str(decision.id),
                "resource_version": 1,
            },
        )
    if error is not None:
        raise error
    return result
