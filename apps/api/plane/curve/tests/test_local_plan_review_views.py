# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F401, F811
import pytest
from django.urls import reverse, resolve
from rest_framework.test import APIRequestFactory
from plane.curve.tests.test_local_plan_views import (
    post,
    get,
    configured,
    context,
    configuration,
    bridge,
    two_stage,
    local,
    store,
    approved,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def review_get(local, user=None, path=None):
    path = path or reverse(
        "curve-local-plan-review-current-v1", kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    )
    request = APIRequestFactory().get(path)
    request.user = user or local.user
    match = resolve(path)
    return match.func(request, **match.kwargs)


def review_post(local, configured, plan, action="SUBMIT", subject=None, feedback=None, csrf=True, extra=None):
    reviewer = configured[1]["reviewers"][0]["approver_user_id"]
    actor = local.user if action == "SUBMIT" else next(user for user in local.reviewers if str(user.id) == reviewer)
    data = dict(
        action=action,
        plan_revision_id=plan["id"],
        plan_revision_digest=plan["digest"],
        prd_submission_id=configured[1]["id"],
        prd_submission_digest=configured[1]["digest"],
        prd_decision_id=configured[2]["id"],
        prd_decision_digest=configured[2]["digest"],
    )
    if subject:
        data.update(submission_id=subject["id"], submission_digest=subject["digest"])
    if action == "REQUEST_CHANGES":
        data["feedback"] = feedback
    data.update(extra or {})
    path = reverse(
        "curve-local-plan-review-command-v1", kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id)
    )
    request = APIRequestFactory(enforce_csrf_checks=True).post(
        path,
        data,
        format="json",
        HTTP_IF_MATCH=f'"{local.initiative.version}"',
        HTTP_IDEMPOTENCY_KEY=action.lower() + plan["id"],
    )
    request.user = actor
    if csrf:
        request.COOKIES["csrftoken"] = "a" * 32
        request.META["HTTP_X_CSRFTOKEN"] = "a" * 32
    match = resolve(path)
    return match.func(request, **match.kwargs)


def test_current_actions_submit_approve_and_replay(local, configured):
    plan = post(local, configured).data
    assert review_get(local).data["available_actions"] == ["SUBMIT"]
    saved = review_post(local, configured, plan)
    assert saved.status_code == 201, saved.data
    assert review_get(local, path=saved["Location"]).data == saved.data
    assert review_get(local).data["available_actions"] == []
    assert not get(local).data["upload_available"]
    retry_upload = post(local, configured)
    assert retry_upload.status_code == 200 and retry_upload["Idempotency-Replayed"] == "true"
    reviewer = next(user for user in local.reviewers if str(user.id) == saved.data["technical_approver_id"])
    assert review_get(local, user=reviewer).data["available_actions"] == ["APPROVE", "REQUEST_CHANGES"]
    decision = review_post(local, configured, plan, "APPROVE", saved.data)
    assert decision.status_code == 201, decision.data
    assert review_get(local, path=decision["Location"]).data == decision.data
    assert review_get(local, user=reviewer).data["available_actions"] == []
    retry = review_post(local, configured, plan, "APPROVE", saved.data)
    assert retry.status_code == 200 and retry.data == decision.data and retry["Idempotency-Replayed"] == "true"
    assert decision["Cache-Control"] == "no-store"
    assert decision["ETag"] == f'"{local.initiative.version}"'


def test_changes_feedback_is_private_plain_text(local, configured):
    plan = post(local, configured).data
    subject = review_post(local, configured, plan).data
    decision = review_post(
        local, configured, plan, "REQUEST_CHANGES", subject, feedback="<script>Keep as literal text</script>"
    )
    assert decision.status_code == 201, decision.data
    content = review_get(local, path=decision["Location"] + "feedback/")
    assert content.status_code == 200
    assert content.content == b"<script>Keep as literal text</script>"
    assert content["Content-Type"] == "text/plain; charset=utf-8"
    assert content["Content-Security-Policy"] == "sandbox; default-src 'none'"
    assert content["Cache-Control"] == "no-store"
    assert get(local).data["upload_available"]


@pytest.mark.parametrize("options,status", [({"csrf": False}, 403), ({"extra": {"hidden": "field"}}, 422)])
def test_commands_require_csrf_and_closed_request(local, configured, options, status):
    plan = post(local, configured).data
    response = review_post(local, configured, plan, **options)
    assert response.status_code == status, response.data
