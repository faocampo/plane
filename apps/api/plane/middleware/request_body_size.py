# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from io import BytesIO
import uuid
from plane.curve.request_privacy import (
    is_local_prd_upload_request,
    is_local_plan_upload_request,
    LOCAL_PRD_UPLOAD_MAX_BYTES,
    is_prd_command_request,
    PRD_COMMAND_MAX_BYTES,
    is_scope_proposal_request,
    SCOPE_PROPOSAL_MAX_BYTES,
)


class RequestBodySizeLimitMiddleware:
    """
    Middleware to catch RequestDataTooBig exceptions and return
    413 Request Entity Too Large instead of 400 Bad Request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        plan_upload = is_local_plan_upload_request(request)
        upload = is_local_prd_upload_request(request) or plan_upload
        scope = is_scope_proposal_request(request)
        if upload or scope or is_prd_command_request(request):
            limit = (
                LOCAL_PRD_UPLOAD_MAX_BYTES if upload else (SCOPE_PROPOSAL_MAX_BYTES if scope else PRD_COMMAND_MAX_BYTES)
            )
            code = (
                ("LOCAL_PLAN_UPLOAD_TOO_LARGE" if plan_upload else "LOCAL_PRD_UPLOAD_TOO_LARGE")
                if upload
                else ("SCOPE_PROPOSAL_REQUEST_TOO_LARGE" if scope else "PRD_COMMAND_TOO_LARGE")
            )
            body = request.read(limit + 1)
            if len(body) > limit:
                return JsonResponse(
                    {
                        "type": "urn:curve:problem:" + code.lower().replace("_", "-"),
                        "code": code,
                        "title": "The scope proposal is too large"
                        if scope
                        else ("The plan document is too large" if plan_upload else "The PRD command is too large"),
                        "status": 413,
                        **({"correlation_id": f"curve-{uuid.uuid4()}"} if scope else {}),
                    },
                    status=413,
                    content_type="application/problem+json",
                    headers={"Cache-Control": "no-store"},
                )
            # Preserve exact bytes before session CSRF validation invokes DRF's
            # parser. Duplicate keys must remain visible to the command boundary.
            request._body = body
            request._stream = BytesIO(body)
        try:
            _ = request.body
        except RequestDataTooBig:
            return JsonResponse(
                {
                    "error": "REQUEST_BODY_TOO_LARGE",
                    "detail": "The size of the request body exceeds the maximum allowed size.",
                },
                status=413,
            )

        # If body size is OK, continue with the request
        return self.get_response(request)
