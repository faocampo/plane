# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from types import SimpleNamespace
import uuid
import pytest
from django.db import transaction
from plane.db.models import WorkspaceMember
from plane.curve.local_plan_authority import require_local_plan_authority
from plane.curve.local_plan_review import create_plan_revision, validate_plan_revision
from plane.curve.local_prd_review import _pin
from plane.curve.local_document_store import LocalDocumentUnavailable
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store, upload  # noqa: F401
from plane.curve.tests.test_local_prd_review_services import command

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def approved(local, store):
    source = upload(local, store).data
    subject = command(local, store, source).data
    decision = command(local, store, source, "APPROVE", subject).data
    return source, subject, decision


def authorize(local, approved, **overrides):
    _, subject, decision = approved
    args = dict(
        request=local.request,
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        action="UPLOAD",
        expected_version=local.initiative.version,
        prd_submission_id=subject["id"],
        prd_submission_digest=subject["digest"],
        prd_decision_id=decision["id"],
        prd_decision_digest=decision["digest"],
    )
    with transaction.atomic():
        return require_local_plan_authority(**(args | overrides))


def test_local_approval_permits_plan_preparation_without_external_checkpoint(local, approved):
    result = authorize(local, approved)
    assert result.product_review.submission.digest == approved[1]["digest"]
    assert local.initiative.current_prd_checkpoint_id is None
    assert local.initiative.controlling_prd_decision_id is None


@pytest.mark.parametrize(
    "field", ["prd_submission_id", "prd_submission_digest", "prd_decision_id", "prd_decision_digest"]
)
def test_wrong_approval_pin_rejects_plan_preparation(local, approved, field):
    with pytest.raises(PrdCommandError, match="PRODUCT_APPROVAL_CHANGED"):
        authorize(local, approved, **{field: str(uuid.uuid4()) if field.endswith("_id") else "sha256:" + "0" * 64})


def test_reviewer_can_read_but_creator_owns_plan_upload(local, approved):
    actor = SimpleNamespace(user=local.reviewers[1])
    assert authorize(local, approved, action="READ", request=actor).action == "READ"
    with pytest.raises(PrdCommandError):
        authorize(local, approved, request=actor)


def test_current_membership_is_required(local, approved):
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.reviewers[1]).update(is_active=False)
    with pytest.raises(PrdCommandError):
        authorize(local, approved)


def test_unapproved_document_cannot_prepare_plan(local, store):
    source = upload(local, store).data
    command(local, store, source)
    with transaction.atomic(), pytest.raises(PrdCommandError, match="PRODUCT_APPROVAL_REQUIRED"):
        require_local_plan_authority(
            request=local.request, workspace_slug=local.workspace.slug, initiative_id=local.initiative.id, action="READ"
        )


def test_plan_revision_keeps_exact_prd_and_protected_material_pins(local, approved):
    source, subject, decision = approved
    record = create_plan_revision(
        submission=subject,
        approval=decision,
        initiative_version=local.initiative.version,
        version=1,
        predecessor_id=None,
        original=source["original"],
        snapshot=source["snapshot"],
        uploaded_by=str(local.user.id),
        uploaded_at="2099-01-01T00:00:00Z",
    )
    assert validate_plan_revision(record, submission=subject, approval=decision) == record
    assert record["prd_decision_id"] == decision["id"]
    for field, value in [
        ("prd_submission_digest", "sha256:" + "0" * 64),
        ("initiative_version", decision["initiative_version"]),
        ("predecessor_id", str(uuid.uuid4())),
        ("uploaded_at", "2000-01-01T00:00:00Z"),
    ]:
        changed = record | {field: value}
        changed["digest"] = _pin(changed)
        with pytest.raises(LocalDocumentUnavailable):
            validate_plan_revision(changed, submission=subject, approval=decision)
