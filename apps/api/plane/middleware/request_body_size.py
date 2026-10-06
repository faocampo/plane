# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from io import BytesIO
from plane.curve.request_privacy import is_prd_command_request, PRD_COMMAND_MAX_BYTES


class RequestBodySizeLimitMiddleware:
    """
    Middleware to catch RequestDataTooBig exceptions and return
    413 Request Entity Too Large instead of 400 Bad Request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_prd_command_request(request):
            body = request.read(PRD_COMMAND_MAX_BYTES + 1)
            if len(body) > PRD_COMMAND_MAX_BYTES:
                return JsonResponse(
                    {
                        "type": "urn:curve:problem:prd-command-too-large",
                        "code": "PRD_COMMAND_TOO_LARGE",
                        "title": "The PRD command is too large",
                        "status": 413,
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
