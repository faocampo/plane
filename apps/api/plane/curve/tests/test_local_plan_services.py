# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from io import BytesIO
import pytest
from django.db import transaction
from plane.db.models import WorkspaceMember
from plane.curve.models import LocalPlanRevision, DomainEvent, OutboxEvent, IdempotencyRecord, AuditEvent
from plane.curve.local_plan_services import upload_local_plan
from plane.curve.local_document_store import LocalDocumentStore
from plane.curve.prd_commands import PrdCommandError
from plane.curve.services import IdempotencyConflict
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def upload_plan(local, store, approved, **overrides):
    _, subject, decision = approved
    args = dict(
        request=local.request,
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        expected_version=local.initiative.version,
        expected_source_version=0,
        prd_submission_id=subject["id"],
        prd_submission_digest=subject["digest"],
        prd_decision_id=decision["id"],
        prd_decision_digest=decision["digest"],
        raw_idempotency_key="plan-upload",
        filename="plan.md",
        stream=BytesIO(b"# Implementation plan"),
        store=store,
    )
    return upload_local_plan(**(args | overrides))


def test_upload_replay_and_replacement(local, store, approved):
    first = upload_plan(local, store, approved)
    retry = upload_plan(local, store, approved)
    assert retry.replayed and first.data == retry.data
    second = upload_plan(
        local,
        store,
        approved,
        expected_source_version=1,
        raw_idempotency_key="plan-revised",
        stream=BytesIO(b"Revised implementation plan"),
    )
    assert second.data["predecessor_id"] == first.data["id"] and second.data["version"] == 2
    assert LocalPlanRevision.objects.count() == 2
    assert DomainEvent.objects.filter(event_type="CURVE.LOCAL_PLAN.UPLOADED_V1").count() == 2
    assert AuditEvent.objects.filter(action="CURVE.LOCAL_PLAN.UPLOAD", outcome="NO_EFFECT").count() == 1
    assert OutboxEvent.objects.filter(destination="CURVE_LOCAL_PLAN_REVISION_V1").count() == 2


def test_changed_content_cannot_reuse_upload_key(local, store, approved):
    upload_plan(local, store, approved)
    with pytest.raises(IdempotencyConflict):
        upload_plan(local, store, approved, stream=BytesIO(b"Different plan"))
    assert LocalPlanRevision.objects.count() == 1


def test_stale_revision_cannot_replace_current_plan(local, store, approved):
    upload_plan(local, store, approved)
    with pytest.raises(PrdCommandError, match="REVISION_CHANGED"):
        upload_plan(local, store, approved, raw_idempotency_key="stale-new-key")
    assert LocalPlanRevision.objects.count() == 1


def test_access_revoked_during_storage_prevents_commit(local, store, approved, monkeypatch):
    original = LocalDocumentStore.put_snapshot

    def revoke(self, **kwargs):
        assert not transaction.get_connection().in_atomic_block
        result = original(self, **kwargs)
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
        return result

    monkeypatch.setattr(LocalDocumentStore, "put_snapshot", revoke)
    with pytest.raises(PrdCommandError):
        upload_plan(local, store, approved)
    assert not LocalPlanRevision.objects.exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PLAN.UPLOAD:").exists()


def test_outbox_failure_rolls_back_revision_audit_and_retry(local, store, approved, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(OutboxEvent.objects, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        upload_plan(local, store, approved)
    assert not LocalPlanRevision.objects.exists()
    assert not DomainEvent.objects.filter(event_type="CURVE.LOCAL_PLAN.UPLOADED_V1").exists()
    assert not AuditEvent.objects.filter(action="CURVE.LOCAL_PLAN.UPLOAD", outcome="SUCCEEDED").exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PLAN.UPLOAD:").exists()


def test_replay_requires_current_access_before_reading_upload(local, store, approved):
    upload_plan(local, store, approved)
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)

    class Unreadable:
        def read(self, *_args):
            pytest.fail("File read before authorization")

    with pytest.raises(PrdCommandError):
        upload_plan(local, store, approved, stream=Unreadable())


@pytest.mark.parametrize("state", [None, "APPROVED", "CHANGES_REQUESTED"])
def test_upload_retry_after_review_returns_original_without_replacing_plan(local, store, approved, state):
    from plane.curve.tests.test_local_plan_review_authority import submit, decide

    first = upload_plan(local, store, approved)
    plan = LocalPlanRevision.objects.get(id=first.data["id"])
    subject = submit(plan)
    if state:
        decide(plan, subject, state)
    retry = upload_plan(local, store, approved)
    assert retry.replayed and retry.data == first.data
    assert LocalPlanRevision.objects.count() == 1
    assert DomainEvent.objects.filter(event_type="CURVE.LOCAL_PLAN.UPLOADED_V1").count() == 1
    if state != "CHANGES_REQUESTED":
        with pytest.raises(PrdCommandError, match="REVIEW_LOCKED"):
            upload_plan(local, store, approved, raw_idempotency_key="new-replacement", expected_source_version=1)
