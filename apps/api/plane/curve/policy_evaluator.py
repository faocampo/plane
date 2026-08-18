# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
from datetime import datetime, timezone
from typing import Mapping
import uuid

from plane.curve.policy_manifest import (
    CORE_POLICY_MANIFEST_DIGEST,
    load_core_policy_manifest,
)
from plane.curve.policy_types import (
    DataClassification,
    PolicyEffect,
    PolicyEvaluationResult,
)


_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "workspace_id",
        "subject",
        "effective_principal",
        "membership",
        "roles",
        "action",
        "resource",
        "classification",
        "environment",
        "feature_enabled",
        "object_acl",
        "assignment_context",
        "target_context",
        "service_authorization",
        "evaluated_at",
        "policy_manifest_digest",
        "correlation_id",
    }
)
_ACTOR_TYPES = frozenset({"HUMAN", "SERVICE", "AGENT", "SYSTEM"})
_HUMAN_ROLES = frozenset(
    {
        "WORKSPACE_MEMBER",
        "PRODUCT_APPROVER",
        "TECHNICAL_APPROVER",
        "CODE_APPROVER",
        "PLATFORM_ADMINISTRATOR",
    }
)
_INPUT_DIGEST_DOMAIN = b"curve-policy-input:v1\0"
_SEMANTIC_SET_PATHS = frozenset(
    {
        ("roles",),
        ("object_acl", "allow_principals"),
        ("object_acl", "deny_principals"),
        ("object_acl", "allow_roles"),
        ("object_acl", "deny_roles"),
        ("assignment_context", "gate_assignments"),
        ("assignment_context", "material_contributors"),
        ("target_context", "allowed_targets"),
        ("service_authorization", "allowed_actions"),
    }
)


def _normalize_canonical_json(value, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        return {key: _normalize_canonical_json(value[key], path + (key,)) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_normalize_canonical_json(item, path + ("[]",)) for item in value]
        if path in _SEMANTIC_SET_PATHS:
            normalized.sort(key=_canonical_json_bytes)
        return normalized
    return value


def _canonical_json_bytes(value) -> bytes:
    normalized = _normalize_canonical_json(value)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _input_digest(value: Mapping[str, object]) -> str:
    return f"sha256:{hashlib.sha256(_INPUT_DIGEST_DOMAIN + _canonical_json_bytes(value)).hexdigest()}"


def _actor(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"actor_type", "actor_id"}
        and value.get("actor_type") in _ACTOR_TYPES
        and isinstance(value.get("actor_id"), str)
        and bool(value["actor_id"])
    )


def _actor_key(value) -> tuple[str, str] | None:
    if not _actor(value):
        return None
    return value["actor_type"], value["actor_id"]


def _resource_ref(value) -> bool:
    if not isinstance(value, dict) or not {"resource_type", "resource_id"}.issubset(value):
        return False
    if not set(value).issubset({"resource_type", "resource_id", "resource_version"}):
        return False
    version = value.get("resource_version")
    return (
        isinstance(value["resource_type"], str)
        and bool(value["resource_type"])
        and isinstance(value["resource_id"], str)
        and bool(value["resource_id"])
        and (version is None or type(version) is int and version >= 1)
    )


def _utc_instant(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
        return None
    return instant


def _same_ref(left, right) -> bool:
    return _resource_ref(left) and _resource_ref(right) and left == right


def _principal_matches(entries, principal) -> bool:
    key = _actor_key(principal)
    return isinstance(entries, list) and key is not None and any(_actor_key(item) == key for item in entries)


def _roles_match(entries, roles: set[str]) -> bool:
    return isinstance(entries, list) and bool(roles.intersection(entries))


def _valid_context_shape(context: Mapping[str, object]) -> bool:
    if not isinstance(context, dict) or set(context) != _REQUIRED_FIELDS:
        return False
    if context.get("schema_version") != "1.0":
        return False
    if not isinstance(context.get("workspace_id"), str) or not context["workspace_id"]:
        return False
    try:
        uuid.UUID(context["workspace_id"])
    except (TypeError, ValueError):
        return False
    roles = context.get("roles")
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles) or len(roles) != len(set(roles)):
        return False
    if not isinstance(context.get("resource"), dict):
        return False
    resource = context["resource"]
    if set(resource) != {"workspace_id", "ref", "exists", "owner"}:
        return False
    if not _resource_ref(resource.get("ref")) or type(resource.get("exists")) is not bool:
        return False
    if resource.get("owner") is not None and not _actor(resource["owner"]):
        return False
    return (
        isinstance(context.get("action"), str)
        and context.get("classification")
        in {
            "INTERNAL",
            "CONFIDENTIAL",
            "RESTRICTED",
            "UNKNOWN",
        }
        and context.get("environment") in {"LOCAL", "STAGING", "PRODUCTION"}
        and type(context.get("feature_enabled")) is bool
        and _utc_instant(context.get("evaluated_at")) is not None
        and isinstance(context.get("correlation_id"), str)
        and bool(context["correlation_id"])
    )


def _acl_denial(action_policy, context, roles: set[str]) -> list[str]:
    mode = action_policy["object_acl"]
    acl = context["object_acl"]
    owner_allowed = bool(
        action_policy["owner_satisfies_acl"]
        and _actor_key(context["resource"].get("owner")) == _actor_key(context["effective_principal"])
    )
    if acl is None:
        return ["OBJECT_ACL_REQUIRED"] if mode == "REQUIRED" and not owner_allowed else []
    if not isinstance(acl, dict):
        return ["POLICY_CONTEXT_INVALID"]
    required = {
        "workspace_id",
        "resource_ref",
        "acl_version",
        "allow_principals",
        "deny_principals",
        "allow_roles",
        "deny_roles",
    }
    if (
        set(acl) != required
        or acl.get("workspace_id") != context["workspace_id"]
        or not _same_ref(acl.get("resource_ref"), context["resource"]["ref"])
        or type(acl.get("acl_version")) is not int
        or acl["acl_version"] < 1
    ):
        return ["POLICY_CONTEXT_INVALID"]
    denied = _principal_matches(acl["deny_principals"], context["effective_principal"]) or _roles_match(
        acl["deny_roles"], roles
    )
    if denied:
        return ["OBJECT_ACL_DENIED"]
    allowed = (
        owner_allowed
        or _principal_matches(acl["allow_principals"], context["effective_principal"])
        or _roles_match(acl["allow_roles"], roles)
    )
    if mode == "REQUIRED" and not allowed:
        return ["OBJECT_ACL_DENIED"]
    if mode == "OPTIONAL_NARROWING" and not allowed:
        return ["OBJECT_ACL_DENIED"]
    return []


def _assignment_denials(action_policy, context) -> list[str]:
    required_role = action_policy["assignment"]
    assignment = context["assignment_context"]
    if required_role == "NONE":
        return [] if assignment is None else ["POLICY_CONTEXT_INVALID"]
    if not isinstance(assignment, dict):
        return ["ASSIGNMENT_REQUIRED"]
    if (
        assignment.get("workspace_id") != context["workspace_id"]
        or not _same_ref(assignment.get("subject_ref"), context["resource"]["ref"])
        or type(assignment.get("assignment_version")) is not int
        or assignment["assignment_version"] < 1
    ):
        return ["POLICY_CONTEXT_INVALID"]
    matches = [
        item
        for item in assignment.get("gate_assignments", [])
        if isinstance(item, dict)
        and item.get("role") == required_role
        and item.get("active") is True
        and _actor_key(item.get("principal")) == _actor_key(context["effective_principal"])
        and item.get("principal", {}).get("actor_type") == "HUMAN"
    ]
    return [] if matches else ["ASSIGNMENT_MISMATCH"]


def _separation_denials(action_policy, context) -> list[str]:
    if action_policy["separation_of_duty"] == "NONE":
        return []
    assignment = context["assignment_context"]
    if not isinstance(assignment, dict):
        return ["SEPARATION_OF_DUTY_DENIED"]
    gates = assignment.get("gate_assignments")
    risk = assignment.get("risk_tier")
    if not isinstance(gates, list) or risk not in {"LOW", "STANDARD", "HIGH"}:
        return ["POLICY_CONTEXT_INVALID"]
    principals = [_actor_key(item.get("principal")) for item in gates if isinstance(item, dict) and item.get("active")]
    if any(item is None or item[0] != "HUMAN" for item in principals):
        return ["SEPARATION_OF_DUTY_DENIED"]
    duplicates = len(principals) != len(set(principals))
    if risk == "HIGH":
        roles = {item.get("role") for item in gates if isinstance(item, dict) and item.get("active")}
        contributors = {_actor_key(item) for item in assignment.get("material_contributors", [])}
        code_principals = {
            _actor_key(item.get("principal"))
            for item in gates
            if isinstance(item, dict) and item.get("role") == "CODE_APPROVER" and item.get("active")
        }
        if (
            roles != {"PRODUCT_APPROVER", "TECHNICAL_APPROVER", "CODE_APPROVER"}
            or duplicates
            or contributors & code_principals
        ):
            return ["SEPARATION_OF_DUTY_DENIED"]
    elif risk == "STANDARD" and duplicates and assignment.get("overlap_exception_ref") is None:
        return ["SEPARATION_OF_DUTY_DENIED"]
    elif risk == "LOW" and duplicates and assignment.get("low_risk_overlap_allowed") is not True:
        return ["SEPARATION_OF_DUTY_DENIED"]
    return []


def _target_denials(action_policy, context) -> list[str]:
    mode = action_policy["target_allowlist"]
    target = context["target_context"]
    if mode == "NOT_APPLICABLE":
        return [] if target is None else ["POLICY_CONTEXT_INVALID"]
    if target is None:
        return ["TARGET_ALLOWLIST_REQUIRED"] if mode == "REQUIRED" else []
    if not isinstance(target, dict) or target.get("workspace_id") != context["workspace_id"]:
        return ["POLICY_CONTEXT_INVALID"]
    configuration_ref = target.get("configuration_ref")
    allowed = target.get("allowed_targets")
    if not _resource_ref(configuration_ref) or configuration_ref.get("resource_version") is None:
        return ["POLICY_CONTEXT_INVALID"]
    if not isinstance(allowed, list):
        return ["POLICY_CONTEXT_INVALID"]
    if mode == "REQUIRED" and not allowed:
        return ["TARGET_ALLOWLIST_REQUIRED"]
    return [] if target.get("target_id") in allowed else ["TARGET_NOT_ALLOWED"]


def _service_denials(context, evaluated_at: datetime) -> list[str]:
    subject = context["subject"]
    authorization = context["service_authorization"]
    if subject.get("actor_type") != "SERVICE":
        return [] if authorization is None else ["POLICY_CONTEXT_INVALID"]
    if not isinstance(authorization, dict):
        return ["SERVICE_AUTHORIZATION_REQUIRED"]
    required = {
        "authorization_id",
        "authorization_version",
        "workspace_id",
        "service",
        "active",
        "allowed_actions",
        "issued_at",
        "expires_at",
    }
    if set(authorization) != required:
        return ["SERVICE_AUTHORIZATION_INVALID"]
    issued_at = _utc_instant(authorization.get("issued_at"))
    expires_at = _utc_instant(authorization.get("expires_at"))
    if (
        type(authorization.get("authorization_version")) is not int
        or authorization["authorization_version"] < 1
        or authorization.get("workspace_id") != context["workspace_id"]
        or _actor_key(authorization.get("service")) != _actor_key(subject)
        or context["action"] not in authorization.get("allowed_actions", [])
        or issued_at is None
        or expires_at is None
        or issued_at > evaluated_at
        or expires_at <= issued_at
    ):
        return ["SERVICE_AUTHORIZATION_INVALID"]
    if authorization.get("active") is not True:
        return ["SERVICE_AUTHORIZATION_INACTIVE"]
    if evaluated_at >= expires_at:
        return ["SERVICE_AUTHORIZATION_EXPIRED"]
    return []


def evaluate_core_policy(context: Mapping[str, object]) -> PolicyEvaluationResult:
    manifest = load_core_policy_manifest()
    try:
        digest = _input_digest(context)
    except (TypeError, ValueError):
        digest = f"sha256:{hashlib.sha256(_INPUT_DIGEST_DOMAIN + b'INVALID_JSON').hexdigest()}"
    evaluated_at = context.get("evaluated_at") if isinstance(context, dict) else ""
    classification = context.get("classification") if isinstance(context, dict) else "UNKNOWN"
    normalized = (
        DataClassification.RESTRICTED
        if classification == DataClassification.UNKNOWN.value
        else DataClassification(classification)
        if classification in {item.value for item in DataClassification if item is not DataClassification.UNKNOWN}
        else DataClassification.RESTRICTED
    )
    reasons: set[str] = set()

    valid_shape = _valid_context_shape(context)
    trusted_time = _utc_instant(evaluated_at)
    if not valid_shape or context.get("policy_manifest_digest") != CORE_POLICY_MANIFEST_DIGEST or trusted_time is None:
        return PolicyEvaluationResult(
            effect=PolicyEffect.DENY,
            reason_codes=("POLICY_CONTEXT_INVALID",),
            normalized_classification=normalized,
            permitted_projection=(),
            input_digest=digest,
            evaluated_at=str(evaluated_at),
            policy_key=manifest["policy_key"],
            policy_version=manifest["policy_version"],
            policy_manifest_digest=CORE_POLICY_MANIFEST_DIGEST,
        )

    if context.get("feature_enabled") is not True:
        reasons.add("FEATURE_DISABLED")

    subject = context.get("subject")
    principal = context.get("effective_principal")
    if not _actor(subject) or subject == {"actor_type": "SYSTEM", "actor_id": "anonymous"}:
        reasons.add("UNAUTHENTICATED")
    elif subject["actor_type"] == "AGENT":
        reasons.add("AGENT_NOT_ALLOWED")

    resource = context.get("resource") if isinstance(context.get("resource"), dict) else {}
    if resource.get("workspace_id") != context.get("workspace_id"):
        reasons.add("WORKSPACE_MISMATCH")

    membership = context.get("membership")
    roles = set(context.get("roles") if isinstance(context.get("roles"), list) else [])
    actor_type = subject.get("actor_type") if isinstance(subject, dict) else None
    if actor_type == "HUMAN":
        if (
            not isinstance(membership, dict)
            or membership.get("workspace_id") != context.get("workspace_id")
            or membership.get("active") is not True
        ):
            reasons.add("INACTIVE_MEMBERSHIP")
    elif membership is not None:
        reasons.add("POLICY_CONTEXT_INVALID")

    action_policy = next(
        (item for item in manifest["actions"] if item["action"] == context.get("action")),
        None,
    )
    if action_policy is None:
        reasons.add("UNKNOWN_ACTION")
    else:
        resource_ref = resource.get("ref") if isinstance(resource, dict) else {}
        if resource_ref.get("resource_type") not in action_policy["allowed_resource_types"]:
            reasons.add("RESOURCE_TYPE_NOT_ALLOWED")
        if resource.get("exists") is not True:
            reasons.add("RESOURCE_NOT_FOUND")
        if (
            not _actor(subject)
            or not _actor(principal)
            or subject != principal
            or subject["actor_type"] not in action_policy["allowed_actor_types"]
        ):
            reasons.add("UNSUPPORTED_PRINCIPAL")

        role_shape_valid = (
            actor_type == "HUMAN"
            and "TRUSTED_SERVICE" not in roles
            and roles.issubset(_HUMAN_ROLES)
            or actor_type == "SERVICE"
            and roles == {"TRUSTED_SERVICE"}
            or actor_type in {"AGENT", "SYSTEM"}
            and not roles
        )
        if not role_shape_valid or not roles.intersection(action_policy["allowed_roles"]):
            reasons.add("ROLE_NOT_ALLOWED")
        if context.get("environment") not in action_policy["allowed_environments"]:
            reasons.add("ENVIRONMENT_NOT_ALLOWED")
        if normalized.value not in action_policy["allowed_classifications"]:
            reasons.add("CLASSIFICATION_NOT_ALLOWED")
        reasons.update(_acl_denial(action_policy, context, roles))
        reasons.update(_assignment_denials(action_policy, context))
        reasons.update(_separation_denials(action_policy, context))
        reasons.update(_target_denials(action_policy, context))
        if trusted_time is not None:
            reasons.update(_service_denials(context, trusted_time))
        if action_policy["external_side_effect"]:
            reasons.add("EXTERNAL_EFFECT_NOT_ALLOWED")

    ordered = tuple(code for code in manifest["deny_precedence"] if code in reasons)
    if ordered:
        return PolicyEvaluationResult(
            effect=PolicyEffect.DENY,
            reason_codes=ordered,
            normalized_classification=normalized,
            permitted_projection=(),
            input_digest=digest,
            evaluated_at=str(evaluated_at),
            policy_key=manifest["policy_key"],
            policy_version=manifest["policy_version"],
            policy_manifest_digest=CORE_POLICY_MANIFEST_DIGEST,
        )

    return PolicyEvaluationResult(
        effect=PolicyEffect.ALLOW,
        reason_codes=(manifest["allow_reason_code"],),
        normalized_classification=normalized,
        permitted_projection=tuple(action_policy["permitted_projection"]),
        input_digest=digest,
        evaluated_at=str(evaluated_at),
        policy_key=manifest["policy_key"],
        policy_version=manifest["policy_version"],
        policy_manifest_digest=CORE_POLICY_MANIFEST_DIGEST,
    )
