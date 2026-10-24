# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
"""Real local review commands, transaction effects and retry boundaries."""

from io import BytesIO
from types import SimpleNamespace
import pytest
from django.db import transaction
from plane.db.models import WorkspaceMember
from plane.curve.models import (
    LocalPrdSubmission,
    LocalPrdDecision,
    IdempotencyRecord,
    DomainEvent,
    OutboxEvent,
    AuditEvent,
)
from plane.curve.local_prd_review_services import execute_local_review
from plane.curve.prd_commands import PrdCommandError
from plane.curve.services import IdempotencyConflict
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store, upload  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def command(local, store, source, action="SUBMIT", subject=None, **overrides):
    args = dict(
        request=local.request,
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        action=action,
        expected_version=local.initiative.version,
        source_id=source["id"],
        source_digest=source["digest"],
        raw_idempotency_key=action,
        store=store,
        submission_id=subject["id"] if subject else None,
        submission_digest=subject["digest"] if subject else None,
    )
    result = execute_local_review(**(args | overrides))
    local.initiative.refresh_from_db()
    return result


def test_submit_approve_and_historical_replays(local, store):
    source = upload(local, store).data
    before = local.initiative.version
    submission = command(local, store, source)
    assert local.initiative.state == "PRD_REVIEW"
    decision_version = local.initiative.version
    approval = command(local, store, source, "APPROVE", submission.data)
    assert local.initiative.state == "PLANNING"
    assert command(local, store, source, expected_version=before).data == submission.data
    replay = command(local, store, source, "APPROVE", submission.data, expected_version=decision_version)
    assert replay.replayed and replay.data == approval.data
    assert LocalPrdSubmission.objects.count() == LocalPrdDecision.objects.count() == 1
    assert (
        DomainEvent.objects.filter(event_type__in=["CURVE.LOCAL_PRD.SUBMIT_V1", "CURVE.LOCAL_PRD.APPROVE_V1"]).count()
        == 2
    )
    assert OutboxEvent.objects.filter(destination="CURVE_LOCAL_PRD_REVIEW_V1").count() == 2
    assert AuditEvent.objects.filter(action="CURVE.LOCAL_PRD.APPROVE", outcome="NO_EFFECT").count() == 1


def test_return_replace_resubmit_approve(local, store):
    source = upload(local, store).data
    submission = command(local, store, source)
    returned = command(
        local, store, source, "REQUEST_CHANGES", submission.data, feedback="Clarify acceptance criteria."
    )
    assert local.initiative.state == "ALIGNING"
    assert returned.data["feedback"]["size_bytes"] == len(b"Clarify acceptance criteria.")
    replacement = upload(
        local,
        store,
        expected_source_version=1,
        raw_idempotency_key="replacement",
        stream=BytesIO(b"Revised requirements"),
    ).data
    revised = command(local, store, replacement, raw_idempotency_key="submit-revised")
    command(local, store, replacement, "APPROVE", revised.data)
    assert local.initiative.state == "PLANNING"
    assert LocalPrdSubmission.objects.count() == LocalPrdDecision.objects.count() == 2


def test_changed_request_cannot_reuse_key(local, store):
    source = upload(local, store).data
    command(local, store, source)
    with pytest.raises(IdempotencyConflict):
        command(local, store, source)
    assert LocalPrdSubmission.objects.count() == 1


def test_technical_reviewer_cannot_approve_product(local, store):
    source = upload(local, store).data
    submission = command(local, store, source)
    with pytest.raises(PrdCommandError):
        command(local, store, source, "APPROVE", submission.data, request=SimpleNamespace(user=local.reviewers[1]))
    assert not LocalPrdDecision.objects.exists()


@pytest.mark.parametrize("failure", ["outbox", "audit"])
def test_failure_rolls_back_all_command_effects(local, store, monkeypatch, failure):
    from plane.curve import local_prd_review_services as service

    source = upload(local, store).data
    before = local.initiative.version

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic transaction failure")

    if failure == "outbox":
        monkeypatch.setattr(OutboxEvent.objects, "create", fail)
    else:
        monkeypatch.setattr(service, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="synthetic transaction failure"):
        command(local, store, source)
    local.initiative.refresh_from_db()
    assert local.initiative.version == before and local.initiative.state == "ALIGNING"
    assert not LocalPrdSubmission.objects.exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PRD.SUBMIT:").exists()
    assert not DomainEvent.objects.filter(event_type="CURVE.LOCAL_PRD.SUBMIT_V1").exists()


def test_access_revocation_during_io_prevents_commit(local, store, monkeypatch):
    from plane.curve import local_prd_review_services as service

    source = upload(local, store).data
    original = service.read_local_document_snapshot

    def revoke(**kwargs):
        assert not transaction.get_connection().in_atomic_block
        result = original(**kwargs)
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
        return result

    monkeypatch.setattr(service, "read_local_document_snapshot", revoke)
    with pytest.raises(PrdCommandError):
        command(local, store, source)
    assert not LocalPrdSubmission.objects.exists()


def test_replay_requires_current_access(local, store):
    source = upload(local, store).data
    before = local.initiative.version
    command(local, store, source)
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)
    with pytest.raises(PrdCommandError):
        command(local, store, source, expected_version=before)
