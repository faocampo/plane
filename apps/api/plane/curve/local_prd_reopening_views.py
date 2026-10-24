# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Session-authenticated owner update action and retained reopening metadata."""

from django.db import transaction
from django.urls import reverse
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from .local_document_views import LocalPrdEndpoint, _version
from .local_prd_review_authority import require_local_review_authority
from .local_prd_reopening_authority import require_local_reopening_authority
from .local_prd_reopening_models import LocalPrdReopening
from .local_prd_reopening_services import execute_local_reopening
from .prd_commands import PrdCommandError


def _read(request, slug, initiative_id):
    return require_local_review_authority(
        request=request, workspace_slug=slug, initiative_id=initiative_id, action="READ"
    )


class CurveLocalPrdReopeningEndpoint(LocalPrdEndpoint):
    parser_classes = [JSONParser]
    http_method_names = ["get", "head", "post", "options"]

    def get(self, request, slug, initiative_id):
        with transaction.atomic():
            current = _read(request, slug, initiative_id)
            init = current.document.context.initiative
            can_reopen = False
            if current.submission and current.decision and current.document.current_source:
                source = current.document.current_source
                try:
                    require_local_reopening_authority(
                        request=request,
                        workspace_slug=slug,
                        initiative_id=initiative_id,
                        expected_version=init.version,
                        source_id=str(source.id),
                        source_digest=source.digest,
                        submission_id=str(current.submission.id),
                        submission_digest=current.submission.digest,
                        decision_id=str(current.decision.id),
                        decision_digest=current.decision.digest,
                    )
                    can_reopen = True
                except PrdCommandError as error:
                    if error.status not in {404, 409}:
                        raise
            response = Response(
                dict(
                    schema_version="curve.local-prd-reopening-current/v1-candidate",
                    initiative_version=init.version,
                    initiative_state=init.state,
                    can_reopen=can_reopen,
                    reopening=current.reopening.as_record() if current.reopening else None,
                )
            )
            response["ETag"] = f'"{init.version}"'
            return response

    def post(self, request, slug, initiative_id):
        if request.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        data = request.data
        fields = {
            "action",
            "source_id",
            "source_digest",
            "submission_id",
            "submission_digest",
            "decision_id",
            "decision_digest",
        }
        if type(data) is not dict or set(data) != fields or data["action"] != "REOPEN":
            raise PrdCommandError("LOCAL_REOPENING_COMMAND_INVALID", 422)
        version = _version(request.headers.get("If-Match"), etag=True)
        result = execute_local_reopening(
            request=request,
            workspace_slug=slug,
            initiative_id=initiative_id,
            expected_version=version,
            raw_idempotency_key=request.headers.get("Idempotency-Key"),
            **{key: value for key, value in data.items() if key != "action"},
        )
        response = Response(result.data, status=200 if result.replayed else 201)
        response["ETag"] = f'"{result.initiative_version}"'
        response["Idempotency-Replayed"] = "true" if result.replayed else "false"
        response["Location"] = reverse(
            "curve-local-prd-reopening-record-v1",
            kwargs=dict(slug=slug, initiative_id=initiative_id, record_id=result.data["id"]),
        )
        return response


class CurveLocalPrdReopeningRecordEndpoint(LocalPrdEndpoint):
    http_method_names = ["get", "head", "options"]

    def get(self, request, slug, initiative_id, record_id):
        with transaction.atomic():
            current = _read(request, slug, initiative_id)
            record = LocalPrdReopening.objects.filter(
                workspace_id=current.document.context.workspace.id, initiative_id=initiative_id, id=record_id
            ).first()
            if record is None:
                raise PrdCommandError("LOCAL_REOPENING_UNAVAILABLE", 404)
            record.validate_metadata()
            response = Response(record.as_record())
            response["ETag"] = f'"{current.document.context.initiative.version}"'
            return response
