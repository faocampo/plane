# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F401, F811
from types import SimpleNamespace
import pytest
from plane.curve.models import LocalPlanSubmission, LocalPlanDecision
from plane.curve.local_plan_review import create_plan_submission, create_plan_decision
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_local_plan_persistence import (
    make,
    context,
    configuration,
    bridge,
    two_stage,
    local,
    store,
    approved,
)
from plane.curve.tests.test_local_plan_authority import authorize

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def plan(local, approved):
    row = make(local, approved)
    row.save()
    return row


def submit(plan):
    record = create_plan_submission(
        plan=plan.as_record(),
        prd_submission=plan.prd_submission.as_record(),
        prd_approval=plan.prd_decision.as_record(),
        initiative_version=plan.initiative_version,
        submitted_by=plan.payload["uploaded_by"],
        submitted_at="2099-01-01T00:01:00Z",
    )
    row = LocalPlanSubmission.from_record(record, plan)
    row.save()
    return row


def decide(plan, submission, state):
    value = create_plan_decision(
        plan=plan.as_record(),
        prd_submission=plan.prd_submission.as_record(),
        prd_approval=plan.prd_decision.as_record(),
        submission=submission.as_record(),
        initiative_version=plan.initiative_version,
        state=state,
        decided_by=submission.payload["technical_approver_id"],
        decided_at="2099-01-01T00:02:00Z",
        feedback=None
        if state == "APPROVED"
        else dict(
            object_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            digest="sha256:" + "1" * 64,
            size_bytes=12,
            media_type="text/plain",
        ),
    )
    row = LocalPlanDecision.from_record(value, submission)
    row.save()
    return row


def pins(plan, submission=None):
    result = dict(plan_revision_id=str(plan.id), plan_revision_digest=plan.digest)
    if submission:
        result.update(submission_id=str(submission.id), submission_digest=submission.digest)
    return result


def test_creator_can_submit_current_plan_and_other_reviewer_cannot(local, approved, plan):
    assert authorize(local, approved, action="SUBMIT", **pins(plan)).revision_is_current
    with pytest.raises(PrdCommandError, match="UNAVAILABLE"):
        authorize(local, approved, action="SUBMIT", request=SimpleNamespace(user=local.reviewers[1]), **pins(plan))
    with pytest.raises(PrdCommandError, match="REVISION_CHANGED"):
        authorize(local, approved, action="SUBMIT", **(pins(plan) | {"plan_revision_digest": "sha256:" + "0" * 64}))


def test_only_assigned_technical_reviewer_can_decide_pending_submission(local, approved, plan):
    subject = submit(plan)
    actor = SimpleNamespace(
        user=next(user for user in local.reviewers if str(user.id) == subject.payload["technical_approver_id"])
    )
    assert str(authorize(local, approved, action="APPROVE", request=actor, **pins(plan, subject)).submission.id) == str(
        subject.id
    )
    assert authorize(local, approved, action="REQUEST_CHANGES", request=actor, **pins(plan, subject)).decision is None
    with pytest.raises(PrdCommandError, match="UNAVAILABLE"):
        authorize(local, approved, action="APPROVE", **pins(plan, subject))
    with pytest.raises(PrdCommandError, match="SUBJECT_CHANGED"):
        authorize(
            local,
            approved,
            action="APPROVE",
            request=actor,
            **(pins(plan, subject) | {"submission_digest": "sha256:" + "0" * 64}),
        )


def test_pending_review_locks_upload_and_resubmission(local, approved, plan):
    submit(plan)
    with pytest.raises(PrdCommandError, match="REVIEW_LOCKED"):
        authorize(local, approved)
    with pytest.raises(PrdCommandError, match="REPLACEMENT_REQUIRED"):
        authorize(local, approved, action="SUBMIT", **pins(plan))


@pytest.mark.parametrize("state", ["APPROVED", "CHANGES_REQUESTED"])
def test_decided_review_cannot_be_decided_twice_and_changes_allow_replacement(local, approved, plan, state):
    subject = submit(plan)
    decide(plan, subject, state)
    actor = SimpleNamespace(
        user=next(user for user in local.reviewers if str(user.id) == subject.payload["technical_approver_id"])
    )
    with pytest.raises(PrdCommandError, match="SUBJECT_CHANGED"):
        authorize(local, approved, action="APPROVE", request=actor, **pins(plan, subject))
    if state == "APPROVED":
        with pytest.raises(PrdCommandError, match="REVIEW_LOCKED"):
            authorize(local, approved)
    else:
        assert authorize(local, approved).decision.state == "CHANGES_REQUESTED"
        replacement = make(local, approved, plan)
        replacement.save()
        assert authorize(local, approved, action="SUBMIT", **pins(replacement)).submission is None
