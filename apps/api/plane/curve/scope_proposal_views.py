# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from .project_association_views import CurveProjectAssociationAPIView, _expected_version
from .scope_proposal_services import ScopeCommandError, parse_scope_body, read_scope_proposal, replace_scope_proposal
from rest_framework.response import Response


def _response(result):
    response = Response(result.data, status=result.response_status)
    response["ETag"] = f'"curve-initiative:{result.data["initiative_id"]}:v{result.data["initiative_version"]}"'
    return response


class CurveScopeProposalEndpoint(CurveProjectAssociationAPIView):
    http_method_names = ["get", "post", "head", "options"]

    def handle_exception(self, exc):
        if isinstance(exc, ScopeCommandError):
            return self.problem(
                self.request,
                status_code=exc.status,
                code=exc.code,
                title="The scope proposal command could not be completed",
            )
        return super().handle_exception(exc)

    def get(self, request, slug, initiative_id, revision_id=None):
        return _response(
            read_scope_proposal(
                request=request, workspace_slug=slug, initiative_id=initiative_id, revision_id=revision_id
            )
        )

    def post(self, request, slug, initiative_id):
        if request.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise ScopeCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        result = replace_scope_proposal(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            payload=parse_scope_body(request.body),
            expected_version=_expected_version(request, kind="initiative", resource_id=initiative_id),
            raw_idempotency_key=request.headers.get("Idempotency-Key"),
        )
        response = _response(result)
        response["Location"] = (
            f"/api/v1/workspaces/{slug}/curve/initiatives/{initiative_id}/scope-proposal/revisions/{result.data['id']}/"
        )
        return response


class CurveScopeProposalRevisionEndpoint(CurveScopeProposalEndpoint):
    http_method_names = ["get", "head", "options"]
