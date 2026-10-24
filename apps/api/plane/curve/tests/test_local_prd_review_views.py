# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
import pytest
from django.urls import reverse, resolve
from rest_framework.test import APIRequestFactory
from plane.db.models import WorkspaceMember
from plane.curve.models import LocalPrdSubmission, LocalPrdDecision
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_views import configured, post  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def request(local, path=None, data=None, *, csrf=True, version=None):
    if path is None:
        path = reverse(
            "curve-local-prd-review-command-v1" if data is not None else "curve-local-prd-review-current-v1",
            kwargs=dict(slug=local.workspace.slug, initiative_id=local.initiative.id),
        )
    factory = APIRequestFactory(enforce_csrf_checks=True)
    req = (
        factory.get(path)
        if data is None
        else factory.post(
            path,
            data,
            format="json",
            HTTP_IF_MATCH=f'"{version or local.initiative.version}"',
            HTTP_IDEMPOTENCY_KEY=data.get("action", "test"),
        )
    )
    req.user = local.user
    if csrf:
        req.COOKIES["csrftoken"] = "a" * 32
        req.META["HTTP_X_CSRFTOKEN"] = "a" * 32
    match = resolve(path)
    result = match.func(req, **match.kwargs)
    local.initiative.refresh_from_db()
    return result


def payload(source, action="SUBMIT", subject=None, **extra):
    value = dict(action=action, source_id=source["id"], source_digest=source["digest"])
    if subject:
        value.update(submission_id=subject["id"], submission_digest=subject["digest"])
    return value | extra


def test_current_submit_approve_and_retry(configured):
    local, _ = configured
    assert request(local).data["available_actions"] == []
    source = post(local).data
    assert request(local).data["available_actions"] == ["SUBMIT"]
    version = local.initiative.version
    submitted = request(local, data=payload(source))
    assert submitted.status_code == 201, submitted.data
    assert request(local, submitted["Location"]).data == submitted.data
    current = request(local)
    assert current.data["available_actions"] == ["APPROVE", "REQUEST_CHANGES"]
    assert current.data["submission_is_current"]
    approved = request(local, data=payload(source, "APPROVE", submitted.data))
    assert approved.status_code == 201, approved.data
    assert request(local).data["initiative_state"] == "PLANNING"
    replay = request(local, data=payload(source), version=version)
    assert replay.status_code == 200 and replay.data == submitted.data
    assert replay["Idempotency-Replayed"] == "true"
    assert LocalPrdSubmission.objects.count() == LocalPrdDecision.objects.count() == 1


def test_changes_feedback_is_protected_plain_text(configured):
    local, _ = configured
    source = post(local).data
    subject = request(local, data=payload(source)).data
    note = "<script>Clarify acceptance criteria.</script>"
    response = request(local, data=payload(source, "REQUEST_CHANGES", subject, feedback=note))
    assert response.status_code == 201, response.data
    assert note not in str(response.data)
    path = response["Location"] + "feedback/"
    feedback = request(local, path)
    assert feedback.status_code == 200 and feedback.content == note.encode()
    assert feedback["Content-Type"] == "text/plain; charset=utf-8"
    assert feedback["Cache-Control"] == "no-store"
    assert feedback["Content-Security-Policy"] == "sandbox; default-src 'none'"
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)
    assert request(local, path).status_code == 404


def test_review_commands_require_csrf_and_closed_payload(configured):
    local, _ = configured
    source = post(local).data
    assert request(local, data=payload(source), csrf=False).status_code == 403
    assert request(local, data=payload(source, extra="unexpected")).status_code == 422
    assert not LocalPrdSubmission.objects.exists()


@pytest.mark.parametrize("note", [None, "", "   "])
def test_return_requires_feedback(configured, note):
    local, _ = configured
    source = post(local).data
    subject = request(local, data=payload(source)).data
    response = request(local, data=payload(source, "REQUEST_CHANGES", subject, feedback=note))
    assert response.status_code == 422, response.data
    assert not LocalPrdDecision.objects.exists()
    assert local.initiative.state == "PRD_REVIEW"
