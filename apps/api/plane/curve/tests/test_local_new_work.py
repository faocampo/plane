# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F401, F811
from copy import copy
from io import BytesIO
from importlib import import_module
from types import SimpleNamespace
import pytest
from django.db import connection, transaction, DatabaseError
from django.db.migrations.executor import MigrationExecutor
from plane.db.models import WorkspaceMember
from plane.curve.models import PolicyDecision, LocalPrdSubmission
from plane.curve.scope_proposal_models import ScopeProposal
from plane.curve.initiative_services import create_initiative, accept_initiative_refinement
from plane.curve.local_document_authority import require_local_document_authority
from plane.curve.local_document_store import LocalDocumentUnavailable
from plane.curve.local_prd_review import _pin, validate_submission
from plane.curve.local_prd_new_work import require_current_new_work_submission
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage
from plane.curve.tests.test_local_document_authority import local
from plane.curve.tests.test_local_document_services import store, upload
from plane.curve.tests.test_local_prd_review_services import command
from plane.curve.tests.test_local_plan_services import upload_plan
from plane.curve.tests.test_local_plan_review_services import command as plan_command
from plane.curve.tests.test_local_prd_reopening_commands import command as reopen
from plane.curve.tests.test_initiative_api import _payload

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def fresh(local):
    value = copy(local)
    value.initiative = create_initiative(
        request=local.request,
        workspace_slug=local.workspace.slug,
        payload=_payload(local.product, local.reviewers[:2], keyword="new-document-review"),
        raw_idempotency_key="create-new-document-review",
    ).initiative
    assert value.initiative.state == "DRAFT"
    assert not ScopeProposal.objects.filter(initiative_id=value.initiative.id).exists()
    return value


def align(fresh):
    accept_initiative_refinement(
        request=fresh.request,
        workspace_slug=fresh.workspace.slug,
        initiative_id=fresh.initiative.id,
        expected_version=fresh.initiative.version,
        raw_idempotency_key="align-new-document-review",
    )
    fresh.initiative.refresh_from_db()


def approve(fresh, store):
    source = upload(fresh, store).data
    align(fresh)
    submission = command(fresh, store, source).data
    decision = command(fresh, store, source, "APPROVE", submission).data
    return source, submission, decision


def test_new_initiative_upload_to_both_approvals_and_reopening(fresh, store):
    approved = approve(fresh, store)
    assert approved[1]["schema_version"] == "curve.local-prd-submission/v2-candidate"
    assert approved[1]["product_id"] == str(fresh.product.id)
    assert "scope_revision_id" not in approved[1]
    plan = upload_plan(fresh, store, approved).data
    submitted = plan_command(fresh, store, approved, plan).data
    decision = plan_command(fresh, store, approved, plan, "APPROVE", submitted).data
    assert decision["state"] == "APPROVED"
    assert not ScopeProposal.objects.filter(initiative_id=fresh.initiative.id).exists()
    reopen(fresh, approved)
    assert fresh.initiative.state == "ALIGNING"
    policies = PolicyDecision.objects.filter(resource_id=fresh.initiative.id, policy_key__startswith="CURVE_LOCAL_")
    assert set(policies.values_list("policy_version", flat=True)) == {2}
    assert policies.values("policy_key").distinct().count() == 5
    migration = import_module("plane.curve.migrations.0042_local_new_work_review")
    with (
        transaction.atomic(),
        connection.schema_editor() as editor,
        pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"),
    ):
        migration.require_empty_reverse(None, editor)


def test_new_initiative_changes_require_replacement_before_resubmission(fresh, store):
    source = upload(fresh, store).data
    align(fresh)
    submission = command(fresh, store, source).data
    command(fresh, store, source, "REQUEST_CHANGES", submission, feedback="Add acceptance criteria.")
    with pytest.raises(PrdCommandError, match="REPLACEMENT_REQUIRED"):
        command(fresh, store, source, raw_idempotency_key="reject-old-document")
    replacement = upload(
        fresh,
        store,
        expected_source_version=1,
        raw_idempotency_key="new-replacement",
        stream=BytesIO(b"# Revised requirements\nAcceptance criteria included."),
    ).data
    submitted = command(fresh, store, replacement, raw_idempotency_key="resubmit-new-document").data
    command(fresh, store, replacement, "APPROVE", submitted)
    assert fresh.initiative.state == "PLANNING"


@pytest.mark.parametrize("participant", [0, 1])
def test_new_initiative_upload_rechecks_both_reviewers(fresh, store, participant):
    WorkspaceMember.objects.filter(workspace=fresh.workspace, member=fresh.reviewers[participant]).update(
        is_active=False
    )
    with pytest.raises(PrdCommandError):
        upload(fresh, store)


def test_new_submission_cannot_forge_product_context(fresh, store):
    source = upload(fresh, store).data
    align(fresh)
    subject = command(fresh, store, source).data
    # Database insertion independently checks the current native Product pin.
    import uuid

    forged = dict(
        subject,
        id=str(uuid.uuid4()),
        initiative_version=subject["initiative_version"] + 10,
        product_version=subject["product_version"] + 1,
    )
    forged["digest"] = _pin(forged)
    with transaction.atomic(), pytest.raises(DatabaseError, match="LOCAL_NEW_WORK_CONTEXT_INVALID"):
        LocalPrdSubmission.from_record(forged).save()
    for extra in ({"scope_revision_id": str(uuid.uuid4())}, {"business_intent": "UNKNOWN"}):
        forged = subject | extra
        forged["digest"] = _pin(forged)
        with pytest.raises(LocalDocumentUnavailable):
            validate_submission(forged)


def test_new_work_migration_roundtrip():
    module = import_module("plane.curve.migrations.0042_local_new_work_review")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0041_local_prd_reopening_command")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0042_local_new_work_review")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
