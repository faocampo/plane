# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-only Roadmap hierarchy HTTP adapters with exact command receipts."""

import re
import uuid
from urllib.parse import quote

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound
from plane.curve.product_format import ProductFormatUnavailable
from plane.curve.prd_commands import PrdCommandError
from plane.curve.roadmap_policy import RoadmapFormatUnavailable
from plane.curve.roadmap_read import RoadmapCursorStale, read_hierarchy
from plane.curve.roadmap_services import RoadmapCommandError, execute_hierarchy_command
from plane.curve.services import ReplayResourceUnavailable
from plane.curve.views import CurveAPIView, CurveAPIRequestError, _required_idempotency_key


def _expected_version(request, kind, identity):
    raw = request.headers.get("If-Match")
    if raw is None:
        raise CurveAPIRequestError(
            status_code=428, code="CURVE_PRECONDITION_REQUIRED", title="If-Match is required", field="If-Match"
        )
    match = re.fullmatch(r'"curve-' + kind + ":" + re.escape(str(identity)) + r':v([1-9][0-9]*)"', raw)
    if match is None or (len(match.group(1)) > 19 or int(match.group(1)) > 9223372036854775807):
        raise CurveAPIRequestError(
            status_code=412,
            code="CURVE_PRECONDITION_FAILED",
            title="The resource version does not match",
            field="If-Match",
        )
    return int(match.group(1))


def _pagination(request, *, milestones=False):
    if set(request.query_params) - {"page_size", "cursor"} or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise CurveAPIRequestError(status_code=422, code="ROADMAP_QUERY_INVALID", title="The query is invalid")
    try:
        raw = request.query_params.get("page_size", "50")
        if not re.fullmatch(r"[1-9][0-9]{0,2}", raw):
            raise ValueError
        size = int(raw)
        if size > 100:
            raise ValueError
        cursor = None
        if "cursor" in request.query_params:
            raw_cursor = request.query_params["cursor"]
            if milestones:
                version, position, identity = raw_cursor.split(":")
                if not re.fullmatch(r"[1-9][0-9]{0,18}", version) or not re.fullmatch(r"0|[1-9][0-9]{0,18}", position):
                    raise ValueError
                if max(int(version), int(position)) > 9223372036854775807:
                    raise ValueError
                cursor = (int(version), int(position), uuid.UUID(identity))
            else:
                cursor = uuid.UUID(raw_cursor)
    except (ValueError, TypeError, AttributeError) as error:
        raise CurveAPIRequestError(
            status_code=422, code="ROADMAP_QUERY_INVALID", title="The query is invalid"
        ) from error
    return {"page_size": size, "after": cursor}


class RoadmapAPIView(CurveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        # Registration alone never activates a new command surface.
        if not getattr(settings, "CURVE_ROADMAP_HIERARCHY_ENABLED", False):
            raise CurvePolicyResourceNotFound

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def handle_exception(self, error):
        if isinstance(error, RoadmapCursorStale):
            return self.problem(
                self.request,
                status_code=412,
                code="ROADMAP_CURSOR_STALE",
                title="Milestone order changed; refresh the list",
            )
        if isinstance(error, CurvePolicyDenied) and {"RESOURCE_UNAVAILABLE", "PRODUCT_UNAVAILABLE"}.intersection(
            error.reason_codes
        ):
            error = CurvePolicyResourceNotFound()
        if isinstance(error, RoadmapCommandError):
            return self.problem(self.request, status_code=422, code=error.code, title="The Roadmap request is invalid")
        if isinstance(error, (RoadmapFormatUnavailable, ProductFormatUnavailable, ReplayResourceUnavailable)):
            return self.problem(
                self.request,
                status_code=404,
                code="CURVE_RESOURCE_NOT_FOUND",
                title="The Curve resource is unavailable",
            )
        if isinstance(error, PrdCommandError):
            return self.problem(
                self.request,
                status_code=503,
                code="ROADMAP_INTEGRITY_UNAVAILABLE",
                title="Roadmap is temporarily unavailable",
            )
        return super().handle_exception(error)

    def command(self, request, slug, product_id, *, action, roadmap_id=None, milestone_id=None):
        if request.query_params:
            raise CurveAPIRequestError(
                status_code=422, code="ROADMAP_QUERY_INVALID", title="Command query parameters are unsupported"
            )
        version = None
        if action != "CREATE_ROADMAP":
            version = _expected_version(request, "milestone" if milestone_id else "roadmap", milestone_id or roadmap_id)
        elif request.headers.get("If-Match") is not None:
            raise CurveAPIRequestError(
                status_code=422, code="ROADMAP_QUERY_INVALID", title="Creation does not accept If-Match"
            )
        result = execute_hierarchy_command(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            roadmap_id=roadmap_id,
            milestone_id=milestone_id,
            action=action,
            payload=request.data,
            expected_version=version,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        response = Response({"resource_ref": result.resource_ref}, status=result.response_status)
        ref = result.resource_ref
        kind = ref["resource_type"].lower()
        response["ETag"] = f'"curve-{kind}:{ref["resource_id"]}:v{ref["resource_version"]}"'
        response["Idempotent-Replay"] = "true" if result.replayed else "false"
        base = f"/api/v1/workspaces/{quote(slug, safe='')}/curve/products/{product_id}/roadmaps/"
        response["Location"] = base + (
            f"{roadmap_id}/milestones/{ref['resource_id']}/" if kind == "milestone" else f"{ref['resource_id']}/"
        )
        return response

    def read(self, request, slug, product_id, *, roadmap_id=None, milestone_id=None, collection=False):
        pagination = _pagination(request, milestones=collection and roadmap_id is not None)
        if not collection and request.query_params:
            raise CurveAPIRequestError(
                status_code=422, code="ROADMAP_QUERY_INVALID", title="Detail query parameters are unsupported"
            )
        data = read_hierarchy(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            roadmap_id=roadmap_id,
            milestone_id=milestone_id,
            collection=collection,
            **pagination,
        )
        response = Response(data)
        if not collection:
            kind = "milestone" if milestone_id else "roadmap"
            response["ETag"] = f'"curve-{kind}:{data["id"]}:v{data["version"]}"'
        elif roadmap_id is not None:
            response["ETag"] = f'"curve-roadmap:{roadmap_id}:v{data["roadmap_version"]}"'
        return response


class RoadmapListEndpoint(RoadmapAPIView):
    def get(self, request, slug, product_id):
        return self.read(request, slug, product_id, collection=True)

    def post(self, request, slug, product_id):
        return self.command(request, slug, product_id, action="CREATE_ROADMAP")


class RoadmapDetailEndpoint(RoadmapAPIView):
    def get(self, request, slug, product_id, roadmap_id):
        return self.read(request, slug, product_id, roadmap_id=roadmap_id)

    def patch(self, request, slug, product_id, roadmap_id):
        return self.command(request, slug, product_id, roadmap_id=roadmap_id, action="UPDATE_ROADMAP")


class MilestoneListEndpoint(RoadmapAPIView):
    def get(self, request, slug, product_id, roadmap_id):
        return self.read(request, slug, product_id, roadmap_id=roadmap_id, collection=True)

    def post(self, request, slug, product_id, roadmap_id):
        return self.command(request, slug, product_id, roadmap_id=roadmap_id, action="CREATE_MILESTONE")


class MilestoneDetailEndpoint(RoadmapAPIView):
    def get(self, request, slug, product_id, roadmap_id, milestone_id):
        return self.read(request, slug, product_id, roadmap_id=roadmap_id, milestone_id=milestone_id)

    def patch(self, request, slug, product_id, roadmap_id, milestone_id):
        return self.command(
            request, slug, product_id, roadmap_id=roadmap_id, milestone_id=milestone_id, action="UPDATE_MILESTONE"
        )


class MilestoneOrderEndpoint(RoadmapAPIView):
    def post(self, request, slug, product_id, roadmap_id):
        return self.command(request, slug, product_id, roadmap_id=roadmap_id, action="REORDER_MILESTONES")
