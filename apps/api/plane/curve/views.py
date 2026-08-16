# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceMemberPermission
from plane.curve.config import is_curve_enabled_for_workspace
from plane.db.models import Workspace


class CurveWorkspaceShellEndpoint(BaseAPIView):
    """Return the empty Curve workspace shell after Plane membership checks."""

    permission_classes = [IsAuthenticated, WorkspaceMemberPermission]

    def get(self, request, slug):
        if not is_curve_enabled_for_workspace(slug):
            raise NotFound()

        workspace = Workspace.objects.only("id").get(slug=slug)
        return Response(
            {
                "workspace_id": str(workspace.id),
                "workspace_slug": slug,
                "state": "EMPTY",
            },
            status=status.HTTP_200_OK,
        )
