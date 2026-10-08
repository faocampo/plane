# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Session/CSRF-only manual draft HTTP candidates; no registered live routes."""

from urllib.parse import quote
from django.core.exceptions import RequestDataTooBig
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .contracts import ManualPlanError, parse_save, require


class ManualPlanSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        # Use Django's original request for normal CSRF checking. Asking DRF for
        # request.POST would parse/consume JSON before our bounded strict parser,
        # discarding duplicate-key and original-byte information.
        return super().enforce_csrf(request._request)


class ManualPlanAPIView(APIView):
    authentication_classes = [ManualPlanSessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    def handle_exception(self, error):
        if isinstance(error, RequestDataTooBig):
            error = ManualPlanError("REQUEST_TOO_LARGE")
        if not isinstance(error, ManualPlanError):
            error = ManualPlanError("UNAVAILABLE")
        return Response({"error": error.code}, status=error.status_code)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class ManualPlanSaveEndpoint(ManualPlanAPIView):
    http_method_names = ["post"]

    def post(self, request, slug, initiative_id):
        from .services import save_manual_plan

        require(not request.query_params, "REQUEST_INVALID")
        require(request.content_type == "application/json", "REQUEST_INVALID")
        raw = request._request.read(65537)
        command = parse_save(
            initiative_id=initiative_id,
            raw=raw,
            if_match=request.headers.get("If-Match"),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        result = save_manual_plan(request=request, workspace_slug=slug, command=command)
        response = Response(result.data, status=result.status_code)
        response["ETag"] = f'"curve-initiative:{initiative_id}:v{result.initiative_version}"'
        response["Location"] = (
            f"/api/v1/workspaces/{quote(slug, safe='')}/curve/initiatives/{initiative_id}/"
            f"manual-plan-drafts/v2/revisions/{result.data['id']}/"
        )
        return response


class ManualPlanReadEndpoint(ManualPlanAPIView):
    http_method_names = ["get", "head"]
    action = "READ_CURRENT"

    def get(self, request, slug, initiative_id, revision_id=None):
        from .reads import read_manual_plan

        result = read_manual_plan(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            action=self.action,
            revision_id=revision_id,
        )
        response = Response(result.data)
        response["ETag"] = f'"curve-initiative:{initiative_id}:v{result.initiative_version}"'
        return response
