# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session-only editor commands; route registration requires qualified integration."""

import re
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from plane.curve.feature_editor_input import FeatureEditorInputError
from plane.curve.feature_editor_read import read_feature_editors
from plane.curve.feature_editor_services import FeatureEditorCommandError, execute_feature_editor_command
from plane.curve.policy_services import CurvePolicyDenied, CurvePolicyResourceNotFound
from plane.curve.prd_commands import PrdCommandError
from plane.curve.product_format import ProductFormatUnavailable
from plane.curve.services import OptimisticConcurrencyError, ReplayResourceUnavailable
from plane.curve.views import CurveAPIView, CurveAPIRequestError, _required_idempotency_key


def _expected_version(request, grant_id):
    raw = request.headers.get("If-Match")
    if raw is None:
        raise CurveAPIRequestError(
            status_code=428, code="CURVE_PRECONDITION_REQUIRED", title="If-Match is required", field="If-Match"
        )
    match = re.fullmatch(r'"curve-feature_editor_grant:' + re.escape(str(grant_id)) + r':v([1-9][0-9]*)"', raw)
    if match is None or len(match.group(1)) > 19 or int(match.group(1)) > 9223372036854775807:
        raise CurveAPIRequestError(
            status_code=412,
            code="CURVE_PRECONDITION_FAILED",
            title="The editor grant version does not match",
            field="If-Match",
        )
    return int(match.group(1))


class FeatureEditorAPIView(CurveAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not getattr(settings, "CURVE_FEATURE_EDITOR_COMMANDS_ENABLED", False):
            raise CurvePolicyResourceNotFound

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def handle_exception(self, error):
        if isinstance(error, CurvePolicyDenied) and {
            "RESOURCE_UNAVAILABLE",
            "PRODUCT_UNAVAILABLE",
            "PRODUCT_FORMAT_UNAVAILABLE",
        }.intersection(error.reason_codes):
            error = CurvePolicyResourceNotFound()
        if isinstance(error, (ProductFormatUnavailable, ReplayResourceUnavailable)):
            error = CurvePolicyResourceNotFound()
        if isinstance(error, (FeatureEditorInputError, FeatureEditorCommandError)):
            return self.problem(self.request, status_code=422, code=error.code, title="The editor request is invalid")
        if isinstance(error, OptimisticConcurrencyError):
            return self.problem(
                self.request,
                status_code=412,
                code="CURVE_PRECONDITION_FAILED",
                title="The editor grant version does not match",
                field="If-Match",
            )
        if isinstance(error, PrdCommandError):
            return self.problem(
                self.request,
                status_code=503,
                code="FEATURE_EDITOR_INTEGRITY_UNAVAILABLE",
                title="Editor management is temporarily unavailable",
            )
        return super().handle_exception(error)

    def command(self, request, slug, product_id, *, grant_id=None):
        if request.query_params:
            raise CurveAPIRequestError(
                status_code=422, code="FEATURE_EDITOR_QUERY_INVALID", title="Command query parameters are unsupported"
            )
        version = None
        if grant_id is not None:
            version = _expected_version(request, grant_id)
        elif request.headers.get("If-Match") is not None:
            raise CurveAPIRequestError(
                status_code=422, code="FEATURE_EDITOR_COMMAND_INVALID", title="Grant creation does not accept If-Match"
            )
        result = execute_feature_editor_command(
            request=request,
            workspace_slug=slug,
            product_id=product_id,
            grant_id=grant_id,
            action="REVOKE_FEATURE_EDITOR" if grant_id is not None else "GRANT_FEATURE_EDITOR",
            payload=request.data,
            expected_version=version,
            raw_idempotency_key=_required_idempotency_key(request),
        )
        ref = result.resource_ref
        response = Response({"resource_ref": ref}, status=result.response_status)
        response["ETag"] = f'"curve-feature_editor_grant:{ref["resource_id"]}:v{ref["resource_version"]}"'
        response["Idempotent-Replay"] = "true" if result.replayed else "false"
        response["Location"] = (
            f"/api/v1/workspaces/{quote(slug, safe='')}/curve/products/{product_id}/"
            f"feature-editors/{ref['resource_id']}/"
        )
        return response


class FeatureEditorListEndpoint(FeatureEditorAPIView):
    def get(self, request, slug, product_id):
        query = request.query_params
        try:
            if set(query) - {"page_size", "after"} or any(len(query.getlist(key)) != 1 for key in query):
                raise ValueError
            raw = query.get("page_size", "50")
            if re.fullmatch(r"[1-9][0-9]{0,2}", raw) is None or int(raw) > 100:
                raise ValueError
            after = UUID(query["after"]) if "after" in query else None
        except (ValueError, TypeError, AttributeError):
            raise CurveAPIRequestError(
                status_code=422, code="FEATURE_EDITOR_QUERY_INVALID", title="The editor query is invalid"
            ) from None
        return Response(
            read_feature_editors(
                request=request, workspace_slug=slug, product_id=product_id, page_size=int(raw), after=after
            )
        )

    def post(self, request, slug, product_id):
        return self.command(request, slug, product_id)


class FeatureEditorDetailEndpoint(FeatureEditorAPIView):
    def get(self, request, slug, product_id, grant_id):
        if request.query_params:
            raise CurveAPIRequestError(
                status_code=422, code="FEATURE_EDITOR_QUERY_INVALID", title="The editor query is invalid"
            )
        result = read_feature_editors(request=request, workspace_slug=slug, product_id=product_id, grant_id=grant_id)
        response = Response(result)
        response["ETag"] = f'"curve-feature_editor_grant:{result["id"]}:v{result["version"]}"'
        return response

    def delete(self, request, slug, product_id, grant_id):
        return self.command(request, slug, product_id, grant_id=grant_id)
