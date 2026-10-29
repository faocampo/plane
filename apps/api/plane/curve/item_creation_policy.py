# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Native ItemCreation command policy candidate; additive qualification is required."""

from contextlib import ExitStack
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder
from plane.curve.item_creation_facts import resolve_item_creation_facts
from plane.curve.item_creation_rules import item_creation_authority_reason
from plane.curve.item_creation_input import ItemCreationInputError
from plane.curve.item_local_material import ItemMaterialUnavailable, LocalItemMaterialResolver
from plane.curve.item_creation_material import scope_requirements
from plane.curve.models import AuditEvent, AuditOutcome, DataClassification, PolicyDecision
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.services import _append_audit_event
from plane.db.models import Workspace


_POLICY_BYTES = (Path(__file__).parent / "items/creation-policy-v1.json").read_bytes()
if hashlib.sha256(_POLICY_BYTES).hexdigest() != "9a1975106794892d3c975b45b6e2d7ef6ed917975c59346c43eee2cac88d54e7":
    raise RuntimeError("ITEM_CREATION_POLICY_CONTRACT_CHANGED")
POLICY = json.loads(_POLICY_BYTES)
POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
)
_ACTIVE = ContextVar("curve_item_creation_command_receipt", default=None)
_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ItemCreationReceipt:
    decision_id: UUID
    workspace_id: UUID
    product_id: UUID
    action: str
    roadmap_id: UUID
    roadmap_owner_id: UUID
    roadmap_version: int
    actor: object
    correlation_id: str
    resource_ref: object
    classification: str
    _token: object


def assert_receipt(receipt):
    if (
        not isinstance(receipt, ItemCreationReceipt)
        or receipt._token is not _TOKEN
        or _ACTIVE.get() is not receipt
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("an active ItemCreation command receipt is required")


def append_audit(receipt, *, target_ref, outcome, key_digest=None, after_digest=None, replay=False):
    assert_receipt(receipt)
    return _append_audit_event(
        workspace_id=receipt.workspace_id,
        action=f"CURVE.ITEM.{receipt.action}" + (".IDEMPOTENT_REPLAY" if replay else ""),
        target_ref=target_ref,
        outcome=outcome,
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        key_digest=key_digest,
        after_digest=after_digest,
        policy_decision_ref={
            "resource_type": "POLICY_DECISION",
            "resource_id": str(receipt.decision_id),
            "resource_version": 1,
        },
    )


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error


def execute_item_creation_mutation(
    *, request, workspace_slug, product_id, roadmap_id, command, prepare, callback, no_effect_exceptions
):
    """Prepare reads before the decision; mutate only inside its active receipt.

    The preparation callback receives locked native facts and may only read. Its
    current target supplies the retained scope, including creation replay.
    The material ExitStack outlives the database transaction and its commit.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    product_id = _uuid(product_id)
    roadmap_id = _uuid(roadmap_id)
    actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
    correlation = correlation_id_for_request(request)
    error = result = None
    with ExitStack() as materials:
        with transaction.atomic(durable=True):
            # Installed only by the additive command qualification successor.
            from plane.curve.scope_reopening_qualification import require_item_creation_qualification

            require_item_creation_qualification()
            workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
            if workspace is None:
                raise CurvePolicyResourceNotFound
            facts = prepared = captured = resolver = None
            reason = "RESOURCE_UNAVAILABLE"
            try:
                facts = resolve_item_creation_facts(
                    workspace_slug=workspace_slug,
                    product_id=product_id,
                    roadmap_id=roadmap_id,
                    actor_id=user.id,
                    command=command,
                )
                reason = item_creation_authority_reason(command, facts)
            except CurvePolicyResourceNotFound:
                pass
            if reason == "ALLOW" and getattr(settings, "CURVE_ENVIRONMENT", None) != "LOCAL":
                reason = "LOCAL_ITEM_CREATION_PROFILE_REQUIRED"
            if reason == "ALLOW":
                try:
                    prepared = prepare(facts)
                except CurvePolicyResourceNotFound:
                    reason = "RESOURCE_UNAVAILABLE"
                except no_effect_exceptions as caught:
                    error = caught
            classification = DataClassification.INTERNAL
            if reason == "ALLOW" and error is None:
                try:
                    requirements = scope_requirements(
                        command, retained_scope=prepared.item.scope_body if prepared.item else None
                    )
                except ItemCreationInputError as caught:
                    requirements = ()
                    error = caught
                if requirements:
                    classification = DataClassification.RESTRICTED
                    try:
                        resolver = materials.enter_context(LocalItemMaterialResolver.from_settings())
                        materials.enter_context(resolver.lease())
                        captured = resolver.capture(
                            workspace_id=workspace.id,
                            product_id=product_id,
                            roadmap_id=roadmap_id,
                            actor_id=user.id,
                            membership_id=facts.actor.membership_id,
                            membership_generation=facts.actor_membership_generation,
                            requirements=requirements,
                        )
                        rank = {value: index for index, value in enumerate(DataClassification.values)}
                        classification = max(
                            (entry["classification"] for entry in captured.observations), key=rank.__getitem__
                        )
                    except ItemMaterialUnavailable:
                        reason = "PROTECTED_MATERIAL_UNAVAILABLE"
            ref = {"resource_type": "ROADMAP", "resource_id": str(roadmap_id)}
            if facts is not None:
                ref["resource_version"] = facts.roadmap_version
            decision_input = {
                "workspace_id": str(workspace.id),
                "product_id": str(product_id),
                "roadmap_id": str(roadmap_id),
                "action": "CREATE_ROADMAP_ITEM_INITIATIVE",
                "actor": actor,
                "resource_ref": ref,
                "reason": reason,
                "native_facts": asdict(facts) if facts is not None else None,
                "membership_id": str(facts.actor.membership_id)
                if facts is not None and facts.actor.membership_id
                else None,
                "membership_generation": facts.actor_membership_generation if facts is not None else None,
                "material_catalog_generation": captured.catalog_generation if captured else None,
                "materials": [dict(entry) for entry in captured.observations] if captured else [],
            }
            at = timezone.now()
            decision = PolicyDecision.objects.create(
                workspace_id=workspace.id,
                sequence=_next_policy_sequence(
                    workspace_id=workspace.id, resource_type=ref["resource_type"], resource_id=UUID(ref["resource_id"])
                ),
                action="CURVE.ITEM.CREATE_ROADMAP_ITEM_INITIATIVE",
                resource_type=ref["resource_type"],
                resource_id=ref["resource_id"],
                resource_version=ref.get("resource_version"),
                subject=actor,
                effective_principal=actor,
                effect="ALLOW" if reason == "ALLOW" else "DENY",
                reason_codes=[reason],
                policy_key=POLICY["policy_key"],
                policy_version=1,
                policy_manifest_digest=POLICY_DIGEST,
                input_digest="sha256:"
                + hashlib.sha256(
                    json.dumps(decision_input, sort_keys=True, separators=(",", ":"), default=str).encode()
                ).hexdigest(),
                normalized_classification=classification,
                permitted_projection=["ROADMAP_ITEM_CREATION_RESULT"] if reason == "ALLOW" else [],
                correlation_id=correlation,
                evaluated_at=at,
                recorded_at=at,
                recorded_by=curve_policy_recorder(),
            )
            receipt = ItemCreationReceipt(
                decision.id,
                workspace.id,
                product_id,
                "CREATE_ROADMAP_ITEM_INITIATIVE",
                roadmap_id,
                facts.roadmap_owner_id if facts else None,
                facts.roadmap_version if facts else None,
                MappingProxyType(actor),
                correlation,
                MappingProxyType(ref),
                classification,
                _TOKEN,
            )
            token = _ACTIVE.set(receipt)
            try:
                if reason != "ALLOW":
                    append_audit(receipt, target_ref=ref, outcome=AuditOutcome.DENIED)
                    error = CurvePolicyDenied(reason_codes=(reason,), decision_id=decision.id)
                elif error is not None:
                    append_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT)
                else:
                    try:
                        with transaction.atomic():
                            result = callback(receipt, prepared)
                            if captured is not None:
                                resolver.revalidate(captured)
                    except no_effect_exceptions + (ItemMaterialUnavailable,) as caught:
                        append_audit(receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT)
                        error = caught
                if (
                    AuditEvent.objects.filter(
                        workspace_id=workspace.id, policy_decision_ref__resource_id=str(decision.id)
                    ).count()
                    != 1
                ):
                    raise RuntimeError("ItemCreation command requires exactly one linked audit")
            finally:
                _ACTIVE.reset(token)
    if error is not None:
        raise error
    return result
