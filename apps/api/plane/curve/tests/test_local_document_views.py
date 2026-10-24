# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811

import uuid

import pytest
from django.urls import reverse
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory
from plane.db.models import WorkspaceMember
from plane.curve.models import LocalPrdSource
from plane.curve.local_document_views import CurveLocalPrdUploadEndpoint, CurveLocalPrdSourceEndpoint
from plane.middleware.request_body_size import RequestBodySizeLimitMiddleware
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def configured(local, settings, tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    settings.CURVE_LOCAL_PRD_STORAGE_ROOT = str(root)
    return local, root


def post(local, body=b"# Synthetic requirements", *, csrf=True, anonymous=False, media="text/markdown", headers=None):
    url = reverse(
        "curve-local-prd-upload-v1", kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    )
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        url,
        body,
        content_type=media,
        HTTP_IF_MATCH=f'"{local.initiative.version}"',
        HTTP_X_CURVE_SOURCE_VERSION="0",
        HTTP_IDEMPOTENCY_KEY="http-upload",
        **(headers or {}),
    )
    request.user = AnonymousUser() if anonymous else local.user
    if csrf:
        request.COOKIES["csrftoken"] = "a" * 32
        request.META["HTTP_X_CSRFTOKEN"] = "a" * 32
    view = CurveLocalPrdUploadEndpoint.as_view()
    return RequestBodySizeLimitMiddleware(
        lambda req: view(req, slug=local.workspace.slug, initiative_id=local.initiative.id)
    )(request)


def get(local, source_id=None, *, content=False):
    route = (
        "curve-local-prd-content-v1"
        if content
        else ("curve-local-prd-source-v1" if source_id else "curve-local-prd-current-v1")
    )
    kwargs = dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    if source_id:
        kwargs["source_id"] = source_id
    request = APIRequestFactory().get(reverse(route, kwargs=kwargs))
    request.user = local.user
    return CurveLocalPrdSourceEndpoint.as_view(content=content)(request, **kwargs)


def test_authenticated_upload_metadata_content_and_replay(configured):
    local, root = configured
    empty = get(local)
    assert empty.status_code == 200 and empty.data["source"] is None and empty.data["upload_available"]
    body = b"<script>literal document text</script>\n# Requirements"
    saved = post(local, body)
    assert saved.status_code == 201, saved.data
    assert saved["Location"] == reverse(
        "curve-local-prd-source-v1",
        kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id, source_id=saved.data["id"]),
    )
    assert saved["ETag"] == f'"{local.initiative.version}"'
    read = get(local, saved.data["id"], content=True)
    assert read.status_code == 200 and read.content == body
    assert read["Content-Type"] == "text/plain; charset=utf-8"
    assert read["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert read["X-Content-Type-Options"] == "nosniff"
    assert saved["Cache-Control"] == read["Cache-Control"] == "no-store"
    assert get(local).data["source"] == saved.data
    replay = post(local, body)
    assert replay.status_code == 200 and replay.data == saved.data and replay["Idempotency-Replayed"] == "true"
    assert len(list(root.iterdir())) == 2


@pytest.mark.parametrize(
    "options,status", [({"csrf": False}, 403), ({"anonymous": True}, 401), ({"media": "application/json"}, 415)]
)
def test_transport_requires_session_csrf_and_supported_content(configured, options, status):
    local, root = configured
    response = post(local, **options)
    assert response.status_code == status, response.data
    assert not LocalPrdSource.objects.exists() and not list(root.iterdir())
    assert response["Cache-Control"] == "no-store"


def test_route_specific_upload_limit_overrides_generic_five_mb_limit(configured, settings):
    local, _ = configured
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
    response = post(local, b"x" * (5 * 1024 * 1024 + 1), media="text/plain")
    assert response.status_code == 201, response.data


def test_over_limit_upload_is_rejected_before_native_or_storage_effects(configured):
    local, root = configured
    response = post(local, b"x" * (10 * 1024 * 1024 + 1), media="text/plain")
    assert response.status_code == 413
    assert response["Cache-Control"] == "no-store"
    assert not list(root.iterdir()) and not LocalPrdSource.objects.exists()


def test_protected_content_rechecks_current_approver_access(configured):
    local, _ = configured
    saved = post(local)
    assert saved.status_code == 201
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
    response = get(local, saved.data["id"], content=True)
    assert response.status_code == 404 and response["Cache-Control"] == "no-store"
    assert b"Synthetic requirements" not in response.render().content


def test_missing_source_returns_private_unavailable(configured):
    local, _ = configured
    assert get(local, str(uuid.uuid4()), content=True).status_code == 404


def test_unconfigured_storage_does_not_offer_upload(configured, settings):
    local, _ = configured
    settings.CURVE_LOCAL_PRD_STORAGE_ROOT = None
    assert get(local).data["upload_available"] is False
    assert post(local).status_code == 503
