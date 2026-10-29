# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-authenticated joint creation; disabled unless explicitly enabled."""

from urllib.parse import quote
import re
from uuid import UUID

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plane.curve.initiative_services import InitiativeKeywordConflict
from plane.curve.item_creation_input import ItemCreationInputError
from plane.curve.item_read import read_items
from plane.curve.item_creation_services import ItemPlacementConflict, execute_item_creation
from plane.curve.item_local_material import ItemMaterialUnavailable
from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound
from plane.curve.prd_commands import PrdCommandError
from plane.curve.roadmap_views import _expected_version
from plane.curve.services import OptimisticConcurrencyError, ReplayResourceUnavailable
from plane.curve.views import CurveAPIView, CurveAPIRequestError, _required_idempotency_key


class RoadmapItemCreationEndpoint(CurveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        flag = "CURVE_ITEM_READ_ENABLED" if request.method in {"GET", "HEAD"} else "CURVE_ITEM_CREATION_ENABLED"
        if getattr(settings, flag, False) is not True:
            raise CurvePolicyResourceNotFound

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def handle_exception(self, error):
        if isinstance(error, CurvePolicyDenied) and {
            "RESOURCE_UNAVAILABLE",
            "PRODUCT_UNAVAILABLE",
            "FORMAT_UNAVAILABLE",
            "PROTECTED_MATERIAL_UNAVAILABLE",
            "FEATURE_DISABLED",
        }.intersection(error.reason_codes):
            error = CurvePolicyResourceNotFound()
        if isinstance(error, ReplayResourceUnavailable):
            error = CurvePolicyResourceNotFound()
        if isinstance(error, ItemCreationInputError):
            return self.problem(
                self.request,
                status_code=422,
                code="ROADMAP_ITEM_COMMAND_INVALID",
                title="The Roadmap item request is invalid",
            )
        if isinstance(error, (InitiativeKeywordConflict, ItemPlacementConflict)):
            return self.problem(
                self.request,
                status_code=409,
                code=error.code,
                title="An item with this keyword or Feature placement already exists",
            )
        if isinstance(error, ItemMaterialUnavailable):
            return self.problem(
                self.request,
                status_code=409,
                code="ROADMAP_ITEM_MATERIAL_CHANGED",
                title="Scope document access changed; retry the request",
            )
        if isinstance(error, OptimisticConcurrencyError):
            return self.problem(
                self.request,
                status_code=412,
                code="CURVE_PRECONDITION_FAILED",
                title="The Roadmap version does not match",
                field="If-Match",
            )
        if isinstance(error, PrdCommandError):
            return self.problem(
                self.request,
                status_code=503,
                code="ROADMAP_ITEM_INTEGRITY_UNAVAILABLE",
                title="Roadmap item creation is temporarily unavailable",
            )
        return super().handle_exception(error)

    def get(self, request, slug, product_id, roadmap_id):
        query = request.query_params
        try:
            if set(query) - {"page_size", "after"} or any(len(query.getlist(key)) != 1 for key in query):
                raise ValueError
            size = query.get("page_size", "50")
            if re.fullmatch(r"[1-9][0-9]{0,2}", size) is None or int(size) > 100:
                raise ValueError
            after = UUID(query["after"]) if "after" in query else None
        except (ValueError, TypeError, AttributeError):
            raise CurveAPIRequestError(
                status_code=422, code="ROADMAP_ITEM_QUERY_INVALID", title="The Roadmap item query is invalid"
            ) from None
        return Response(
            read_items(
                request=request,
                workspace_slug=slug,
                product_id=product_id,
                roadmap_id=roadmap_id,
                page_size=int(size),
                after=after,
            )
        )

    def post(self, request, slug, product_id, roadmap_id):
        if request.query_params:
            raise CurveAPIRequestError(
                status_code=422, code="ROADMAP_ITEM_QUERY_INVALID", title="Command query parameters are unsupported"
            )
        result = execute_item_creation(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            roadmap_id=roadmap_id,
            payload=request.data,
            expected_version=_expected_version(request, "roadmap", roadmap_id),
            raw_idempotency_key=_required_idempotency_key(request),
        )
        ref = result.resource_ref
        response = Response({"resource_ref": ref}, status=result.response_status)
        response["ETag"] = f'"curve-roadmap-item:{ref["resource_id"]}:v{ref["resource_version"]}"'
        response["Idempotent-Replay"] = "true" if result.replayed else "false"
        response["Location"] = (
            f"/api/v1/workspaces/{quote(slug, safe='')}/curve/initiatives/{ref['initiative_ref']['resource_id']}/"
        )
        return response
