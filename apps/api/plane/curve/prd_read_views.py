# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Authenticated metadata-only PRD read, disabled without a trusted runtime."""

import uuid

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .config import is_curve_enabled_for_workspace
from .prd_read_context import PrdReadUnavailable, read_prd_review_context


def resolve_prd_read_scope(*, request, workspace_slug, initiative_id):
    """Read only local identity/version columns; no protected metadata serializer."""
    # Lazy imports keep the projection and API policy seam independently testable.
    from plane.db.models import Workspace, WorkspaceMember
    from .models import Initiative

    user = request.user
    if not (user.is_authenticated and user.is_active and not getattr(user, "is_bot", True)):
        raise PrdReadUnavailable
    workspace = Workspace.objects.filter(slug=workspace_slug).values("id").first()
    if (
        workspace is None
        or not WorkspaceMember.objects.filter(
            workspace_id=workspace["id"],
            member_id=user.id,
            is_active=True,
            member__is_active=True,
            member__is_bot=False,
        ).exists()
    ):
        raise PrdReadUnavailable
    initiative = (
        Initiative.objects.filter(workspace_id=workspace["id"], id=initiative_id)
        .values("version", "pending_scope_reopening_id")
        .first()
    )
    if initiative is None or initiative["pending_scope_reopening_id"] is not None:
        # The retained checkpoint is historical while reopening is pending.
        # The old closed metadata DTO cannot truthfully label this state.
        raise PrdReadUnavailable
    return {
        "workspace_id": str(workspace["id"]),
        "initiative_id": str(uuid.UUID(str(initiative_id))),
        "actor_id": str(uuid.UUID(str(user.id))),
        "initiative_version": initiative["version"],
    }


class CurvePrdReviewContextEndpoint(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]
    http_method_names = ["get", "head", "options"]

    def get(self, request, slug, initiative_id):
        if not is_curve_enabled_for_workspace(slug) or getattr(settings, "CURVE_PRD_READ_ENABLED", False) is not True:
            raise PrdReadUnavailable
        runtime = getattr(settings, "CURVE_PRD_READ_RUNTIME", None)
        result = read_prd_review_context(
            resolve_scope=lambda: resolve_prd_read_scope(
                request=request, workspace_slug=slug, initiative_id=initiative_id
            ),
            runtime=runtime,
            clock=lambda: timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        )
        return Response(result)

    def handle_exception(self, error):
        # A fixed non-enumerating failure for missing/denied/unavailable reads.
        # Do not invoke generic exception renderers/loggers with protected detail.
        return Response(
            {
                "type": "urn:curve:problem:prd-context-unavailable",
                "title": "PRD context unavailable",
                "status": 404,
                "code": "PRD_CONTEXT_UNAVAILABLE",
            },
            status=404,
            content_type="application/problem+json",
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
