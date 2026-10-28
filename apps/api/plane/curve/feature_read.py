# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Scoped Feature metadata reads; protected description refs require fresh access.

Lists contain only Product-visible Feature metadata, without object references.
Detail reads independently authorize a protected description before projecting it.
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from plane.curve.config import curve_policy_recorder
from plane.curve.feature_authority_facts import resolve_feature_facts
from plane.curve.feature_editor_rules import feature_editor_reason
from plane.curve.feature_input import FeatureInputError, normalize_feature_command
from plane.curve.feature_local_material import FeatureMaterialUnavailable, LocalFeatureMaterialResolver
from plane.curve.feature_material import FeatureMaterialError, description_requirements
from plane.curve.feature_policy import POLICY, POLICY_DIGEST
from plane.curve.models import AuditOutcome, DataClassification, Feature, PolicyDecision
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    correlation_id_for_request,
    _next_policy_sequence,
)
from plane.curve.services import _append_audit_event
from plane.db.models import Workspace


def _read_reason(facts):
    if not facts.feature_enabled:
        return "FEATURE_DISABLED"
    if not facts.actor_active_human or not facts.actor_active_member:
        return "ACTIVE_HUMAN_MEMBERSHIP_REQUIRED"
    if not facts.product_active:
        return "PRODUCT_UNAVAILABLE"
    if not facts.product_format_supported:
        return "PRODUCT_FORMAT_UNAVAILABLE"
    return "ALLOW"


def _record_read(*, workspace_id, action, ref, actor, correlation, reason, facts, captured, classification):
    at = timezone.now()
    document = {
        "action": action,
        "resource_ref": ref,
        "actor": actor,
        "reason": reason,
        "native_facts": asdict(facts) if facts else None,
        "material_catalog_generation": captured.catalog_generation if captured else None,
        "materials": [dict(value) for value in captured.observations] if captured else [],
    }
    allowed = reason == "ALLOW"
    decision = PolicyDecision.objects.create(
        workspace_id=workspace_id,
        sequence=_next_policy_sequence(
            workspace_id=workspace_id, resource_type=ref["resource_type"], resource_id=UUID(ref["resource_id"])
        ),
        action=f"CURVE.FEATURE.{action}",
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
        normalized_classification=classification,
        permitted_projection=(
            ["FEATURE_METADATA"] + (["FEATURE_DESCRIPTION_REFERENCE"] if captured else []) if allowed else []
        ),
        correlation_id=correlation,
        evaluated_at=at,
        recorded_at=at,
        recorded_by=curve_policy_recorder(),
    )
    _append_audit_event(
        workspace_id=workspace_id,
        action=f"CURVE.FEATURE.{action}",
        target_ref=ref,
        outcome=AuditOutcome.SUCCEEDED if allowed else AuditOutcome.DENIED,
        actor=actor,
        effective_principal=actor,
        correlation_id=correlation,
        policy_decision_ref={
            "resource_type": "POLICY_DECISION",
            "resource_id": str(decision.id),
            "resource_version": 1,
        },
    )
    return decision


def _metadata(row):
    return {
        "id": str(row.id),
        "version": row.version,
        "name": row.name,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def read_features(*, request, workspace_slug, product_id, feature_id=None, page_size=50, after=None):
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("invalid page size")
    try:
        product_id = UUID(str(product_id))
        feature_id = UUID(str(feature_id)) if feature_id is not None else None
        after = UUID(str(after)) if after is not None else None
    except (ValueError, TypeError, AttributeError) as error:
        raise CurvePolicyResourceNotFound from error
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise CurvePolicyResourceNotFound
    actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
    correlation = correlation_id_for_request(request)
    action = "READ_FEATURE" if feature_id else "LIST_FEATURES"
    ref = {"resource_type": "FEATURE" if feature_id else "PRODUCT", "resource_id": str(feature_id or product_id)}
    result = error = None
    with ExitStack() as materials:
        with transaction.atomic(durable=True):
            from plane.curve.scope_reopening_qualification import require_feature_command_qualification

            require_feature_command_qualification()
            workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
            if workspace is None:
                raise CurvePolicyResourceNotFound
            facts = captured = None
            classification = DataClassification.INTERNAL
            reason = "RESOURCE_UNAVAILABLE"
            try:
                facts = resolve_feature_facts(workspace_slug=workspace_slug, product_id=product_id, actor_id=user.id)
                reason = _read_reason(facts)
            except CurvePolicyResourceNotFound:
                pass
            if reason == "ALLOW" and getattr(settings, "CURVE_ENVIRONMENT", None) != "LOCAL":
                reason = "LOCAL_FEATURE_PROFILE_REQUIRED"
            if reason == "ALLOW":
                query = (
                    Feature.objects.select_for_update(no_key=True)
                    .filter(
                        workspace_id=workspace.id,
                        product_id=product_id,
                        tombstoned_at__isnull=True,
                    )
                    .order_by("id")
                )
                if feature_id:
                    row = query.filter(id=feature_id).first()
                    if row is None or row.schema_version != "1.0":
                        reason = "RESOURCE_UNAVAILABLE"
                    else:
                        ref["resource_version"] = row.version
                        result = _metadata(row)
                        result["description"] = deepcopy(row.description)
                        result["can_edit"] = feature_editor_reason("UPDATE_FEATURE", facts) == "ALLOW"
                        if row.description is not None:
                            classification = DataClassification.RESTRICTED
                            try:
                                command = normalize_feature_command(
                                    "CREATE_FEATURE", {"name": row.name, "description": row.description}, None
                                )
                                requirements = description_requirements(command, retained_description=None)
                                resolver = materials.enter_context(LocalFeatureMaterialResolver.from_settings())
                                materials.enter_context(resolver.lease())
                                captured = resolver.capture(
                                    workspace_id=workspace.id,
                                    product_id=product_id,
                                    actor_id=user.id,
                                    membership_id=facts.membership_id,
                                    membership_generation=facts.membership_generation,
                                    requirements=requirements,
                                )
                                classification = captured.observations[0]["classification"]
                                resolver.revalidate(captured)
                            except (FeatureMaterialUnavailable, FeatureInputError, FeatureMaterialError):
                                reason = "PROTECTED_MATERIAL_UNAVAILABLE"
                                result = None
                else:
                    if after is not None:
                        query = query.filter(id__gt=after)
                    rows = list(query[: page_size + 1])
                    if any(row.schema_version != "1.0" for row in rows):
                        reason = "RESOURCE_UNAVAILABLE"
                    else:
                        result = {
                            "results": [_metadata(row) for row in rows[:page_size]],
                            "next_cursor": str(rows[page_size - 1].id) if len(rows) > page_size else None,
                            "is_editor": feature_editor_reason("CREATE_FEATURE", facts) == "ALLOW",
                        }
            decision = _record_read(
                workspace_id=workspace.id,
                action=action,
                ref=ref,
                actor=actor,
                correlation=correlation,
                reason=reason,
                facts=facts,
                captured=captured,
                classification=classification,
            )
            if reason != "ALLOW":
                error = CurvePolicyDenied(reason_codes=(reason,), decision_id=decision.id)
    if error is not None:
        raise error
    return result
