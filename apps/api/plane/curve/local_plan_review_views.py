# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Session-authenticated local Technical review and protected feedback."""

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from .local_document_views import LocalPrdEndpoint, _store, _version
from .local_document_store import StoredDocument
from .local_plan_authority import require_local_plan_authority
from .local_plan_models import LocalPlanSubmission, LocalPlanDecision
from .local_plan_review_services import execute_local_plan_review
from .prd_commands import PrdCommandError


def _authority(request, slug, initiative_id, **kwargs):
    return require_local_plan_authority(request=request, workspace_slug=slug, initiative_id=initiative_id, **kwargs)


class CurveLocalPlanReviewEndpoint(LocalPrdEndpoint):
    http_method_names = ["get", "head", "options"]

    def get(self, request, slug, initiative_id):
        with transaction.atomic():
            current = _authority(request, slug, initiative_id, action="READ")
            source = current.current_revision
            actions = []
            if source and getattr(settings, "CURVE_LOCAL_PRD_STORAGE_ROOT", None):
                for action in ("SUBMIT", "APPROVE", "REQUEST_CHANGES"):
                    try:
                        _authority(
                            request,
                            slug,
                            initiative_id,
                            action=action,
                            expected_version=current.context.initiative.version,
                            plan_revision_id=str(source.id),
                            plan_revision_digest=source.digest,
                            prd_submission_id=str(current.product_review.submission.id),
                            prd_submission_digest=current.product_review.submission.digest,
                            prd_decision_id=str(current.product_review.decision.id),
                            prd_decision_digest=current.product_review.decision.digest,
                            submission_id=str(current.submission.id)
                            if action != "SUBMIT" and current.submission
                            else None,
                            submission_digest=current.submission.digest
                            if action != "SUBMIT" and current.submission
                            else None,
                        )
                        actions.append(action)
                    except PrdCommandError as error:
                        if error.status not in {404, 409}:
                            raise
            response = Response(
                dict(
                    schema_version="curve.local-plan-review-current/v1-candidate",
                    initiative_version=current.context.initiative.version,
                    initiative_state=current.context.initiative.state,
                    revision=source.as_record() if source else None,
                    prd_submission=current.product_review.submission.as_record(),
                    prd_approval=current.product_review.decision.as_record(),
                    submission=current.submission.as_record() if current.submission else None,
                    decision=current.decision.as_record() if current.decision else None,
                    revision_is_current=current.revision_is_current,
                    available_actions=actions,
                )
            )
            response["ETag"] = f'"{current.context.initiative.version}"'
            return response


class CurveLocalPlanReviewCommandEndpoint(LocalPrdEndpoint):
    parser_classes = [JSONParser]
    http_method_names = ["post", "options"]

    def post(self, request, slug, initiative_id):
        if request.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        value = request.data
        base = {
            "action",
            "plan_revision_id",
            "plan_revision_digest",
            "prd_submission_id",
            "prd_submission_digest",
            "prd_decision_id",
            "prd_decision_digest",
        }
        if type(value) is not dict or value.get("action") not in {"SUBMIT", "APPROVE", "REQUEST_CHANGES"}:
            raise PrdCommandError("LOCAL_PLAN_REVIEW_COMMAND_INVALID", 422)
        fields = base if value["action"] == "SUBMIT" else base | {"submission_id", "submission_digest"}
        if value["action"] == "REQUEST_CHANGES":
            fields |= {"feedback"}
        if set(value) != fields:
            raise PrdCommandError("LOCAL_PLAN_REVIEW_COMMAND_INVALID", 422)
        version = _version(request.headers.get("If-Match"), etag=True)
        # Resolve native access before opening the private storage root.
        with transaction.atomic():
            _authority(request, slug, initiative_id, action="READ")
        with _store() as store:
            result = execute_local_plan_review(
                request=request,
                workspace_slug=slug,
                initiative_id=initiative_id,
                expected_version=version,
                raw_idempotency_key=request.headers.get("Idempotency-Key"),
                store=store,
                **value,
            )
        response = Response(result.data, status=200 if result.replayed else 201)
        response["ETag"] = f'"{result.initiative_version}"'
        response["Idempotency-Replayed"] = "true" if result.replayed else "false"
        response["Location"] = reverse(
            "curve-local-plan-review-record-v1",
            kwargs=dict(
                slug=slug,
                initiative_id=initiative_id,
                kind="submissions" if value["action"] == "SUBMIT" else "decisions",
                record_id=result.data["id"],
            ),
        )
        return response


class CurveLocalPlanReviewRecordEndpoint(LocalPrdEndpoint):
    http_method_names = ["get", "head", "options"]
    feedback = False

    def get(self, request, slug, initiative_id, kind, record_id):
        with transaction.atomic():
            before = _authority(request, slug, initiative_id, action="READ")
            if kind not in {"submissions", "decisions"} or (self.feedback and kind != "decisions"):
                raise PrdCommandError("LOCAL_PLAN_REVIEW_UNAVAILABLE", 404)
            model = LocalPlanSubmission if kind == "submissions" else LocalPlanDecision
            record = model.objects.filter(
                workspace_id=before.context.workspace.id, initiative_id=initiative_id, id=record_id
            ).first()
            if record is None:
                raise PrdCommandError("LOCAL_PLAN_REVIEW_UNAVAILABLE", 404)
            record.validate_metadata()
            data = record.as_record()
            if not self.feedback:
                response = Response(data)
                response["ETag"] = f'"{before.context.initiative.version}"'
                return response
            ref = data["feedback"]
            if ref is None:
                raise PrdCommandError("LOCAL_PLAN_REVIEW_UNAVAILABLE", 404)
        with _store() as store:
            body = store.read(
                workspace_id=data["workspace_id"],
                reference=StoredDocument(
                    data["workspace_id"], ref["object_id"], ref["digest"], ref["size_bytes"], ref["media_type"]
                ),
            )
        with transaction.atomic():
            after = _authority(request, slug, initiative_id, action="READ")
            if after.fence != before.fence:
                raise PrdCommandError("LOCAL_PLAN_REVIEW_SUBJECT_CHANGED", 409)
        response = HttpResponse(body, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="feedback.txt"'
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        response["ETag"] = f'"{ref["digest"]}"'
        return response
