# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
import pytest
from django.urls import reverse, resolve
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory
from plane.db.models import WorkspaceMember
from plane.curve.models import LocalPlanRevision
from plane.middleware.request_body_size import RequestBodySizeLimitMiddleware
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def configured(approved, settings, tmp_path):
    settings.CURVE_LOCAL_PRD_STORAGE_ROOT = str(tmp_path / "documents")
    return approved


def post(local, approved, *, body=b"# Implementation plan", csrf=True, anonymous=False, headers=None):
    _, subject, decision = approved
    path = reverse(
        "curve-local-plan-upload-v1", kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    )
    defaults = dict(
        HTTP_IF_MATCH=f'"{local.initiative.version}"',
        HTTP_X_CURVE_PLAN_VERSION="0",
        HTTP_IDEMPOTENCY_KEY="http-plan",
        HTTP_X_CURVE_PRD_SUBMISSION_ID=subject["id"],
        HTTP_X_CURVE_PRD_SUBMISSION_DIGEST=subject["digest"],
        HTTP_X_CURVE_PRD_DECISION_ID=decision["id"],
        HTTP_X_CURVE_PRD_DECISION_DIGEST=decision["digest"],
    )
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        path, body, content_type="text/markdown", **(defaults | (headers or {}))
    )
    request.user = AnonymousUser() if anonymous else local.user
    if csrf:
        request.COOKIES["csrftoken"] = "a" * 32
        request.META["HTTP_X_CSRFTOKEN"] = "a" * 32
    match = resolve(path)
    return RequestBodySizeLimitMiddleware(lambda req: match.func(req, **match.kwargs))(request)


def get(local, path=None):
    path = path or reverse(
        "curve-local-plan-current-v1", kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    )
    request = APIRequestFactory().get(path)
    request.user = local.user
    match = resolve(path)
    return match.func(request, **match.kwargs)


def test_current_upload_content_and_exact_retry(local, configured):
    current = get(local)
    assert current.status_code == 200, current.data
    assert current.data["revision"] is None and current.data["upload_available"]
    assert current.data["prd_approval"] == configured[2]
    body = b"<script>Literal implementation plan</script>"
    saved = post(local, configured, body=body)
    assert saved.status_code == 201, saved.data
    assert get(local, saved["Location"]).data == saved.data
    content = get(local, saved["Location"] + "content/")
    assert content.status_code == 200 and content.content == body
    assert content["Content-Type"] == "text/plain; charset=utf-8"
    assert content["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert content["Cache-Control"] == saved["Cache-Control"] == "no-store"
    replay = post(local, configured, body=body)
    assert replay.status_code == 200 and replay.data == saved.data and replay["Idempotency-Replayed"] == "true"
    assert LocalPlanRevision.objects.count() == 1


@pytest.mark.parametrize(
    "options,status",
    [
        ({"csrf": False}, 403),
        ({"anonymous": True}, 401),
        ({"headers": {"HTTP_X_CURVE_PLAN_VERSION": ""}}, 428),
        ({"headers": {"HTTP_X_CURVE_PRD_DECISION_DIGEST": "sha256:" + "0" * 64}}, 409),
    ],
)
def test_upload_rejects_missing_auth_or_wrong_pins(local, configured, options, status):
    response = post(local, configured, **options)
    assert response.status_code == status, response.data
    assert not LocalPlanRevision.objects.exists()


def test_plan_content_requires_current_access(local, configured):
    saved = post(local, configured)
    assert saved.status_code == 201
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
    response = get(local, saved["Location"] + "content/")
    assert response.status_code == 404 and response["Cache-Control"] == "no-store"


def test_upload_body_limit_is_local_plan_specific(local, configured):
    response = post(local, configured, body=b"x" * (10 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert b"LOCAL_PLAN_UPLOAD_TOO_LARGE" in response.content
    assert not LocalPlanRevision.objects.exists()
