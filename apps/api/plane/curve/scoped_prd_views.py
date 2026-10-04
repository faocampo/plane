# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Explicit, default-off LOCAL C2a command and protected read transport."""

from django.urls import reverse
from rest_framework.response import Response

from .prd_commands import PrdCommandError
from .prd_read_views import CurvePrdReviewContextEndpoint
from .prd_views import CurvePrdCommandEndpoint
from .scoped_prd_commands import parse_scoped_prd_command
from .scoped_prd_read import (
    _projection,
    read_scoped_prd_observation,
    read_scoped_prd_subject,
    scoped_prd_enabled,
)


def accept_scoped_prd_command(**kwargs):
    from .scoped_prd_acceptance import accept_scoped_prd_command as accept

    return accept(**kwargs)


def capture_scoped_prd_observation(**kwargs):
    from .scoped_prd_observations import capture_scoped_prd_observation as capture

    return capture(**kwargs)


class CurveScopedPrdCommandEndpoint(CurvePrdCommandEndpoint):
    http_method_names = ["post", "options"]

    def post(self, request, slug, initiative_id):
        if not scoped_prd_enabled(slug):
            raise PrdCommandError("NOT_FOUND", 404)
        if request.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        command = parse_scoped_prd_command(
            route=self.route,
            body=request.body,
            if_match=request.headers.get("If-Match"),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        if self.route == "observe":
            result = capture_scoped_prd_observation(
                request=request, workspace_slug=slug, initiative_id=initiative_id, command=command
            )
            if result.response_status != 201:
                raise PrdCommandError("SCOPED_PRD_RUNTIME_UNAVAILABLE", 503)
            response = Response(_projection(result.data, "observation"), status=201)
            response["Location"] = reverse(
                "curve-scoped-prd-observation",
                kwargs={"slug": slug, "initiative_id": initiative_id, "observation_id": result.data["id"]},
            )
        else:
            result = accept_scoped_prd_command(
                request=request, workspace_slug=slug, initiative_id=initiative_id, command=command
            )
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
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class CurveScopedPrdObservationEndpoint(CurvePrdReviewContextEndpoint):
    def get(self, request, slug, initiative_id, observation_id):
        return Response(
            read_scoped_prd_observation(
                request=request,
                workspace_slug=slug,
                initiative_id=initiative_id,
                observation_id=observation_id,
            )
        )


class CurveScopedPrdSubjectEndpoint(CurvePrdReviewContextEndpoint):
    def get(self, request, slug, initiative_id, scoped_subject_id=None):
        return Response(
            read_scoped_prd_subject(
                request=request,
                workspace_slug=slug,
                initiative_id=initiative_id,
                scoped_subject_id=scoped_subject_id,
            )
        )
