# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated candidate PRD commands; explicit runtime activation only."""

from django.conf import settings
from django.urls import reverse
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotAuthenticated, AuthenticationFailed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.exceptions import MethodNotAllowed, NotAcceptable, ParseError, UnsupportedMediaType
from rest_framework.response import Response
from rest_framework.views import APIView

from .config import is_curve_enabled_for_workspace
from .policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound, correlation_id_for_request
from .prd_acceptance import accept_prd_command, PrdRuntimeUnavailable
from .prd_commands import parse_prd_command, PrdCommandError
from .prd_policy_context import PrdAuthorityUnavailable
from .services import IdempotencyConflict, CommandAlreadyInProgress, ReplayResourceUnavailable


class CurvePrdCommandEndpoint(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    route = None

    def post(self, request, slug, initiative_id):
        if (
            not is_curve_enabled_for_workspace(slug)
            or getattr(settings, "CURVE_PRD_COMMANDS_ENABLED", False) is not True
        ):
            raise PrdCommandError("NOT_FOUND", 404)
        if request.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        command = parse_prd_command(
            route=self.route,
            body=request.body,
            if_match=request.headers.get("If-Match"),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        result = accept_prd_command(request=request, workspace_slug=slug, initiative_id=initiative_id, command=command)
        operation = result.operation
        response = Response(
            dict(
                schema_version="1.0",
                id=str(operation.id),
                workspace_id=str(operation.workspace_id),
                operation_type=operation.operation_type,
                status=operation.status,
                version=operation.aggregate_version,
            ),
            status=202,
        )
        response["Location"] = reverse("curve-operation-detail", kwargs={"slug": slug, "resource_id": operation.id})
        response["ETag"] = f'"{command.expected_version}"'
        response["Cache-Control"] = "no-store"
        return response

    def handle_exception(self, error):
        # Never pass provider, rationale, schema or storage exceptions to a generic
        # exception logger/renderer. Only fixed Problem Details leave this boundary.
        code, status = "PRD_RUNTIME_UNAVAILABLE", 503
        if isinstance(error, PrdCommandError):
            code, status = error.code, error.status
        elif isinstance(error, (NotAuthenticated, AuthenticationFailed)):
            code, status = "AUTHENTICATION_REQUIRED", 401
        elif isinstance(error, PermissionDenied):
            code, status = "FORBIDDEN", 403
        elif isinstance(error, MethodNotAllowed):
            code, status = "METHOD_NOT_ALLOWED", 405
        elif isinstance(error, NotAcceptable):
            code, status = "NOT_ACCEPTABLE", 406
        elif isinstance(error, ParseError):
            code, status = "PRD_COMMAND_INVALID", 422
        elif isinstance(error, UnsupportedMediaType):
            code, status = "UNSUPPORTED_MEDIA_TYPE", 415
        elif isinstance(error, CurvePolicyDenied):
            hidden = {"FEATURE_DISABLED", "RESOURCE_NOT_FOUND"}.intersection(error.reason_codes)
            if "INACTIVE_MEMBERSHIP" in error.reason_codes:
                hidden = False
            code, status = ("NOT_FOUND", 404) if hidden else ("FORBIDDEN", 403)
        elif isinstance(error, CurvePolicyResourceNotFound):
            code, status = "NOT_FOUND", 404
        elif isinstance(error, (IdempotencyConflict, CommandAlreadyInProgress)):
            code, status = "IDEMPOTENCY_CONFLICT", 409
        elif isinstance(error, (PrdRuntimeUnavailable, PrdAuthorityUnavailable, ReplayResourceUnavailable)):
            code, status = "PRD_RUNTIME_UNAVAILABLE", 503
        response = Response(
            dict(
                type=f"urn:curve:problem:{code.lower().replace('_', '-')}",
                title="The PRD command could not be accepted",
                status=status,
                code=code,
                correlation_id=correlation_id_for_request(self.request),
            ),
            status=status,
            content_type="application/problem+json",
        )
        response["Cache-Control"] = "no-store"
        return response
