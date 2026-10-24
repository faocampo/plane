# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
"""Native lifecycle invariants; helper writes do not emulate command/audit acceptance."""

from importlib import import_module
from io import BytesIO
from types import SimpleNamespace
import uuid
import pytest
from django.db import transaction, connection, DatabaseError
from plane.curve.models import LocalPrdSubmission, LocalPrdDecision
from plane.curve.local_prd_review import create_submission, create_decision
from plane.curve.local_prd_review_authority import require_local_review_authority, submission_inputs
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store, upload  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def auth(local, source, action="SUBMIT", subject=None, user=None):
    return require_local_review_authority(
        request=SimpleNamespace(user=user or local.user),
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        action=action,
        expected_version=local.initiative.version,
        source_id=source["id"],
        source_digest=source["digest"],
        submission_id=str(subject.id) if subject else None,
        submission_digest=subject.digest if subject else None,
    )


def submit(local, source):
    with transaction.atomic():
        grant = auth(local, source)
        init = grant.document.context.initiative
        subject = LocalPrdSubmission.from_record(
            create_submission(
                **submission_inputs(grant.document),
                initiative_version=init.version,
                submitted_by=str(local.user.id),
                submitted_at="2026-10-21T12:00:00Z",
            )
        )
        subject.save()
        init.current_local_prd_submission_id = subject.id
        init.controlling_local_prd_decision_id = None
        init.state = "PRD_REVIEW"
        init.version += 1
        init.updated_by = dict(actor_type="HUMAN", actor_id=str(local.user.id))
        init.save(
            update_fields=[
                "current_local_prd_submission_id",
                "controlling_local_prd_decision_id",
                "state",
                "version",
                "updated_by",
                "updated_at",
            ]
        )
    local.initiative.refresh_from_db()
    return subject


def decide(local, source, subject, changes=False):
    with transaction.atomic():
        allowed = auth(local, source, "REQUEST_CHANGES" if changes else "APPROVE", subject)
        init = allowed.document.context.initiative
        value = create_decision(
            submission=subject.as_record(),
            initiative_version=init.version,
            state="CHANGES_REQUESTED" if changes else "APPROVED",
            decided_by=str(local.user.id),
            decided_at="2026-10-21T12:01:00Z",
            feedback=dict(
                object_id=str(uuid.uuid4()), digest="sha256:" + "a" * 64, size_bytes=20, media_type="text/plain"
            )
            if changes
            else None,
        )
        item = LocalPrdDecision.from_record(value, subject)
        item.save()
        init.controlling_local_prd_decision_id = item.id
        init.state = "ALIGNING" if changes else "PLANNING"
        init.version += 1
        init.updated_by = dict(actor_type="HUMAN", actor_id=str(local.user.id))
        init.save(update_fields=["controlling_local_prd_decision_id", "state", "version", "updated_by", "updated_at"])
    local.initiative.refresh_from_db()
    return item


def test_native_upload_submission_and_approval_enters_planning(local, store):
    source = upload(local, store).data
    subject = submit(local, source)
    assert local.initiative.state == "PRD_REVIEW"
    result = decide(local, source, subject)
    assert local.initiative.state == "PLANNING"
    assert str(local.initiative.controlling_local_prd_decision_id) == str(result.id)
    assert local.initiative.current_prd_checkpoint_id is None
    assert local.initiative.controlling_prd_decision_id is None


def test_return_replace_resubmit_approve_preserves_old_records(local, store):
    source = upload(local, store).data
    subject = submit(local, source)
    first = decide(local, source, subject, True)
    assert local.initiative.state == "ALIGNING"
    with pytest.raises(PrdCommandError, match="REPLACEMENT_REQUIRED"), transaction.atomic():
        auth(local, source)
    replacement = upload(
        local, store, expected_source_version=1, raw_idempotency_key="revised", stream=BytesIO(b"Updated PRD")
    ).data
    second = submit(local, replacement)
    decide(local, replacement, second)
    assert LocalPrdSubmission.objects.count() == 2 and LocalPrdDecision.objects.count() == 2
    first.refresh_from_db()
    assert first.state == "CHANGES_REQUESTED"
    assert local.initiative.state == "PLANNING"


def test_technical_reviewer_cannot_decide_product_review(local, store):
    source = upload(local, store).data
    subject = submit(local, source)
    with pytest.raises(PrdCommandError), transaction.atomic():
        auth(local, source, "APPROVE", subject, local.reviewers[1])


@pytest.mark.parametrize("damage", ["clear_submission", "planning_without_decision", "wrong_decision", "skip_version"])
def test_database_prevents_unproven_lifecycle(local, store, damage):
    source = upload(local, store).data
    submit(local, source)
    with pytest.raises(DatabaseError), transaction.atomic():
        init = local.initiative
        if damage == "clear_submission":
            init.current_local_prd_submission_id = None
            init.state = "ALIGNING"
        elif damage == "planning_without_decision":
            init.state = "PLANNING"
        elif damage == "wrong_decision":
            init.controlling_local_prd_decision_id = uuid.uuid4()
            init.state = "PLANNING"
        else:
            init.state = "PAUSED"
            init.paused_from_state = "PRD_REVIEW"
            init.version += 2
        init.save()


def test_pause_resume_cancel_preserves_submitted_subject(local, store):
    source = upload(local, store).data
    subject = submit(local, source)
    for state, paused in [("PAUSED", "PRD_REVIEW"), ("PRD_REVIEW", None), ("CANCELLED", None)]:
        with transaction.atomic():
            init = local.initiative
            init.state = state
            init.paused_from_state = paused
            init.version += 1
            init.save()
    assert str(local.initiative.current_local_prd_submission_id) == str(subject.id)


def test_reverse_refuses_active_local_review(local, store):
    source = upload(local, store).data
    submit(local, source)
    module = import_module("plane.curve.migrations.0033_local_prd_lifecycle")
    with (
        pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"),
        transaction.atomic(),
        connection.schema_editor() as editor,
    ):
        module.require_empty_reverse(None, editor)


def test_empty_lifecycle_migration_roundtrip():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0033_local_prd_lifecycle")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0032_local_prd_review")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0033_local_prd_lifecycle")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
