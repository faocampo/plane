# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F401, F811
from io import BytesIO
from types import SimpleNamespace
import pytest
from django.db import transaction
from plane.db.models import WorkspaceMember
from plane.curve.models import LocalPlanSubmission, LocalPlanDecision, DomainEvent, OutboxEvent, IdempotencyRecord
from plane.curve.local_plan_review_services import execute_local_plan_review
from plane.curve.local_document_store import LocalDocumentStore, LocalDocumentUnavailable, StoredDocument
from plane.curve.prd_commands import PrdCommandError
from plane.curve.services import IdempotencyConflict
from plane.curve.tests.test_local_plan_services import (
    upload_plan,
    context,
    configuration,
    bridge,
    two_stage,
    local,
    store,
    approved,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def plan(local, store, approved):
    return upload_plan(local, store, approved).data


def command(local, store, approved, plan, action="SUBMIT", submission=None, **overrides):
    reviewer = approved[1]["reviewers"][0]["approver_user_id"]
    actor = local.user if action == "SUBMIT" else next(user for user in local.reviewers if str(user.id) == reviewer)
    args = dict(
        request=SimpleNamespace(user=actor),
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        action=action,
        expected_version=local.initiative.version,
        plan_revision_id=plan["id"],
        plan_revision_digest=plan["digest"],
        prd_submission_id=approved[1]["id"],
        prd_submission_digest=approved[1]["digest"],
        prd_decision_id=approved[2]["id"],
        prd_decision_digest=approved[2]["digest"],
        raw_idempotency_key=action.lower() + plan["id"],
        store=store,
        submission_id=submission["id"] if submission else None,
        submission_digest=submission["digest"] if submission else None,
    )
    return execute_local_plan_review(**(args | overrides))


def test_submit_approve_and_exact_retries(local, store, approved, plan):
    subject = command(local, store, approved, plan)
    assert command(local, store, approved, plan).replayed
    decision = command(local, store, approved, plan, "APPROVE", subject.data)
    retry = command(local, store, approved, plan, "APPROVE", subject.data)
    assert retry.replayed and retry.data == decision.data
    assert decision.data["state"] == "APPROVED"
    assert LocalPlanSubmission.objects.count() == LocalPlanDecision.objects.count() == 1
    assert DomainEvent.objects.filter(aggregate_type__in=["LOCAL_PLAN_SUBMISSION", "LOCAL_PLAN_DECISION"]).count() == 2
    assert OutboxEvent.objects.filter(destination="CURVE_LOCAL_PLAN_REVIEW_V1").count() == 2
    local.initiative.refresh_from_db()
    assert local.initiative.state == "PLANNING" and local.initiative.version == decision.initiative_version


def test_changes_feedback_and_revised_plan_can_be_approved(local, store, approved, plan):
    subject = command(local, store, approved, plan).data
    returned = command(local, store, approved, plan, "REQUEST_CHANGES", subject, feedback="Add rollout steps.").data
    ref = returned["feedback"]
    assert (
        store.read(
            workspace_id=str(local.workspace.id),
            reference=StoredDocument(
                str(local.workspace.id), ref["object_id"], ref["digest"], ref["size_bytes"], ref["media_type"]
            ),
        )
        == b"Add rollout steps."
    )
    replacement = upload_plan(
        local,
        store,
        approved,
        expected_source_version=1,
        raw_idempotency_key="plan-replacement",
        stream=BytesIO(b"Plan with rollout steps"),
    ).data
    new_subject = command(local, store, approved, replacement).data
    accepted = command(local, store, approved, replacement, "APPROVE", new_subject).data
    assert accepted["plan_revision_id"] == replacement["id"]
    assert LocalPlanSubmission.objects.count() == LocalPlanDecision.objects.count() == 2
    assert command(local, store, approved, plan, "REQUEST_CHANGES", subject, feedback="Add rollout steps.").replayed


def test_changed_feedback_cannot_reuse_command_key(local, store, approved, plan):
    subject = command(local, store, approved, plan).data
    command(local, store, approved, plan, "REQUEST_CHANGES", subject, feedback="Add tests.")
    with pytest.raises(IdempotencyConflict):
        command(local, store, approved, plan, "REQUEST_CHANGES", subject, feedback="Changed feedback.")


def test_feedback_is_required_before_any_decision(local, store, approved, plan):
    subject = command(local, store, approved, plan).data
    with pytest.raises(LocalDocumentUnavailable):
        command(local, store, approved, plan, "REQUEST_CHANGES", subject, feedback="  ")
    assert not LocalPlanDecision.objects.exists()


def test_outbox_failure_rolls_back_submission_and_retry(local, store, approved, plan, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(OutboxEvent.objects, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic outbox"):
        command(local, store, approved, plan)
    assert not LocalPlanSubmission.objects.exists()
    assert not DomainEvent.objects.filter(aggregate_type="LOCAL_PLAN_SUBMISSION").exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PLAN.SUBMIT:").exists()


def test_access_revocation_during_feedback_prevents_decision(local, store, approved, plan, monkeypatch):
    subject = command(local, store, approved, plan).data
    original = LocalDocumentStore.put

    def revoke(self, **kwargs):
        assert not transaction.get_connection().in_atomic_block
        result = original(self, **kwargs)
        WorkspaceMember.objects.filter(workspace=local.workspace, member_id=subject["technical_approver_id"]).update(
            is_active=False
        )
        return result

    monkeypatch.setattr(LocalDocumentStore, "put", revoke)
    with pytest.raises(PrdCommandError):
        command(local, store, approved, plan, "REQUEST_CHANGES", subject, feedback="Add rollback steps.")
    assert not LocalPlanDecision.objects.exists()


def test_replay_requires_current_membership(local, store, approved, plan):
    command(local, store, approved, plan)
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)
    with pytest.raises(PrdCommandError):
        command(local, store, approved, plan)
