# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from uuid import UUID

from django.conf import settings
from rest_framework.response import Response

from plane.curve.item_creation_views import RoadmapItemCreationEndpoint
from plane.curve.item_cancellation_services import cancel_item_creation
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.views import CurveAPIView, CurveAPIRequestError


class RoadmapItemCancellationEndpoint(RoadmapItemCreationEndpoint):
    http_method_names = ["post", "options"]

    def initial(self, request, *args, **kwargs):
        CurveAPIView.initial(self, request, *args, **kwargs)
        if getattr(settings, "CURVE_ITEM_CANCELLATION_ENABLED", False) is not True:
            raise CurvePolicyResourceNotFound

    def post(self, request, slug, product_id, roadmap_id):
        key = request.headers.get("Idempotency-Key")
        try:
            if (
                request.query_params
                or type(request.data) is not dict
                or request.data != {}
                or not key
                or str(UUID(key)) != key
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise CurveAPIRequestError(
                status_code=422,
                code="ITEM_CANCELLATION_REQUEST_INVALID",
                title="A valid creation identifier is required",
            ) from None
        return Response(
            cancel_item_creation(
                request=request, workspace_slug=slug, product_id=product_id, roadmap_id=roadmap_id, command_key=key
            )
        )
