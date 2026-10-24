# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
"""Database transition invariants; command authorization is tested separately."""

from importlib import import_module
from io import BytesIO
from types import SimpleNamespace
import pytest
from django.db import connection, transaction, DatabaseError
from django.utils import timezone
from plane.curve.models import LocalPrdReopening, LocalPrdSubmission, LocalPrdDecision
from plane.curve.local_prd_reopening import create_reopening
from plane.curve.local_prd_review import create_submission
from plane.curve.local_prd_review_authority import require_local_review_authority, submission_inputs
from plane.curve.local_plan_authority import require_local_plan_authority
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store, upload  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def reopen_record(local, approved):
    _, subject, decision = approved
    return LocalPrdReopening.from_record(
        create_reopening(
            submission=subject,
            decision=decision,
            initiative_version=local.initiative.version,
            reopened_by=str(local.user.id),
            reopened_at=timezone.now().isoformat(timespec="microseconds").replace("+00:00", "Z"),
        ),
        LocalPrdSubmission.objects.get(id=subject["id"]),
        LocalPrdDecision.objects.get(id=decision["id"]),
    )


def transition(local, *, wrong_actor=False, skip_version=False):
    init = local.initiative
    init.state = "ALIGNING"
    init.version += 2 if skip_version else 1
    init.updated_by = dict(actor_type="HUMAN", actor_id=str(local.reviewers[1].id if wrong_actor else local.user.id))
    init.save(update_fields=["state", "version", "updated_by", "updated_at"])


def reopen(local, approved):
    with transaction.atomic():
        record = reopen_record(local, approved)
        record.save()
        transition(local)
    local.initiative.refresh_from_db()
    return record


def test_reopening_retains_approval_and_blocks_technical_work(local, approved):
    before = local.initiative.version
    record = reopen(local, approved)
    assert local.initiative.state == "ALIGNING" and local.initiative.version == before + 1
    assert str(local.initiative.controlling_local_prd_decision_id) == str(record.decision_id)
    assert LocalPrdDecision.objects.get(id=record.decision_id).state == "APPROVED"
    with transaction.atomic(), pytest.raises(PrdCommandError):
        require_local_plan_authority(
            request=SimpleNamespace(user=local.user),
            workspace_slug=local.workspace.slug,
            initiative_id=local.initiative.id,
            action="READ",
        )


@pytest.mark.parametrize("damage", ["missing_record", "wrong_actor", "skip_version", "old_transaction"])
def test_reopening_requires_exact_transaction_evidence(local, approved, damage):
    if damage == "old_transaction":
        reopen_record(local, approved).save()
    with transaction.atomic(), pytest.raises(DatabaseError):
        if damage not in {"missing_record", "old_transaction"}:
            reopen_record(local, approved).save()
        transition(local, wrong_actor=damage == "wrong_actor", skip_version=damage == "skip_version")


def submit_raw(local):
    """Exercise SQL evidence independently of the command layer."""
    with transaction.atomic():
        authority = require_local_review_authority(
            request=SimpleNamespace(user=local.user),
            workspace_slug=local.workspace.slug,
            initiative_id=local.initiative.id,
            action="READ",
        )
        record = LocalPrdSubmission.from_record(
            create_submission(
                **submission_inputs(authority.document),
                initiative_version=local.initiative.version,
                submitted_by=str(local.user.id),
                submitted_at=timezone.now().isoformat(timespec="microseconds").replace("+00:00", "Z"),
            )
        )
        record.save()
        init = local.initiative
        init.current_local_prd_submission_id = record.id
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
    return record


def test_reopened_prd_requires_new_upload_before_resubmission(local, approved, store):
    reopen(local, approved)
    with pytest.raises(DatabaseError):
        submit_raw(local)
    local.initiative.refresh_from_db()
    upload(
        local,
        store,
        expected_source_version=1,
        raw_idempotency_key="reopened-replacement",
        stream=BytesIO(b"Revised approved requirements"),
    )
    new = submit_raw(local)
    assert str(new.id) != approved[1]["id"]
    assert LocalPrdDecision.objects.get(id=approved[2]["id"]).state == "APPROVED"


def test_reopened_prd_can_pause_resume_and_cancel(local, approved):
    reopen(local, approved)
    for state, paused in [("PAUSED", "ALIGNING"), ("ALIGNING", None), ("CANCELLED", None)]:
        with transaction.atomic():
            init = local.initiative
            init.state = state
            init.paused_from_state = paused
            init.version += 1
            init.save(update_fields=["state", "paused_from_state", "version", "updated_at"])


def test_lifecycle_reverse_preserves_reopening(local, approved):
    reopen(local, approved)
    module = import_module("plane.curve.migrations.0040_local_prd_reopening_lifecycle")
    with (
        transaction.atomic(),
        connection.schema_editor() as editor,
        pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"),
    ):
        module.require_empty_reverse(None, editor)


def test_empty_reopening_lifecycle_migration_roundtrip():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0040_local_prd_reopening_lifecycle")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0039_local_prd_reopening")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0040_local_prd_reopening_lifecycle")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)


def test_reopened_approval_is_not_current_and_native_resubmission_requires_replacement(local, approved, store):
    from plane.curve.tests.test_local_prd_review_services import command

    reopened = reopen(local, approved)
    with transaction.atomic():
        current = require_local_review_authority(
            request=local.request,
            workspace_slug=local.workspace.slug,
            initiative_id=local.initiative.id,
            action="READ",
        )
        assert current.submission_is_current is False
        assert str(current.reopening.id) == str(reopened.id)
    with pytest.raises(PrdCommandError, match="REPLACEMENT_REQUIRED"):
        command(local, store, approved[0], raw_idempotency_key="reopened-old-source")
    replacement = upload(
        local,
        store,
        expected_source_version=1,
        raw_idempotency_key="reopened-new-source",
        stream=BytesIO(b"Updated requirements after Product approval"),
    ).data
    new = command(local, store, replacement, raw_idempotency_key="reopened-new-submission")
    assert local.initiative.state == "PRD_REVIEW"
    with transaction.atomic():
        current = require_local_review_authority(
            request=local.request,
            workspace_slug=local.workspace.slug,
            initiative_id=local.initiative.id,
            action="READ",
        )
        assert current.submission_is_current is True
        assert current.reopening is None and current.decision is None
    command(local, store, replacement, "APPROVE", new.data, raw_idempotency_key="reopened-new-approval")
    assert local.initiative.state == "PLANNING"
    assert LocalPrdDecision.objects.get(id=approved[2]["id"]).state == "APPROVED"
