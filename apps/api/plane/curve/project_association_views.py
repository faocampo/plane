# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import re

from django.db import IntegrityError
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from .project_association_guards import AssociationBindingGuardUnavailable, AssociationHasActiveBindings
from .project_association_services import (
    AssociationCommandError,
    AssociationPreconditionRequired,
    associate_project,
    end_association,
    read_association,
)
from .services import OptimisticConcurrencyError, ReplayResourceUnavailable
from .views import CurveAPIView


def _expected_version(request, *, kind, resource_id):
    value = request.headers.get("If-Match")
    if value is None:
        raise AssociationPreconditionRequired("If-Match")
    match = re.fullmatch(r'"curve-' + kind + r':([0-9a-f-]{36}):v([1-9][0-9]{0,15})"', value)
    if match is None or match.group(1) != str(resource_id):
        raise OptimisticConcurrencyError
    version = int(match.group(2))
    if version > 9007199254740991:
        raise OptimisticConcurrencyError
    return version


def _response(result):
    response = Response(result.data, status=result.response_status)
    response["ETag"] = f'"curve-project-association:{result.data["id"]}:v{result.data["version"]}"'
    return response


class CurveProjectAssociationAPIView(CurveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    def handle_exception(self, exc):
        if isinstance(exc, AssociationCommandError):
            return self.problem(
                self.request,
                status_code=exc.status_code,
                code=exc.code,
                title="The project association command could not be completed",
                field=exc.field,
            )
        if isinstance(exc, AssociationBindingGuardUnavailable):
            return self.problem(
                self.request, status_code=503, code=exc.code, title="Association binding reconciliation is unavailable"
            )
        if isinstance(exc, (AssociationHasActiveBindings, IntegrityError)):
            return self.problem(
                self.request,
                status_code=409,
                code="PROJECT_ASSOCIATION_CONFLICT",
                title="The project association command conflicts with current state",
            )
        if isinstance(exc, ReplayResourceUnavailable):
            return self.problem(
                self.request,
                status_code=404,
                code="CURVE_RESOURCE_NOT_FOUND",
                title="The Curve resource is unavailable",
            )
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class CurveProjectAssociationCreateEndpoint(CurveProjectAssociationAPIView):
    http_method_names = ["post", "options"]

    def post(self, request, slug, product_id):
        result = associate_project(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            payload=request.data,
            expected_version=_expected_version(request, kind="product", resource_id=product_id),
            raw_idempotency_key=request.headers.get("Idempotency-Key"),
        )
        response = _response(result)
        response["Location"] = f"/api/v1/workspaces/{slug}/curve/project-associations/{result.data['id']}/"
        return response


class CurveProjectAssociationDetailEndpoint(CurveProjectAssociationAPIView):
    http_method_names = ["get", "head", "options"]

    def get(self, request, slug, association_id):
        return _response(read_association(request=request, workspace_slug=slug, association_id=association_id))


class CurveProjectAssociationEndEndpoint(CurveProjectAssociationAPIView):
    http_method_names = ["post", "options"]

    def post(self, request, slug, association_id):
        return _response(
            end_association(
                request=request,
                workspace_slug=slug,
                association_id=association_id,
                payload=request.data,
                expected_version=_expected_version(request, kind="project-association", resource_id=association_id),
                raw_idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )
