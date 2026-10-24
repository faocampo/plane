# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Authenticated local implementation-plan upload and protected document reads."""

from io import BytesIO
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse
from rest_framework.response import Response
from .local_document_views import LocalPrdEndpoint, UnparsedDocumentUploadParser, _version, _store
from .local_document_capture import read_local_document_snapshot
from .local_document_store import StoredDocument
from .local_plan_authority import require_local_plan_authority
from .local_plan_models import LocalPlanRevision
from .local_plan_services import upload_local_plan
from .prd_commands import PrdCommandError

_TYPES = {"application/pdf": "plan.pdf", "text/plain": "plan.txt", "text/markdown": "plan.md"}


def _authority(request, slug, initiative_id, **kwargs):
    return require_local_plan_authority(request=request, workspace_slug=slug, initiative_id=initiative_id, **kwargs)


class CurveLocalPlanUploadEndpoint(LocalPrdEndpoint):
    parser_classes = [UnparsedDocumentUploadParser]
    http_method_names = ["post", "options"]

    def post(self, request, slug, initiative_id):
        media = request.content_type.split(";", 1)[0].strip().lower()
        if media not in _TYPES:
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        version = _version(request.headers.get("If-Match"), etag=True)
        revision = _version(request.headers.get("X-Curve-Plan-Version"))
        pins = {
            field: request.headers.get(header)
            for field, header in [
                ("prd_submission_id", "X-Curve-Prd-Submission-Id"),
                ("prd_submission_digest", "X-Curve-Prd-Submission-Digest"),
                ("prd_decision_id", "X-Curve-Prd-Decision-Id"),
                ("prd_decision_digest", "X-Curve-Prd-Decision-Digest"),
            ]
        }
        with transaction.atomic():
            _authority(request, slug, initiative_id, action="READ_UPLOAD_RESULT", expected_version=version, **pins)
        with _store() as store:
            result = upload_local_plan(
                request=request,
                workspace_slug=slug,
                initiative_id=initiative_id,
                expected_version=version,
                expected_source_version=revision,
                **pins,
                raw_idempotency_key=request.headers.get("Idempotency-Key"),
                filename=_TYPES[media],
                stream=BytesIO(request.body),
                store=store,
            )
        response = Response(result.data, status=200 if result.replayed else 201)
        response["Location"] = reverse(
            "curve-local-plan-revision-v1",
            kwargs=dict(slug=slug, initiative_id=initiative_id, revision_id=result.data["id"]),
        )
        response["ETag"] = f'"{result.initiative_version}"'
        response["Idempotency-Replayed"] = "true" if result.replayed else "false"
        return response


class CurveLocalPlanRevisionEndpoint(LocalPrdEndpoint):
    http_method_names = ["get", "head", "options"]
    content = False

    def get(self, request, slug, initiative_id, revision_id=None):
        with transaction.atomic():
            before = _authority(request, slug, initiative_id, action="READ")
            record = (
                before.current_revision
                if revision_id is None
                else LocalPlanRevision.objects.filter(
                    workspace_id=before.context.workspace.id, initiative_id=initiative_id, id=revision_id
                ).first()
            )
            if revision_id is not None and record is None:
                raise PrdCommandError("LOCAL_PLAN_UNAVAILABLE", 404)
            if record:
                record.validate_metadata()
            data = record.as_record() if record else None
            if not self.content:
                response = Response(
                    data
                    if revision_id
                    else dict(
                        schema_version="curve.local-plan-current/v1-candidate",
                        revision=data,
                        initiative_version=before.context.initiative.version,
                        prd_submission=before.product_review.submission.as_record(),
                        prd_approval=before.product_review.decision.as_record(),
                        upload_available=before.context.actor_id == before.context.initiative.creator_user_id
                        and bool(getattr(settings, "CURVE_LOCAL_PRD_STORAGE_ROOT", None))
                        and (
                            not before.revision_is_current
                            or before.submission is None
                            or (before.decision is not None and before.decision.state == "CHANGES_REQUESTED")
                        ),
                    )
                )
                response["ETag"] = f'"{before.context.initiative.version}"'
                return response
        if data is None:
            raise PrdCommandError("LOCAL_PLAN_UNAVAILABLE", 404)
        ref = data["snapshot"]
        with _store() as store:
            captured = read_local_document_snapshot(
                store=store,
                workspace_id=data["workspace_id"],
                reference=StoredDocument(
                    data["workspace_id"], ref["object_id"], ref["digest"], ref["size_bytes"], ref["media_type"]
                ),
            )
            # The snapshot must contain the exact original retained by this revision.
            original = data["original"]
            expected = StoredDocument(
                data["workspace_id"],
                original["object_id"],
                original["digest"],
                original["size_bytes"],
                original["media_type"],
            )
            if captured.source != expected:
                raise PrdCommandError("LOCAL_PLAN_DOCUMENT_UNAVAILABLE", 404)
            body = store.read(workspace_id=data["workspace_id"], reference=expected)
        with transaction.atomic():
            after = _authority(request, slug, initiative_id, action="READ")
            if before.fence != after.fence:
                raise PrdCommandError("LOCAL_PLAN_CHANGED", 409)
        media = expected.media_type
        response = HttpResponse(
            body, content_type="application/pdf" if media == "application/pdf" else "text/plain; charset=utf-8"
        )
        response["Content-Disposition"] = f'inline; filename="{_TYPES[media]}"'
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        response["ETag"] = f'"{expected.content_digest}"'
        return response
