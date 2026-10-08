# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Session-authenticated, non-enumerating association precondition GET."""

from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .project_association_read import AssociationReadUnavailable, read_project_association_preconditions


class CurveProjectAssociationPreconditionsEndpoint(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "head", "options"]

    def get(self, request, slug, product_id):
        if (
            set(request.query_params) != {"source_project_id"}
            or len(request.query_params.getlist("source_project_id")) != 1
        ):
            raise AssociationReadUnavailable
        data = read_project_association_preconditions(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            source_project_id=request.query_params["source_project_id"],
        )
        response = Response(data)
        response["ETag"] = f'"curve-product:{data["product_id"]}:v{data["product_version"]}"'
        return response

    def handle_exception(self, error):
        return Response(
            {
                "type": "urn:curve:problem:project-association-preconditions-unavailable",
                "title": "Project association preconditions unavailable",
                "status": 404,
                "code": "PROJECT_ASSOCIATION_PRECONDITIONS_UNAVAILABLE",
            },
            status=404,
            content_type="application/problem+json",
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
