# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Callable, Mapping
import uuid

from django.db import transaction
from django.utils import timezone

from plane.curve.config import (
    CurvePolicyConfigurationError,
    curve_environment,
    curve_policy_recorder,
    is_curve_enabled_for_workspace,
)
from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DataClassification,
    Operation,
    PolicyDecision,
)
from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_manifest import CORE_POLICY_MANIFEST_DIGEST
from plane.curve.policy_types import PolicyEffect, PolicyEvaluationResult
from plane.db.models import Workspace, WorkspaceMember


_PLANE_ROLE_NAMES = {20: "ADMIN", 15: "MEMBER", 5: "GUEST"}
_QUERY_CACHE_ATTRIBUTE = "_curve_policy_query_cache"
_CORRELATION_ATTRIBUTE = "_curve_policy_correlation_id"
_ACTIVE_MUTATION_RECEIPT: ContextVar[object | None] = ContextVar("curve_active_mutation_receipt", default=None)
_RECEIPT_CONSTRUCTOR_TOKEN = object()
_UNRESOLVED_CONTEXT = object()


class CurvePolicyDenied(PermissionError):
    def __init__(self, *, reason_codes: tuple[str, ...], decision_id: uuid.UUID):
        super().__init__("Curve policy denied the requested action")
        self.reason_codes = reason_codes
        self.decision_id = decision_id


class CurvePolicyResourceNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class QueryAuthorizationReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    resource_ref: Mapping[str, object]
    permitted_projection: tuple[str, ...]
    projection: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AuthorizedPolicyReceipt:
    decision_id: uuid.UUID
    action: str
    workspace_id: uuid.UUID
    resource_ref: Mapping[str, object]
    effect: PolicyEffect
    permitted_projection: tuple[str, ...]
    policy_manifest_digest: str
    policy_version: int
    evaluated_at: str
    _constructor_token: object


@dataclass(frozen=True, slots=True)
class _CachedQueryResult:
    receipt: QueryAuthorizationReceipt | None
    denial: CurvePolicyDenied | None


def _correlation_id(request) -> str:
    value = getattr(request, _CORRELATION_ATTRIBUTE, None)
    if value is None:
        value = f"curve-{uuid.uuid4()}"
        setattr(request, _CORRELATION_ATTRIBUTE, value)
    return value


def correlation_id_for_request(request) -> str:
    """Return the request-scoped safe correlation identifier."""

    return _correlation_id(request)


def _human_actor(user) -> dict[str, str]:
    if user is None or not getattr(user, "is_authenticated", False):
        return {"actor_type": "SYSTEM", "actor_id": "anonymous"}
    return {"actor_type": "HUMAN", "actor_id": str(user.id)}


def _valid_actor(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"actor_type", "actor_id"}
        and value.get("actor_type") in {"HUMAN", "SERVICE", "AGENT", "SYSTEM"}
        and isinstance(value.get("actor_id"), str)
        and bool(value["actor_id"])
    )


def _trusted_environment() -> str:
    try:
        return curve_environment()
    except CurvePolicyConfigurationError:
        return ""


def _workspace_membership(*, workspace_id: uuid.UUID, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None, []
    membership = (
        WorkspaceMember.objects.filter(
            workspace_id=workspace_id,
            member_id=user.id,
            is_active=True,
        )
        .only("workspace_id", "role", "is_active")
        .first()
    )
    if membership is None:
        return None, []
    return (
        {
            "workspace_id": str(workspace_id),
            "active": True,
            "plane_role": _PLANE_ROLE_NAMES.get(membership.role),
        },
        ["WORKSPACE_MEMBER"],
    )


def _workspace_resource(workspace: Workspace):
    owner = {"actor_type": "HUMAN", "actor_id": str(workspace.owner_id)}
    resource_ref = {
        "resource_type": "WORKSPACE",
        "resource_id": str(workspace.id),
        "resource_version": 1,
    }
    return {
        "workspace_id": str(workspace.id),
        "ref": resource_ref,
        "exists": True,
        "owner": owner,
    }


def _operation_resource(*, workspace: Workspace, resource_id):
    try:
        operation_id = uuid.UUID(str(resource_id))
    except (TypeError, ValueError) as error:
        raise CurvePolicyResourceNotFound from error
    operation = (
        Operation.objects.filter(workspace_id=workspace.id, id=operation_id)
        .only(
            "id",
            "workspace_id",
            "aggregate_version",
            "created_by",
        )
        .first()
    )
    if operation is None:
        return {
            "workspace_id": str(workspace.id),
            "ref": {
                "resource_type": "OPERATION",
                "resource_id": str(operation_id),
            },
            "exists": False,
            "owner": None,
        }
    owner = (
        operation.created_by
        if _valid_actor(operation.created_by)
        else {
            "actor_type": "INVALID",
            "actor_id": "",
        }
    )
    return {
        "workspace_id": str(workspace.id),
        "ref": {
            "resource_type": "OPERATION",
            "resource_id": str(operation.id),
            "resource_version": operation.aggregate_version,
        },
        "exists": True,
        "owner": owner,
    }


def _resolve_resource(*, workspace: Workspace, resource_type: str, resource_id):
    if resource_type == "WORKSPACE":
        if resource_id is not None and str(resource_id) != str(workspace.id):
            raise CurvePolicyResourceNotFound
        return _workspace_resource(workspace)
    if resource_type == "OPERATION":
        return _operation_resource(workspace=workspace, resource_id=resource_id)
    requested_id = resource_id or workspace.id
    return {
        "workspace_id": str(workspace.id),
        "ref": {
            "resource_type": resource_type,
            "resource_id": str(requested_id),
        },
        "exists": False,
        "owner": None,
    }


def _unresolved_resource(*, workspace: Workspace, resource_type: str, resource_id):
    if resource_type == "WORKSPACE":
        return _workspace_resource(workspace)
    requested_id = resource_id or workspace.id
    try:
        requested_id = uuid.UUID(str(requested_id))
    except (TypeError, ValueError) as error:
        raise CurvePolicyResourceNotFound from error
    return {
        "workspace_id": str(workspace.id),
        "ref": {
            "resource_type": resource_type,
            "resource_id": str(requested_id),
        },
        "exists": False,
        "owner": None,
    }


def _load_permitted_projection(*, workspace: Workspace, resource_ref: Mapping[str, object], permitted_projection):
    resource_type = resource_ref["resource_type"]
    if resource_type == "WORKSPACE":
        if tuple(permitted_projection) != ("WORKSPACE_ID", "WORKSPACE_SLUG", "SHELL_STATE"):
            raise PermissionError("unsupported Curve workspace projection")
        return MappingProxyType(
            {
                "workspace_id": str(workspace.id),
                "workspace_slug": workspace.slug,
                "state": "EMPTY",
            }
        )
    if resource_type == "OPERATION":
        if tuple(permitted_projection) != ("OPERATION_SAFE_METADATA",):
            raise PermissionError("unsupported Curve Operation projection")
        operation = (
            Operation.objects.filter(
                workspace_id=workspace.id,
                id=resource_ref["resource_id"],
                aggregate_version=resource_ref.get("resource_version"),
            )
            .only(
                "id",
                "workspace_id",
                "operation_type",
                "aggregate_version",
                "status",
                "progress_percent",
            )
            .first()
        )
        if operation is None:
            raise CurvePolicyResourceNotFound
        return MappingProxyType(
            {
                "schema_version": "1.0",
                "id": str(operation.id),
                "workspace_id": str(operation.workspace_id),
                "operation_type": operation.operation_type,
                "status": operation.status,
                "version": operation.aggregate_version,
                **({"progress_percent": operation.progress_percent} if operation.progress_percent is not None else {}),
            }
        )
    raise CurvePolicyResourceNotFound


def _build_query_context(
    *,
    workspace: Workspace,
    user,
    action: str,
    resource: dict,
    correlation_id: str,
    membership=_UNRESOLVED_CONTEXT,
    roles=_UNRESOLVED_CONTEXT,
    environment=_UNRESOLVED_CONTEXT,
    feature_enabled=_UNRESOLVED_CONTEXT,
):
    subject = _human_actor(user)
    if membership is _UNRESOLVED_CONTEXT or roles is _UNRESOLVED_CONTEXT:
        membership, roles = _workspace_membership(
            workspace_id=workspace.id,
            user=user,
        )
    if environment is _UNRESOLVED_CONTEXT:
        environment = _trusted_environment()
    if feature_enabled is _UNRESOLVED_CONTEXT:
        feature_enabled = is_curve_enabled_for_workspace(workspace.slug)
    return {
        "schema_version": "1.0",
        "workspace_id": str(workspace.id),
        "subject": subject,
        "effective_principal": dict(subject),
        "membership": membership,
        "roles": roles,
        "action": action,
        "resource": resource,
        "classification": DataClassification.INTERNAL,
        "environment": environment,
        "feature_enabled": feature_enabled,
        "object_acl": None,
        "assignment_context": None,
        "target_context": None,
        "service_authorization": None,
        "evaluated_at": timezone.now().isoformat().replace("+00:00", "Z"),
        "policy_manifest_digest": CORE_POLICY_MANIFEST_DIGEST,
        "correlation_id": correlation_id,
    }


def _next_policy_sequence(*, workspace_id, resource_type, resource_id) -> int:
    from plane.curve.services import _lock_audit_sequence

    _lock_audit_sequence(workspace_id, resource_type, resource_id)
    previous = (
        PolicyDecision.objects.filter(
            workspace_id=workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    return (previous or 0) + 1


def _record_policy_decision(
    *,
    context: dict,
    result: PolicyEvaluationResult,
) -> PolicyDecision:
    resource_ref = context["resource"]["ref"]
    workspace_id = uuid.UUID(context["workspace_id"])
    resource_id = uuid.UUID(resource_ref["resource_id"])
    recorded_by = curve_policy_recorder()
    evaluated_at = datetime.fromisoformat(result.evaluated_at.replace("Z", "+00:00"))
    return PolicyDecision.objects.create(
        workspace_id=workspace_id,
        sequence=_next_policy_sequence(
            workspace_id=workspace_id,
            resource_type=resource_ref["resource_type"],
            resource_id=resource_id,
        ),
        action=context["action"],
        resource_type=resource_ref["resource_type"],
        resource_id=resource_id,
        resource_version=resource_ref.get("resource_version"),
        subject=context["subject"],
        effective_principal=context["effective_principal"],
        effect=result.effect.value,
        reason_codes=list(result.reason_codes),
        policy_key=result.policy_key,
        policy_version=result.policy_version,
        policy_manifest_digest=result.policy_manifest_digest,
        input_digest=result.input_digest,
        normalized_classification=result.normalized_classification.value,
        permitted_projection=list(result.permitted_projection),
        correlation_id=context["correlation_id"],
        evaluated_at=evaluated_at,
        recorded_by=recorded_by,
    )


def _decision_ref(decision_id: uuid.UUID) -> dict[str, object]:
    return {
        "resource_type": "POLICY_DECISION",
        "resource_id": str(decision_id),
        "resource_version": 1,
    }


def _append_policy_audit(*, context, result, decision, outcome=None):
    from plane.curve.services import _append_audit_event

    return _append_audit_event(
        workspace_id=uuid.UUID(context["workspace_id"]),
        action=context["action"],
        target_ref=context["resource"]["ref"],
        outcome=outcome or (AuditOutcome.ALLOWED if result.effect is PolicyEffect.ALLOW else AuditOutcome.DENIED),
        actor=context["subject"],
        effective_principal=context["effective_principal"],
        correlation_id=context["correlation_id"],
        policy_decision_ref=_decision_ref(decision.id),
    )


def _record_query_evidence(*, context, result):
    with transaction.atomic():
        decision = _record_policy_decision(context=context, result=result)
        _append_policy_audit(context=context, result=result, decision=decision)
    return decision


def authorize_query(
    *,
    request,
    action: str,
    workspace_slug: str,
    resource_type: str,
    resource_id=None,
) -> QueryAuthorizationReceipt:
    try:
        workspace = Workspace.objects.only("id", "slug", "owner_id").get(slug=workspace_slug)
    except Workspace.DoesNotExist as error:
        raise CurvePolicyResourceNotFound from error

    membership, roles = _workspace_membership(workspace_id=workspace.id, user=request.user)
    environment = _trusted_environment()
    feature_enabled = is_curve_enabled_for_workspace(workspace.slug)
    may_load_child_metadata = bool(membership and feature_enabled and environment)
    resource = (
        _resolve_resource(
            workspace=workspace,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if resource_type == "WORKSPACE" or may_load_child_metadata
        else _unresolved_resource(
            workspace=workspace,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )
    resource_ref = resource["ref"]
    cache_key = (
        action,
        workspace.id,
        resource_ref["resource_type"],
        resource_ref["resource_id"],
        resource_ref.get("resource_version"),
    )
    cache = getattr(request, _QUERY_CACHE_ATTRIBUTE, None)
    if cache is None:
        cache = {}
        setattr(request, _QUERY_CACHE_ATTRIBUTE, cache)
    cached = cache.get(cache_key)
    if cached is not None:
        if cached.denial is not None:
            raise cached.denial
        return cached.receipt

    context = _build_query_context(
        workspace=workspace,
        user=request.user,
        action=action,
        resource=resource,
        correlation_id=_correlation_id(request),
        membership=membership,
        roles=roles,
        environment=environment,
        feature_enabled=feature_enabled,
    )
    result = evaluate_core_policy(context)
    decision = _record_query_evidence(context=context, result=result)
    if result.effect is not PolicyEffect.ALLOW:
        denial = CurvePolicyDenied(
            reason_codes=result.reason_codes,
            decision_id=decision.id,
        )
        cache[cache_key] = _CachedQueryResult(receipt=None, denial=denial)
        raise denial

    projection = _load_permitted_projection(
        workspace=workspace,
        resource_ref=resource_ref,
        permitted_projection=result.permitted_projection,
    )
    receipt = QueryAuthorizationReceipt(
        decision_id=decision.id,
        action=action,
        workspace_id=workspace.id,
        resource_ref=MappingProxyType(dict(resource_ref)),
        permitted_projection=result.permitted_projection,
        projection=projection,
    )
    cache[cache_key] = _CachedQueryResult(receipt=receipt, denial=None)
    return receipt


def _new_authorized_receipt(*, decision, result, context):
    return AuthorizedPolicyReceipt(
        decision_id=decision.id,
        action=context["action"],
        workspace_id=decision.workspace_id,
        resource_ref=MappingProxyType(dict(context["resource"]["ref"])),
        effect=result.effect,
        permitted_projection=result.permitted_projection,
        policy_manifest_digest=result.policy_manifest_digest,
        policy_version=result.policy_version,
        evaluated_at=result.evaluated_at,
        _constructor_token=_RECEIPT_CONSTRUCTOR_TOKEN,
    )


def assert_active_mutation_receipt(
    receipt,
    *,
    action: str,
    workspace_id: uuid.UUID,
    resource_ref: dict,
):
    if (
        not isinstance(receipt, AuthorizedPolicyReceipt)
        or receipt._constructor_token is not _RECEIPT_CONSTRUCTOR_TOKEN
        or _ACTIVE_MUTATION_RECEIPT.get() is not receipt
        or receipt.effect is not PolicyEffect.ALLOW
        or receipt.action != action
        or receipt.workspace_id != workspace_id
        or dict(receipt.resource_ref) != resource_ref
        or receipt.policy_manifest_digest != CORE_POLICY_MANIFEST_DIGEST
        or receipt.policy_version != 1
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("an active Curve mutation authorization receipt is required")


def policy_decision_ref_for_receipt(receipt) -> dict[str, object]:
    if _ACTIVE_MUTATION_RECEIPT.get() is not receipt:
        raise PermissionError("the Curve mutation authorization receipt is inactive")
    return _decision_ref(receipt.decision_id)


def _assert_one_mutation_audit(decision_id: uuid.UUID):
    if (
        AuditEvent.objects.filter(
            policy_decision_ref__resource_type="POLICY_DECISION",
            policy_decision_ref__resource_id=str(decision_id),
            policy_decision_ref__resource_version=1,
        ).count()
        != 1
    ):
        raise RuntimeError("authorized Curve mutation must append exactly one linked audit event")


def execute_authorized_mutation(
    *,
    context_builder: Callable[[], dict],
    mutation_callback: Callable[[AuthorizedPolicyReceipt], object],
    no_effect_exceptions: tuple[type[Exception], ...] = (),
):
    """Evaluate, persist, mutate, and audit in one policy-owned transaction."""

    pending_error = None
    mutation_result = None
    with transaction.atomic():
        context = context_builder()
        result = evaluate_core_policy(context)
        decision = _record_policy_decision(context=context, result=result)
        if result.effect is not PolicyEffect.ALLOW:
            _append_policy_audit(context=context, result=result, decision=decision)
            pending_error = CurvePolicyDenied(
                reason_codes=result.reason_codes,
                decision_id=decision.id,
            )
        else:
            receipt = _new_authorized_receipt(
                decision=decision,
                result=result,
                context=context,
            )
            token = _ACTIVE_MUTATION_RECEIPT.set(receipt)
            try:
                mutation_result = mutation_callback(receipt)
            except no_effect_exceptions as error:
                pending_error = error
            finally:
                _ACTIVE_MUTATION_RECEIPT.reset(token)
            _assert_one_mutation_audit(decision.id)

    if pending_error is not None:
        raise pending_error
    return mutation_result


def start_foundation_probe(
    *,
    request,
    workspace_slug: str,
    raw_idempotency_key: str,
    canonical_request: bytes,
    command_type: str = "CREATE_FOUNDATION_PROBE",
    causation_id: str | None = None,
    destination: str = "CURVE_LOCAL",
):
    """Create the local foundation Operation through the exact core policy."""

    correlation_id = _correlation_id(request)

    def context_builder():
        try:
            workspace = Workspace.objects.select_for_update().only("id", "slug", "owner_id").get(slug=workspace_slug)
        except Workspace.DoesNotExist as error:
            raise CurvePolicyResourceNotFound from error
        resource = _workspace_resource(workspace)
        return _build_query_context(
            workspace=workspace,
            user=request.user,
            action="CURVE.FOUNDATION_PROBE.START",
            resource=resource,
            correlation_id=correlation_id,
        )

    def mutation_callback(receipt):
        from plane.curve.models import OperationType
        from plane.curve.services import _create_operation_authorized

        actor = _human_actor(request.user)
        target = dict(receipt.resource_ref)
        return _create_operation_authorized(
            authorization_receipt=receipt,
            workspace_id=receipt.workspace_id,
            principal_scope=f"{actor['actor_type']}:{actor['actor_id']}",
            command_scope=f"{command_type}:{receipt.workspace_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_request,
            operation_type=OperationType.FOUNDATION_PROBE,
            command_type=command_type,
            target=target,
            actor=actor,
            effective_principal=dict(actor),
            correlation_id=correlation_id,
            causation_id=causation_id,
            destination=destination,
        )

    from plane.curve.services import CommandAlreadyInProgress, IdempotencyConflict

    return execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
        no_effect_exceptions=(IdempotencyConflict, CommandAlreadyInProgress),
    )


def request_operation_cancellation(
    *,
    request,
    workspace_slug: str,
    operation_id: uuid.UUID,
    expected_version: int,
    raw_idempotency_key: str,
    canonical_request: bytes,
    destination: str = "CURVE_TEMPORAL_OPERATION_V1",
):
    """Request a human-authorized, idempotent Operation cancellation."""

    correlation_id = _correlation_id(request)

    def context_builder():
        try:
            workspace = Workspace.objects.select_for_update().only("id", "slug", "owner_id").get(slug=workspace_slug)
        except Workspace.DoesNotExist as error:
            raise CurvePolicyResourceNotFound from error
        resource = _operation_resource(workspace=workspace, resource_id=operation_id)
        return _build_query_context(
            workspace=workspace,
            user=request.user,
            action="CURVE.OPERATION.CANCEL",
            resource=resource,
            correlation_id=correlation_id,
        )

    def mutation_callback(receipt):
        from plane.curve.services import _request_operation_cancellation_authorized

        actor = _human_actor(request.user)
        return _request_operation_cancellation_authorized(
            authorization_receipt=receipt,
            workspace_id=receipt.workspace_id,
            operation_id=operation_id,
            expected_version=expected_version,
            principal_scope=f"{actor['actor_type']}:{actor['actor_id']}",
            command_scope=f"CANCEL_OPERATION:{operation_id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical_request,
            actor=actor,
            effective_principal=dict(actor),
            correlation_id=correlation_id,
            causation_id=f"cancel:{operation_id}",
            destination=destination,
        )

    from plane.curve.services import (
        CommandAlreadyInProgress,
        IdempotencyConflict,
        InvalidOperationTransition,
        OptimisticConcurrencyError,
    )

    return execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
        no_effect_exceptions=(
            IdempotencyConflict,
            CommandAlreadyInProgress,
            OptimisticConcurrencyError,
            InvalidOperationTransition,
        ),
    )


def transition_operation_with_service_authorization(
    *,
    workspace_id: uuid.UUID,
    operation_id: uuid.UUID,
    expected_version: int,
    status: str,
    service_actor: dict,
    service_authorization: dict,
    correlation_id: str,
    causation_id: str | None = None,
    progress_percent: int | None = None,
    error: dict | None = None,
    destination: str = "CURVE_LOCAL",
    workflow_id: str | None = None,
):
    """Apply a worker transition through a trusted service-authorization boundary."""

    if not _valid_actor(service_actor) or service_actor["actor_type"] != "SERVICE":
        raise CurvePolicyConfigurationError("a trusted service actor is required")

    def context_builder():
        try:
            workspace = Workspace.objects.only("id", "slug", "owner_id").get(id=workspace_id)
        except Workspace.DoesNotExist as exc:
            raise CurvePolicyResourceNotFound from exc
        operation = (
            Operation.objects.select_for_update()
            .filter(workspace_id=workspace_id, id=operation_id)
            .only("id", "workspace_id", "aggregate_version", "created_by")
            .first()
        )
        if operation is None:
            resource = {
                "workspace_id": str(workspace_id),
                "ref": {
                    "resource_type": "OPERATION",
                    "resource_id": str(operation_id),
                },
                "exists": False,
                "owner": None,
            }
        else:
            resource = {
                "workspace_id": str(workspace_id),
                "ref": {
                    "resource_type": "OPERATION",
                    "resource_id": str(operation.id),
                    "resource_version": operation.aggregate_version,
                },
                "exists": True,
                "owner": operation.created_by
                if _valid_actor(operation.created_by)
                else {"actor_type": "INVALID", "actor_id": ""},
            }
        return {
            "schema_version": "1.0",
            "workspace_id": str(workspace_id),
            "subject": dict(service_actor),
            "effective_principal": dict(service_actor),
            "membership": None,
            "roles": ["TRUSTED_SERVICE"],
            "action": "CURVE.OPERATION.TRANSITION",
            "resource": resource,
            "classification": DataClassification.INTERNAL,
            "environment": _trusted_environment(),
            "feature_enabled": is_curve_enabled_for_workspace(workspace.slug),
            "object_acl": None,
            "assignment_context": None,
            "target_context": None,
            "service_authorization": service_authorization,
            "evaluated_at": timezone.now().isoformat().replace("+00:00", "Z"),
            "policy_manifest_digest": CORE_POLICY_MANIFEST_DIGEST,
            "correlation_id": correlation_id,
        }

    def mutation_callback(receipt):
        from plane.curve.services import _transition_operation_authorized

        return _transition_operation_authorized(
            authorization_receipt=receipt,
            workspace_id=workspace_id,
            operation_id=operation_id,
            expected_version=expected_version,
            status=status,
            actor=dict(service_actor),
            effective_principal=dict(service_actor),
            correlation_id=correlation_id,
            causation_id=causation_id,
            progress_percent=progress_percent,
            error=error,
            destination=destination,
            workflow_id=workflow_id,
        )

    from plane.curve.services import (
        InvalidOperationTransition,
        OptimisticConcurrencyError,
    )

    return execute_authorized_mutation(
        context_builder=context_builder,
        mutation_callback=mutation_callback,
        no_effect_exceptions=(OptimisticConcurrencyError, InvalidOperationTransition),
    )
