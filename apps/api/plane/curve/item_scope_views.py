# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings
from rest_framework.response import Response

from plane.curve.item_creation_views import RoadmapItemCreationEndpoint
from plane.curve.item_local_material import ItemMaterialUnavailable
from plane.curve.item_scope_services import execute_item_scope_preparation
from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound
from plane.curve.roadmap_views import _expected_version
from plane.curve.views import CurveAPIView, CurveAPIRequestError, _required_idempotency_key


class RoadmapItemScopeEndpoint(RoadmapItemCreationEndpoint):
    http_method_names = ["post", "options"]

    def initial(self, request, *args, **kwargs):
        CurveAPIView.initial(self, request, *args, **kwargs)
        if getattr(settings, "CURVE_ITEM_SCOPE_PREPARATION_ENABLED", False) is not True:
            raise CurvePolicyResourceNotFound

    def handle_exception(self, error):
        if isinstance(error, ItemMaterialUnavailable) and str(error) == "ITEM_SCOPE_INPUT_INVALID":
            return self.problem(
                self.request, status_code=422, code="ITEM_SCOPE_INPUT_INVALID", title="Enter a valid scope document"
            )
        if isinstance(error, CurvePolicyDenied) and "LOCAL_SCOPE_PREPARATION_DISABLED" in error.reason_codes:
            error = CurvePolicyResourceNotFound()
        return super().handle_exception(error)

    def post(self, request, slug, product_id, roadmap_id):
        if request.query_params:
            raise CurveAPIRequestError(
                status_code=422, code="ITEM_SCOPE_QUERY_INVALID", title="Command query parameters are unsupported"
            )
        result = execute_item_scope_preparation(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            roadmap_id=roadmap_id,
            payload=request.data,
            expected_version=_expected_version(request, "roadmap", roadmap_id),
            raw_idempotency_key=_required_idempotency_key(request),
        )
        response = Response({"resource_ref": result.resource_ref}, status=result.response_status)
        response["Idempotent-Replay"] = "true" if result.replayed else "false"
        return response
