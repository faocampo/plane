# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plane.api.views.base import BaseAPIView
from plane.curve.permissions import (
    CurveCorePolicyPermission,
    query_authorization_receipt,
)


class CurveWorkspaceShellEndpoint(BaseAPIView):
    """Return the empty Curve shell projection after audited policy evaluation."""

    permission_classes = [IsAuthenticated, CurveCorePolicyPermission]
    curve_policy_action = "CURVE.SHELL.VIEW"
    curve_policy_resource_type = "WORKSPACE"

    def get(self, request, slug):
        receipt = query_authorization_receipt(request)
        return Response(dict(receipt.projection), status=status.HTTP_200_OK)
