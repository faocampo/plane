# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import json
import logging
import re
import time
import uuid

from django.conf import settings
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.api.views.base import BaseAPIView
from plane.curve.config import CurvePolicyConfigurationError
from plane.curve.initiative_policy import authorize_initiative_query
from plane.curve.initiative_serialization import initiative_etag, serialize_initiative
from plane.curve.initiative_services import (
    InitiativeCommandError,
    InitiativeGateAssignmentInvalid,
    InitiativeKeywordConflict,
    InitiativeNoChanges,
    InitiativeProductInactive,
    InitiativeProductUnavailable,
    InitiativeStateConflict,
    InitiativeValidationError,
    RoadmapModeNotAvailable,
    accept_initiative_refinement,
    cancel_initiative,
    create_initiative,
    pause_initiative,
    resume_initiative,
    update_initiative_draft,
)
from plane.curve.models import (
    DomainEvent,
    Initiative,
    InitiativeState,
    Operation,
    OperationType,
    Product,
    ProductState,
)
from plane.curve.observability.instrumentation import observe_curve_span
from plane.curve.observability.propagation import event_contract
from plane.curve.observability.runtime import get_telemetry_runtime
from plane.curve.permissions import (
    CurveCorePolicyPermission,
    query_authorization_receipt,
)
from plane.curve.policy_manifest import PolicyManifestIntegrityError
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    authorize_query,
    correlation_id_for_request,
    request_operation_cancellation,
    start_foundation_probe,
)
from plane.curve.product_guards import (
    ProductHasNonTerminalInitiative,
    ProductInitiativeGuardUnavailable,
)
from plane.curve.product_policy import authorize_product_query
from plane.curve.product_serialization import product_etag, serialize_product
from plane.curve.product_services import (
    ProductCommandError,
    ProductKeyConflict,
    ProductNoChanges,
    ProductStateConflict,
    ProductTargetOwnerInactive,
    ProductValidationError,
    archive_product,
    create_product,
    reassign_product_owner,
    restore_product,
    update_product_metadata,
)
from plane.curve.serialization import serialize_sse_event
from plane.curve.services import (
    CommandAlreadyInProgress,
    CurveResourceNotFound,
    IdempotencyConflict,
    InvalidCommand,
    InvalidOperationTransition,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    canonical_json_bytes,
)
from plane.curve.temporal.constants import TEMPORAL_DESTINATION


logger = logging.getLogger(__name__)
ETAG_PATTERN = re.compile(r'^"curve-operation:([0-9a-f-]{36}):v([1-9][0-9]*)"$')
PRODUCT_ETAG_PATTERN = re.compile(r'^"curve-product:([0-9a-f-]{36}):v([1-9][0-9]*)"$')
INITIATIVE_ETAG_PATTERN = re.compile(r'^"curve-initiative:([0-9a-f-]{36}):v([1-9][0-9]*)"$')


class CurveAPIRequestError(ValueError):
    def __init__(self, *, status_code: int, code: str, title: str, field: str | None = None):
        super().__init__(title)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.field = field


class CurveStaleCursor(CurveAPIRequestError):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_410_GONE,
            code="CURVE_EVENT_CURSOR_STALE",
            title="The event cursor can no longer be resumed",
            field="Last-Event-ID",
        )


class CurveEventStreamRenderer(BaseRenderer):
    """Negotiate SSE while retaining JSON Problem Details on stream errors."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        return json.dumps(data, separators=(",", ":")).encode("utf-8")


def operation_etag(*, operation_id: str, version: int) -> str:
    return f'"curve-operation:{operation_id}:v{version}"'


def _required_idempotency_key(request) -> str:
    value = request.headers.get("Idempotency-Key", "")
    if not 16 <= len(value) <= 255 or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CurveAPIRequestError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="CURVE_IDEMPOTENCY_KEY_INVALID",
            title="A valid Idempotency-Key header is required",
            field="Idempotency-Key",
        )
    return value


def _expected_operation_version(request, operation_id: uuid.UUID) -> int:
    value = request.headers.get("If-Match")
    if value is None:
        raise CurveAPIRequestError(
            status_code=428,
            code="CURVE_PRECONDITION_REQUIRED",
            title="If-Match is required for cancellation",
            field="If-Match",
        )
    match = ETAG_PATTERN.fullmatch(value)
    if match is None or match.group(1) != str(operation_id):
        raise CurveAPIRequestError(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            code="CURVE_PRECONDITION_FAILED",
            title="The operation version does not match",
            field="If-Match",
        )
    return int(match.group(2))


def _expected_product_version(request, product_id: uuid.UUID) -> int:
    value = request.headers.get("If-Match")
    if value is None:
        raise CurveAPIRequestError(
            status_code=428,
            code="CURVE_PRECONDITION_REQUIRED",
            title="If-Match is required for Product changes",
            field="If-Match",
        )
    match = PRODUCT_ETAG_PATTERN.fullmatch(value)
    if match is None or match.group(1) != str(product_id):
        raise CurveAPIRequestError(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            code="CURVE_PRECONDITION_FAILED",
            title="The Product version does not match",
            field="If-Match",
        )
    return int(match.group(2))


def _expected_initiative_version(request, initiative_id: uuid.UUID) -> int:
    value = request.headers.get("If-Match")
    if value is None:
        raise CurveAPIRequestError(
            status_code=428,
            code="CURVE_PRECONDITION_REQUIRED",
            title="If-Match is required for Initiative changes",
            field="If-Match",
        )
    match = INITIATIVE_ETAG_PATTERN.fullmatch(value)
    if match is None or match.group(1) != str(initiative_id):
        raise CurveAPIRequestError(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            code="CURVE_PRECONDITION_FAILED",
            title="The Initiative version does not match",
            field="If-Match",
        )
    return int(match.group(2))


def _page_size(request) -> int:
    raw = request.query_params.get("page_size", "25")
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise CurveAPIRequestError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="CURVE_PAGE_SIZE_INVALID",
            title="page_size must be an integer between 1 and 100",
            field="page_size",
        ) from error
    if not 1 <= value <= 100:
        raise CurveAPIRequestError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="CURVE_PAGE_SIZE_INVALID",
            title="page_size must be an integer between 1 and 100",
            field="page_size",
        )
    return value


def _operation_type_filter(request) -> str | None:
    value = request.query_params.get("operation_type")
    if value is None:
        return None
    if value not in OperationType.values:
        raise CurveAPIRequestError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="CURVE_OPERATION_TYPE_INVALID",
            title="operation_type is not supported",
            field="operation_type",
        )
    return value


def _encode_page_cursor(operation: Operation) -> str:
    payload = canonical_json_bytes(
        {
            "created_at": operation.created_at.isoformat(),
            "id": str(operation.id),
        }
    )
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_page_cursor(value: str | None):
    if not value:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"created_at", "id"}:
            raise ValueError
        created_at = parse_datetime(payload["created_at"])
        operation_id = uuid.UUID(payload["id"])
        if created_at is None or created_at.tzinfo is None:
            raise ValueError
        return created_at, operation_id
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CurveAPIRequestError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="CURVE_CURSOR_INVALID",
            title="The operation cursor is invalid",
            field="cursor",
        ) from error


def _human_actor(user) -> dict[str, str]:
    return {"actor_type": "HUMAN", "actor_id": str(user.id)}


class CurveAPIView(BaseAPIView):
    """Curve API base with safe RFC 9457 Problem Details responses."""

    authentication_classes = [SessionAuthentication, APIKeyAuthentication]

    def problem(self, request, *, status_code: int, code: str, title: str, field: str | None = None, extra=None):
        body = {
            "type": f"https://curve.example.invalid/problems/{code.lower().replace('_', '-')}",
            "title": title,
            "status": status_code,
            "correlation_id": correlation_id_for_request(request),
        }
        if field:
            body["errors"] = [{"code": code, "field": field, "message": title}]
        if extra:
            body.update(extra)
        return Response(body, status=status_code, content_type="application/problem+json")

    def handle_exception(self, exc):
        if isinstance(exc, CurveAPIRequestError):
            extra = None
            if isinstance(exc, CurveStaleCursor):
                extra = {"resync": {"action": "FETCH_CURRENT_OPERATIONS", "cursor": None}}
            return self.problem(
                self.request,
                status_code=exc.status_code,
                code=exc.code,
                title=exc.title,
                field=exc.field,
                extra=extra,
            )
        if isinstance(exc, CurvePolicyDenied):
            hidden = {"FEATURE_DISABLED", "RESOURCE_NOT_FOUND"}.intersection(exc.reason_codes)
            return self.problem(
                self.request,
                status_code=status.HTTP_404_NOT_FOUND if hidden else status.HTTP_403_FORBIDDEN,
                code="CURVE_RESOURCE_NOT_FOUND" if hidden else "CURVE_ACCESS_DENIED",
                title="The Curve resource is unavailable" if hidden else "Access to this Curve resource is denied",
            )
        if isinstance(exc, (CurvePolicyResourceNotFound, CurveResourceNotFound, NotFound)):
            return self.problem(
                self.request,
                status_code=status.HTTP_404_NOT_FOUND,
                code="CURVE_RESOURCE_NOT_FOUND",
                title="The Curve resource is unavailable",
            )
        if isinstance(exc, OptimisticConcurrencyError):
            return self.problem(
                self.request,
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                code="CURVE_PRECONDITION_FAILED",
                title="The operation version does not match",
                field="If-Match",
            )
        if isinstance(exc, ProductValidationError):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="The Product request is invalid",
                field=exc.field,
            )
        if isinstance(exc, InitiativeValidationError):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="The Initiative request is invalid",
                field=exc.field,
            )
        if isinstance(exc, InitiativeProductUnavailable):
            return self.problem(
                self.request,
                status_code=status.HTTP_404_NOT_FOUND,
                code=exc.code,
                title="The Product is unavailable",
                field="product_id",
            )
        if isinstance(exc, RoadmapModeNotAvailable):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="ROADMAP Initiative mode is not available in this release",
                field="mode",
            )
        if isinstance(exc, InitiativeKeywordConflict):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Initiative keyword is already in use",
                field="keyword",
            )
        if isinstance(exc, InitiativeGateAssignmentInvalid):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Initiative gate assignments do not satisfy policy",
                field="gate_assignments",
            )
        if isinstance(exc, InitiativeProductInactive):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Product is not active",
                field="product_id",
            )
        if isinstance(exc, InitiativeNoChanges):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="The Initiative command contains no changes",
            )
        if isinstance(exc, InitiativeStateConflict):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Initiative lifecycle precondition is not satisfied",
            )
        if isinstance(exc, InitiativeCommandError):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="The Initiative command was rejected",
            )
        if isinstance(exc, ProductKeyConflict):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Product key is already in use",
                field="key",
            )
        if isinstance(exc, ProductNoChanges):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="The Product command contains no changes",
            )
        if isinstance(exc, ProductTargetOwnerInactive):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The target owner is not an active workspace member",
                field="owner_user_id",
            )
        if isinstance(exc, (ProductStateConflict, ProductHasNonTerminalInitiative)):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Product lifecycle precondition is not satisfied",
            )
        if isinstance(exc, ProductInitiativeGuardUnavailable):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code=exc.code,
                title="The Product archival guard is unavailable",
            )
        if isinstance(exc, ProductCommandError):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code=exc.code,
                title="The Product command was rejected",
            )
        if isinstance(exc, InvalidOperationTransition):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_OPERATION_NOT_CANCELLABLE",
                title="The operation cannot be cancelled in its current state",
            )
        if isinstance(exc, (IdempotencyConflict, CommandAlreadyInProgress, ReplayResourceUnavailable)):
            return self.problem(
                self.request,
                status_code=status.HTTP_409_CONFLICT,
                code="CURVE_COMMAND_CONFLICT",
                title="The command conflicts with an existing request",
            )
        if isinstance(exc, (InvalidCommand, ParseError)):
            return self.problem(
                self.request,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_REQUEST_INVALID",
                title="The Curve request is invalid",
            )
        if isinstance(exc, (CurvePolicyConfigurationError, PolicyManifestIntegrityError, PermissionDenied)):
            return self.problem(
                self.request,
                status_code=status.HTTP_403_FORBIDDEN,
                code="CURVE_ACCESS_DENIED",
                title="Access to this Curve resource is denied",
            )
        if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            return self.problem(
                self.request,
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="CURVE_AUTHENTICATION_REQUIRED",
                title="Authentication is required",
            )
        if isinstance(exc, APIException):
            return self.problem(
                self.request,
                status_code=exc.status_code,
                code="CURVE_REQUEST_REJECTED",
                title="The Curve request was rejected",
            )
        logger.error("Curve request failed")
        return self.problem(
            self.request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="CURVE_INTERNAL_ERROR",
            title="Curve could not complete the request",
        )


class CurveWorkspaceShellEndpoint(CurveAPIView):
    """Return the Curve shell projection after audited policy evaluation."""

    permission_classes = [IsAuthenticated, CurveCorePolicyPermission]
    curve_policy_action = "CURVE.SHELL.VIEW"
    curve_policy_resource_type = "WORKSPACE"

    def get(self, request, slug):
        receipt = query_authorization_receipt(request)
        return Response(dict(receipt.projection), status=status.HTTP_200_OK)


def _product_response(result_or_product, *, status_code):
    product = getattr(result_or_product, "product", result_or_product)
    response = Response(serialize_product(product), status=status_code)
    response["ETag"] = product_etag(product)
    return response


class CurveProductAPIView(CurveAPIView):
    authentication_classes = [SessionAuthentication]


class CurveProductListEndpoint(CurveProductAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        authorization = authorize_product_query(request=request, workspace_slug=slug)
        page_size = _page_size(request)
        state_filter = request.query_params.get("state", ProductState.ACTIVE)
        if state_filter not in ProductState.values:
            raise CurveAPIRequestError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_PRODUCT_STATE_INVALID",
                title="state must be ACTIVE or ARCHIVED",
                field="state",
            )
        cursor = _decode_page_cursor(request.query_params.get("cursor"))
        products = Product.objects.filter(
            workspace_id=authorization.workspace.id,
            state=state_filter,
        )
        if cursor:
            created_at, product_id = cursor
            products = products.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=product_id))
        products = list(products.order_by("-created_at", "-id")[: page_size + 1])
        return Response(
            {
                "results": [serialize_product(product) for product in products[:page_size]],
                "next_cursor": _encode_page_cursor(products[page_size - 1]) if len(products) > page_size else None,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, slug):
        result = create_product(
            request=request,
            workspace_slug=slug,
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        response = _product_response(result, status_code=status.HTTP_201_CREATED)
        response["Location"] = f"/api/v1/workspaces/{slug}/curve/products/{result.product.id}/"
        return response


class CurveProductDetailEndpoint(CurveProductAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug, product_id):
        authorization = authorize_product_query(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
        )
        return _product_response(authorization.product, status_code=status.HTTP_200_OK)

    def patch(self, request, slug, product_id):
        result = update_product_metadata(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            expected_version=_expected_product_version(request, product_id),
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _product_response(result, status_code=status.HTTP_200_OK)


class CurveProductOwnerEndpoint(CurveProductAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, product_id):
        result = reassign_product_owner(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            expected_version=_expected_product_version(request, product_id),
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _product_response(result, status_code=status.HTTP_200_OK)


class CurveProductArchiveEndpoint(CurveProductAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, product_id):
        if request.data not in ({}, None):
            raise ProductValidationError
        result = archive_product(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            expected_version=_expected_product_version(request, product_id),
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _product_response(result, status_code=status.HTTP_200_OK)


class CurveProductRestoreEndpoint(CurveProductAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, product_id):
        if request.data not in ({}, None):
            raise ProductValidationError
        result = restore_product(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            expected_version=_expected_product_version(request, product_id),
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _product_response(result, status_code=status.HTTP_200_OK)


def _initiative_response(result_or_initiative, *, status_code):
    initiative = getattr(result_or_initiative, "initiative", result_or_initiative)
    response = Response(serialize_initiative(initiative), status=status_code)
    response["ETag"] = initiative_etag(initiative)
    return response


class CurveInitiativeAPIView(CurveAPIView):
    authentication_classes = [SessionAuthentication]


class CurveInitiativeListEndpoint(CurveInitiativeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        authorization = authorize_initiative_query(request=request, workspace_slug=slug)
        page_size = _page_size(request)
        state_filter = request.query_params.get("state")
        if state_filter is not None and state_filter not in {
            InitiativeState.DRAFT,
            InitiativeState.ALIGNING,
            InitiativeState.PAUSED,
            InitiativeState.CANCELLED,
        }:
            raise CurveAPIRequestError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_INITIATIVE_STATE_INVALID",
                title="state is not available in M1-01A",
                field="state",
            )
        product_filter = request.query_params.get("product_id")
        if product_filter is not None:
            try:
                product_filter = uuid.UUID(product_filter)
            except ValueError as error:
                raise CurveAPIRequestError(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="CURVE_INITIATIVE_PRODUCT_FILTER_INVALID",
                    title="product_id must be a UUID",
                    field="product_id",
                ) from error
        cursor = _decode_page_cursor(request.query_params.get("cursor"))
        initiatives = Initiative.objects.filter(workspace_id=authorization.workspace.id).prefetch_related(
            "gate_assignments"
        )
        if state_filter:
            initiatives = initiatives.filter(state=state_filter)
        if product_filter:
            initiatives = initiatives.filter(product_id=product_filter)
        if cursor:
            created_at, initiative_id = cursor
            initiatives = initiatives.filter(
                Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=initiative_id)
            )
        initiatives = list(initiatives.order_by("-created_at", "-id")[: page_size + 1])
        return Response(
            {
                "results": [serialize_initiative(initiative) for initiative in initiatives[:page_size]],
                "next_cursor": (
                    _encode_page_cursor(initiatives[page_size - 1]) if len(initiatives) > page_size else None
                ),
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, slug):
        result = create_initiative(
            request=request,
            workspace_slug=slug,
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        response = _initiative_response(result, status_code=status.HTTP_201_CREATED)
        response["Location"] = f"/api/v1/workspaces/{slug}/curve/initiatives/{result.initiative.id}/"
        return response


class CurveInitiativeDetailEndpoint(CurveInitiativeAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug, initiative_id):
        authorization = authorize_initiative_query(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
        )
        return _initiative_response(authorization.initiative, status_code=status.HTTP_200_OK)

    def patch(self, request, slug, initiative_id):
        result = update_initiative_draft(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            expected_version=_expected_initiative_version(request, initiative_id),
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _initiative_response(result, status_code=status.HTTP_200_OK)


class CurveInitiativeAcceptRefinementEndpoint(CurveInitiativeAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, initiative_id):
        if request.data not in ({}, None):
            raise InitiativeValidationError
        result = accept_initiative_refinement(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            expected_version=_expected_initiative_version(request, initiative_id),
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _initiative_response(result, status_code=status.HTTP_200_OK)


class CurveInitiativePauseEndpoint(CurveInitiativeAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, initiative_id):
        result = pause_initiative(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            expected_version=_expected_initiative_version(request, initiative_id),
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _initiative_response(result, status_code=status.HTTP_200_OK)


class CurveInitiativeResumeEndpoint(CurveInitiativeAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, initiative_id):
        result = resume_initiative(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            expected_version=_expected_initiative_version(request, initiative_id),
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _initiative_response(result, status_code=status.HTTP_200_OK)


class CurveInitiativeCancelEndpoint(CurveInitiativeAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, initiative_id):
        result = cancel_initiative(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            expected_version=_expected_initiative_version(request, initiative_id),
            payload=request.data,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        return _initiative_response(result, status_code=status.HTTP_200_OK)


class CurveOperationListEndpoint(CurveAPIView):
    permission_classes = [IsAuthenticated, CurveCorePolicyPermission]
    curve_policy_action = "CURVE.SHELL.VIEW"
    curve_policy_resource_type = "WORKSPACE"

    def get(self, request, slug):
        workspace_receipt = query_authorization_receipt(request)
        page_size = _page_size(request)
        operation_type = _operation_type_filter(request)
        cursor = _decode_page_cursor(request.query_params.get("cursor"))
        candidates = Operation.objects.filter(
            workspace_id=workspace_receipt.workspace_id,
            created_by=_human_actor(request.user),
        ).only("id", "created_at")
        if operation_type:
            candidates = candidates.filter(operation_type=operation_type)
        if cursor:
            created_at, operation_id = cursor
            candidates = candidates.filter(Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=operation_id))
        candidates = list(candidates.order_by("-created_at", "-id")[: page_size + 1])
        visible = []
        for operation in candidates[:page_size]:
            receipt = authorize_query(
                request=request,
                action="CURVE.OPERATION.READ",
                workspace_slug=slug,
                resource_type="OPERATION",
                resource_id=operation.id,
            )
            visible.append(dict(receipt.projection))
        return Response(
            {
                "results": visible,
                "next_cursor": _encode_page_cursor(candidates[page_size - 1]) if len(candidates) > page_size else None,
            },
            status=status.HTTP_200_OK,
        )


class CurveOperationDetailEndpoint(CurveAPIView):
    permission_classes = [IsAuthenticated, CurveCorePolicyPermission]
    curve_policy_action = "CURVE.OPERATION.READ"
    curve_policy_resource_type = "OPERATION"

    def get(self, request, slug, resource_id):
        receipt = query_authorization_receipt(request)
        projection = dict(receipt.projection)
        response = Response(projection, status=status.HTTP_200_OK)
        response["ETag"] = operation_etag(operation_id=projection["id"], version=projection["version"])
        return response


class CurveOperationCancelEndpoint(CurveAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, resource_id):
        if request.data not in ({}, None):
            raise CurveAPIRequestError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_CANCEL_BODY_INVALID",
                title="Cancellation does not accept a request body",
            )
        expected_version = _expected_operation_version(request, resource_id)
        result = request_operation_cancellation(
            request=request,
            workspace_slug=slug,
            operation_id=resource_id,
            expected_version=expected_version,
            raw_idempotency_key=_required_idempotency_key(request),
            canonical_request=canonical_json_bytes(
                {
                    "command_type": "CANCEL_OPERATION",
                    "operation_id": str(resource_id),
                    "expected_version": expected_version,
                }
            ),
            destination=TEMPORAL_DESTINATION,
        )
        projection = {
            "schema_version": result.operation.schema_version,
            "id": str(result.operation.id),
            "workspace_id": str(result.operation.workspace_id),
            "operation_type": result.operation.operation_type,
            "status": result.operation.status,
            "version": result.operation.aggregate_version,
            **(
                {"progress_percent": result.operation.progress_percent}
                if result.operation.progress_percent is not None
                else {}
            ),
        }
        response = Response(projection, status=status.HTTP_202_ACCEPTED)
        response["ETag"] = operation_etag(operation_id=projection["id"], version=projection["version"])
        return response


class CurveFoundationProbeEndpoint(CurveAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        if not (
            settings.DEBUG
            and getattr(settings, "CURVE_FOUNDATION_PROBE_ENABLED", False)
            and getattr(settings, "CURVE_ENVIRONMENT", "") == "LOCAL"
        ):
            raise CurvePolicyResourceNotFound
        if not isinstance(request.data, dict) or not set(request.data).issubset({"requested_delay_ms"}):
            raise CurveAPIRequestError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_PROBE_BODY_INVALID",
                title="The Foundation probe request is invalid",
            )
        delay = request.data.get("requested_delay_ms")
        if delay is not None and (type(delay) is not int or not 0 <= delay <= 5000):
            raise CurveAPIRequestError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="CURVE_PROBE_DELAY_INVALID",
                title="requested_delay_ms must be an integer between 0 and 5000",
                field="requested_delay_ms",
            )
        command = {"command_type": "CREATE_FOUNDATION_PROBE"}
        if delay is not None:
            command["requested_delay_ms"] = delay
        result = start_foundation_probe(
            request=request,
            workspace_slug=slug,
            raw_idempotency_key=_required_idempotency_key(request),
            canonical_request=canonical_json_bytes(command),
            destination=TEMPORAL_DESTINATION,
        )
        projection = {
            "schema_version": result.operation.schema_version,
            "id": str(result.operation.id),
            "workspace_id": str(result.operation.workspace_id),
            "operation_type": result.operation.operation_type,
            "status": result.operation.status,
            "version": result.operation.aggregate_version,
            **(
                {"progress_percent": result.operation.progress_percent}
                if result.operation.progress_percent is not None
                else {}
            ),
        }
        response = Response(projection, status=status.HTTP_202_ACCEPTED)
        response["Location"] = f"/api/v1/workspaces/{slug}/curve/operations/{result.operation.id}"
        response["ETag"] = operation_etag(operation_id=projection["id"], version=projection["version"])
        return response


def _visible_event_queryset(*, workspace_id, user):
    operation_ids = Operation.objects.filter(
        workspace_id=workspace_id,
        created_by=_human_actor(user),
    ).values_list("id", flat=True)
    return DomainEvent.objects.filter(
        workspace_id=workspace_id,
        aggregate_type="OPERATION",
        aggregate_id__in=operation_ids,
    )


def _events_after(queryset, event):
    return queryset.filter(Q(recorded_at__gt=event.recorded_at) | Q(recorded_at=event.recorded_at, id__gt=event.id))


def _record_sse_metric(runtime, name: str, value: int, *, result: str | None = None) -> None:
    if not runtime.enabled:
        return
    attributes = {"curve.component": "SSE"}
    if result is not None:
        attributes["curve.result"] = result
    try:
        runtime.registry.record(name, value, attributes=attributes)
    except Exception:
        return


def _format_sse(event: DomainEvent, *, telemetry_runtime=None) -> str:
    try:
        _, traceparent = event_contract(event.payload_schema, event.payload)
    except ValueError:
        traceparent = None
    with observe_curve_span(
        component="API",
        span_name="curve.sse.publish",
        workspace_id=event.workspace_id,
        parent_traceparent=traceparent,
        attributes={
            "curve.component": "SSE",
            "curve.event.id": str(event.id),
            "curve.operation.id": str(event.aggregate_id),
            "curve.result": "SUCCEEDED",
        },
        runtime=telemetry_runtime,
    ):
        data = json.dumps(serialize_sse_event(event), separators=(",", ":"))
        return f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"


class CurveEventStreamEndpoint(CurveAPIView):
    permission_classes = [IsAuthenticated, CurveCorePolicyPermission]
    renderer_classes = [JSONRenderer, CurveEventStreamRenderer]
    curve_policy_action = "CURVE.SHELL.VIEW"
    curve_policy_resource_type = "WORKSPACE"

    def get(self, request, slug):
        workspace_receipt = query_authorization_receipt(request)
        telemetry_runtime = get_telemetry_runtime(component="API")
        replay_limit = getattr(settings, "CURVE_SSE_REPLAY_LIMIT", 100)
        events = _visible_event_queryset(workspace_id=workspace_receipt.workspace_id, user=request.user)
        last_event_id = request.headers.get("Last-Event-ID")
        cursor_event = None
        if last_event_id:
            try:
                cursor_id = uuid.UUID(last_event_id)
            except ValueError as error:
                raise CurveStaleCursor from error
            cursor_event = events.filter(id=cursor_id).only("id", "recorded_at").first()
            if cursor_event is None:
                raise CurveStaleCursor
            later = _events_after(events, cursor_event)
            if later.count() > replay_limit:
                _record_sse_metric(telemetry_runtime, "curve.sse.resume", 1, result="FAILED")
                raise CurveStaleCursor
            initial_events = list(later.order_by("recorded_at", "id")[:replay_limit])
            _record_sse_metric(telemetry_runtime, "curve.sse.resume", 1, result="SUCCEEDED")
        else:
            initial_events = list(events.order_by("-recorded_at", "-id")[:replay_limit])
            initial_events.reverse()

        def stream():
            latest = cursor_event
            _record_sse_metric(telemetry_runtime, "curve.sse.connections", 1)
            try:
                yield "retry: 1000\n\n"
                for event in initial_events:
                    try:
                        authorize_query(
                            request=request,
                            action="CURVE.OPERATION.READ",
                            workspace_slug=slug,
                            resource_type="OPERATION",
                            resource_id=event.aggregate_id,
                        )
                    except (CurvePolicyDenied, CurvePolicyResourceNotFound):
                        continue
                    latest = event
                    yield _format_sse(event, telemetry_runtime=telemetry_runtime)

                deadline = time.monotonic() + getattr(settings, "CURVE_SSE_CONNECTION_SECONDS", 25.0)
                poll_interval = getattr(settings, "CURVE_SSE_POLL_INTERVAL_SECONDS", 1.0)
                while time.monotonic() < deadline:
                    time.sleep(poll_interval)
                    current_events = _visible_event_queryset(
                        workspace_id=workspace_receipt.workspace_id,
                        user=request.user,
                    )
                    if latest is not None:
                        current_events = _events_after(current_events, latest)
                    batch = list(current_events.order_by("recorded_at", "id")[:replay_limit])
                    if not batch:
                        yield ": keep-alive\n\n"
                        continue
                    for event in batch:
                        try:
                            authorize_query(
                                request=request,
                                action="CURVE.OPERATION.READ",
                                workspace_slug=slug,
                                resource_type="OPERATION",
                                resource_id=event.aggregate_id,
                            )
                        except (CurvePolicyDenied, CurvePolicyResourceNotFound):
                            continue
                        latest = event
                        yield _format_sse(event, telemetry_runtime=telemetry_runtime)
            finally:
                _record_sse_metric(telemetry_runtime, "curve.sse.connections", -1)

        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache, no-store"
        response["Content-Encoding"] = "identity"
        response["X-Accel-Buffering"] = "no"
        return response
