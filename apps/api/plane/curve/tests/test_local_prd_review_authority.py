# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from types import SimpleNamespace
from io import BytesIO
import uuid
import pytest
from django.db import transaction
from plane.db.models import WorkspaceMember, ProjectMember
from plane.curve.local_prd_review_authority import require_local_review_authority, submission_inputs
from plane.curve.local_prd_review import create_submission
from plane.curve.local_prd_review_models import LocalPrdSubmission
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store, upload  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def source(local, store):
    return upload(local, store).data


def authority(local, source, **overrides):
    arguments = dict(
        request=local.request,
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        action="SUBMIT",
        expected_version=local.initiative.version,
        source_id=source["id"],
        source_digest=source["digest"],
    )
    return require_local_review_authority(**(arguments | overrides))


def test_creator_can_submit_current_source_with_stable_native_fence(local, source):
    with transaction.atomic():
        before = authority(local, source)
    with transaction.atomic():
        after = authority(local, source)
    assert before.fence == after.fence
    assert before.submission is None
    assert not before.submission_is_current
    assert before.document.context.actor_id == local.user.id


def test_technical_approver_cannot_submit_for_creator(local, source):
    with pytest.raises(PrdCommandError), transaction.atomic():
        authority(local, source, request=SimpleNamespace(user=local.reviewers[1]))


@pytest.mark.parametrize("change", ["id", "digest", "version", "missing_version", "boolean_version"])
def test_submission_requires_exact_file_and_initiative_version(local, source, change):
    overrides = {
        "id": {"source_id": str(uuid.uuid4())},
        "digest": {"source_digest": "sha256:" + "b" * 64},
        "version": {"expected_version": local.initiative.version + 1},
        "missing_version": {"expected_version": None},
        "boolean_version": {"expected_version": True},
    }[change]
    with pytest.raises(PrdCommandError), transaction.atomic():
        authority(local, source, **overrides)


@pytest.mark.parametrize("change", ["actor_membership", "product_membership", "technical_access"])
def test_current_native_revocation_denies_submission(local, source, change):
    with transaction.atomic():
        authority(local, source)
    if change == "actor_membership":
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)
    elif change == "product_membership":
        WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[0]).update(is_active=False)
    else:
        ProjectMember.objects.filter(project=local.project, member=local.reviewers[1]).update(is_active=False)
    with pytest.raises(PrdCommandError), transaction.atomic():
        authority(local, source)


def record_submission(local, source):
    with transaction.atomic():
        allowed = authority(local, source)
        record = LocalPrdSubmission.from_record(
            create_submission(
                **submission_inputs(allowed.document),
                initiative_version=local.initiative.version,
                submitted_by=str(local.user.id),
                submitted_at="2026-10-21T12:01:00Z",
            )
        )
        record.save()
    return record


def test_read_reports_exact_submission_and_replacement_invalidates_it(local, source, store):
    record = record_submission(local, source)
    with transaction.atomic():
        result = authority(local, source, action="READ")
    assert str(result.submission.id) == str(record.id) and result.submission_is_current
    replacement = upload(
        local, store, expected_source_version=1, raw_idempotency_key="new-source", stream=BytesIO(b"New PRD")
    ).data
    with transaction.atomic():
        result = authority(local, replacement, action="READ")
    assert not result.submission_is_current
    assert str(result.submission.id) == str(record.id)


def test_duplicate_submission_is_denied_before_any_decision(local, source):
    record_submission(local, source)
    with pytest.raises(PrdCommandError, match="REPLACEMENT_REQUIRED"), transaction.atomic():
        authority(local, source)


@pytest.mark.parametrize("action", ["APPROVE", "REQUEST_CHANGES"])
def test_decision_requires_review_state_and_exact_submission(local, source, action):
    record = record_submission(local, source)
    with pytest.raises(PrdCommandError, match="STATE_CHANGED"), transaction.atomic():
        authority(
            local,
            source,
            request=SimpleNamespace(user=local.reviewers[0]),
            action=action,
            submission_id=str(record.id),
            submission_digest=record.digest,
        )


def test_review_authority_requires_native_transaction(local, source):
    with pytest.raises(PrdCommandError, match="TRANSACTION_REQUIRED"):
        authority(local, source)


def test_creator_who_is_product_reviewer_can_still_submit(local, source):
    assert local.reviewers[0].id == local.user.id
    with transaction.atomic():
        assert authority(local, source, request=SimpleNamespace(user=local.reviewers[0])).action == "SUBMIT"
