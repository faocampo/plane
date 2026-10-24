# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
import pytest
from django.urls import reverse
from plane.curve.models import LocalPrdReopening
from plane.curve.tests.test_local_prd_review_views import request
from plane.curve.tests.test_local_prd_reopening_commands import subject
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def path(local):
    return reverse(
        "curve-local-prd-reopening-v1", kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    )


def test_owner_reopening_current_record_and_retry(local, approved):
    url = path(local)
    before = local.initiative.version
    current = request(local, url)
    assert current.status_code == 200 and current.data["can_reopen"] is True
    assert current["Cache-Control"] == "no-store"
    data = dict(action="REOPEN", **subject(approved))
    response = request(local, url, data=data)
    assert response.status_code == 201, response.data
    assert request(local, response["Location"]).data == response.data
    current = request(local, url)
    assert current.data["initiative_state"] == "ALIGNING"
    assert current.data["reopening"] == response.data and current.data["can_reopen"] is False
    replay = request(local, url, data=data, version=before)
    assert replay.status_code == 200 and replay.data == response.data
    assert replay["Idempotency-Replayed"] == "true"
    assert LocalPrdReopening.objects.count() == 1


def test_reopening_requires_csrf_and_closed_request(local, approved):
    data = dict(action="REOPEN", **subject(approved))
    assert request(local, path(local), data=data, csrf=False).status_code == 403
    assert request(local, path(local), data=data | {"extra": True}).status_code == 422
    assert not LocalPrdReopening.objects.exists()


def test_technical_reviewer_can_read_but_cannot_reopen(local, approved):
    local.user = local.reviewers[1]
    current = request(local, path(local))
    assert current.status_code == 200 and current.data["can_reopen"] is False
    response = request(local, path(local), data=dict(action="REOPEN", **subject(approved)))
    assert response.status_code == 404
    assert not LocalPrdReopening.objects.exists()
