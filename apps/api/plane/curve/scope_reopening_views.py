# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Session-authenticated, default-off successor reopening boundary."""

import re

from rest_framework.response import Response

from .prd_commands import PrdCommandError
from .prd_views import CurvePrdCommandEndpoint
from .scope_reopening_policy import reopening_enabled
from .scope_reopening_services import parse_scope_reopening_body, reopen_and_replace_scope


class CurveScopeReopeningEndpoint(CurvePrdCommandEndpoint):
    http_method_names = ["post", "options"]

    def post(self, request, slug, initiative_id):
        if not reopening_enabled(slug):
            raise PrdCommandError("NOT_FOUND", 404)
        if request.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        value = request.headers.get("If-Match")
        if value is None:
            raise PrdCommandError("PRECONDITION_REQUIRED", 428)
        if len(value) > 18 or re.fullmatch(r'"[1-9][0-9]*"', value) is None:
            raise PrdCommandError("VERSION_CONFLICT", 412)
        result = reopen_and_replace_scope(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            payload=parse_scope_reopening_body(request.body),
            expected_version=int(value[1:-1]),
            raw_idempotency_key=request.headers.get("Idempotency-Key"),
        )
        response = Response(result.data, status=result.response_status)
        response["ETag"] = f'"{result.data["initiative_version"]}"'
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


from .prd_read_views import CurvePrdReviewContextEndpoint  # noqa: E402
from .scope_reopening_read import read_scope_reopening_preconditions  # noqa: E402


class CurveScopeReopeningPreconditionsEndpoint(CurvePrdReviewContextEndpoint):
    def get(self, request, slug, initiative_id):
        data = read_scope_reopening_preconditions(request=request, workspace_slug=slug, initiative_id=initiative_id)
        response = Response(data)
        response["ETag"] = f'"{data["initiative_version"]}"'
        return response
