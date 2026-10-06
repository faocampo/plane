# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Candidate session-only, fixed-denial HTTP scope discovery."""

from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .scope_editor_read_v2 import ScopeEditorUnavailable, read_scope_editor_preconditions


class CurveScopeEditorPreconditionsV2Endpoint(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "head"]

    def get(self, request, slug, initiative_id):
        if request.query_params:
            raise ScopeEditorUnavailable
        data = read_scope_editor_preconditions(request=request, workspace_slug=slug, initiative_id=initiative_id)
        response = Response(data)
        response["ETag"] = f'"curve-initiative:{data["initiative_id"]}:v{data["initiative_version"]}"'
        return response

    def handle_exception(self, error):
        return Response({"error": "SCOPE_EDITOR_PRECONDITION_UNAVAILABLE"}, status=404)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
