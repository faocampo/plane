# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Real PRD-service regressions against synthetic local scope metadata.

The normal C1 command cannot write after DRAFT. Deliberately injected scope rows
exercise old accepted commands, corruption, and trusted-runtime race hooks in the
existing PRD_REVIEW fixtures. Only this disposable PostgreSQL fixture disables
write triggers; the production guard is never patched or bypassed.
"""

from contextlib import contextmanager
from datetime import timedelta
import uuid

import pytest
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from plane.curve.models import Initiative, Operation, OutboxEvent, PrdAcceptedCommand, PrdReviewDecision
from plane.curve.prd_commands import PrdCommandError
from plane.curve.prd_completion import complete_prd_operation
from plane.curve.scope_prd_guard import require_legacy_prd_scope
from plane.curve.scope_proposal_models import ScopeProposal, ScopeProposalItem, ScopeProposalRevision
from plane.curve.scope_proposal_serialization import scope_membership_digest, serialize_scope_item
from plane.curve.tests.test_prd_accepted_commands import accept, fixture  # noqa: F401
from plane.curve.tests.test_prd_acceptance_api import post
from plane.curve.tests.test_prd_completion import SyntheticCompletionRuntime, real_digest  # noqa: F401
from plane.curve.tests.test_prd_lifecycle_repository import decide, raw_update, submit


pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]
CODE = "PRD_SCOPE_BRIDGE_UNAVAILABLE"


@pytest.fixture
def setup(fixture, settings):  # noqa: F811 - imported pytest fixture
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    runtime = SyntheticCompletionRuntime(fixture)
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = runtime
    settings.CURVE_PRD_COMPLETION_RUNTIME = runtime
    settings.CURVE_SCOPE_PROPOSALS_ENABLED = False
    client = APIClient()
    client.force_authenticate(user=fixture[4])
    return fixture, runtime, client


@contextmanager
def _synthetic_scope_write():
    """Fault injection only: scoped to this transaction and restored immediately."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SHOW session_replication_role")
        previous = cursor.fetchone()[0]
        cursor.execute("SET LOCAL session_replication_role = replica")
        try:
            yield
        finally:
            cursor.execute("SELECT set_config('session_replication_role', %s, true)", [previous])


def _raw_change(record, **changes):
    columns = ", ".join(f"{connection.ops.quote_name(key)} = %s" for key in changes)
    with _synthetic_scope_write(), connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {connection.ops.quote_name(record._meta.db_table)} SET {columns} WHERE id = %s",
            [*changes.values(), record.id],
        )


def _inject_scope(setup, purposes=("PROPOSED_DELIVERY",)):
    _, initiative, _, _, actor, _ = setup[0]
    now = timezone.now()
    head = ScopeProposal.objects.filter(initiative_id=initiative.id).first()
    number = head.version + 1 if head else 1
    revision_id = uuid.uuid4()
    proposal_id = head.id if head else uuid.uuid4()
    members = [
        ScopeProposalItem(
            workspace_id=initiative.workspace_id,
            revision_id=revision_id,
            association_id=uuid.uuid4(),
            association_version=1,
            provider_installation_id=uuid.uuid4(),
            source_project_id=uuid.uuid4(),
            source_issue_id=uuid.uuid4(),
            purpose=purpose,
            source_observed_at=now - timedelta(seconds=1),
            source_version="synthetic-observation-1",
            source_fingerprint="sha256:" + "b" * 64,
        )
        for purpose in purposes
    ]
    revision = ScopeProposalRevision(
        id=revision_id,
        workspace_id=initiative.workspace_id,
        proposal_id=proposal_id,
        initiative_id=initiative.id,
        product_id=initiative.product_id,
        version=number,
        initiative_version=max(number + 1, initiative.version),
        predecessor_id=head.current_revision_id if head else None,
        item_count=len(members),
        delivery_count=sum(member.purpose == "PROPOSED_DELIVERY" for member in members),
        membership_digest=scope_membership_digest([serialize_scope_item(member) for member in members]),
        created_by=actor.id,
        recorded_at=now,
        command_receipt_id=uuid.uuid4(),
    )
    with _synthetic_scope_write():
        if revision.initiative_version > initiative.version:
            raw_update(initiative.id, version=revision.initiative_version)
            initiative.refresh_from_db()
        revision.save_base(force_insert=True)
        for member in members:
            member.save_base(force_insert=True)
        if head:
            _raw_change(head, current_revision_id=revision.id, version=number)
            head.refresh_from_db()
        else:
            head = ScopeProposal(
                id=proposal_id,
                workspace_id=initiative.workspace_id,
                initiative_id=initiative.id,
                product_id=initiative.product_id,
                version=number,
                current_revision_id=revision.id,
            )
            head.save_base(force_insert=True)
    return head, revision, members


def _guard(setup, action="CURVE.PRD.APPROVE"):
    initiative = setup[0][1]
    with transaction.atomic():
        return require_legacy_prd_scope(
            workspace_id=initiative.workspace_id, initiative_id=initiative.id, action=action
        )


def _accepted(setup, action="approve", **kwargs):
    response = post(setup, action, **kwargs)
    assert response.status_code == 202, response.data
    return uuid.UUID(response.data["id"])


def _accepted_for_completion(setup, action="approve"):
    if action != "submit":
        return _accepted(setup, action)
    from plane.curve.models import PrdArtifact
    from plane.curve.tests.test_prd_checkpoint_models import capture_records

    binding, _, old, _, actor, _ = setup[0]
    artifact = PrdArtifact.objects.get(id=old.artifact_version.artifact_id)
    snapshot, version, checkpoint = capture_records(binding, artifact, old.id)
    version.created_by = checkpoint.submitted_or_approved_by = {"actor_type": "HUMAN", "actor_id": str(actor.id)}
    setup[1].capture = snapshot, version, checkpoint
    return _accepted(
        setup,
        action,
        body={
            "external_document_binding_id": str(binding.id),
            "evidence_snapshot_id": str(snapshot.id),
            "completeness_check_id": str(checkpoint.completeness_check_id),
        },
    )


def _complete(setup, operation_id):
    return complete_prd_operation(workspace_id=setup[0][5].id, operation_id=operation_id)


def _assert_scope_error(call):
    with pytest.raises(PrdCommandError) as error:
        call()
    assert error.value.code == CODE and error.value.status == 503
    assert str(error.value) == CODE


@pytest.mark.parametrize("action", ["submit", "approve"])
@pytest.mark.parametrize("enabled", [True, False])
def test_delivery_blocks_intake_independently_of_c1_flag(setup, settings, action, enabled):
    settings.CURVE_SCOPE_PROPOSALS_ENABLED = enabled
    _inject_scope(setup)
    response = post(setup, action)
    assert response.status_code == 503 and response.data["code"] == CODE
    assert setup[1].calls == 0
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == OutboxEvent.objects.count() == 0


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_accepted_replay_rechecks_current_delivery_before_reuse(setup, action):
    operation_id = _accepted(setup, action)
    _inject_scope(setup)
    response = post(setup, action)
    assert response.status_code == 503 and response.data["code"] == CODE
    assert setup[1].calls == 1
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == 1
    assert Operation.objects.get(id=operation_id).status == "PENDING"


@pytest.mark.parametrize("action", ["submit", "approve"])
@pytest.mark.parametrize("phase", ["prepare", "revalidate"])
def test_scope_rechecked_after_acceptance_runtime_hooks(setup, action, phase):
    if phase == "prepare":
        setup[1].on_prepare = lambda *_: _inject_scope(setup)
    else:

        def inject(_):
            _inject_scope(setup)
            return True

        setup[1].on_revalidate = inject
    response = post(setup, action)
    assert response.status_code == 503 and response.data["code"] == CODE
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == 0
    assert setup[1].committed == [None]


@pytest.mark.parametrize("action", ["submit", "approve"])
@pytest.mark.parametrize("purposes", [None, (), ("CONTEXT_EVIDENCE",)])
def test_unscoped_empty_and_context_only_keep_legacy_intake(setup, action, purposes):
    if purposes is not None:
        _inject_scope(setup, purposes)
    body = None
    if action == "submit":
        body = {
            "external_document_binding_id": str(setup[0][0].id),
            "evidence_snapshot_id": str(setup[0][2].evidence_snapshot_id),
            "completeness_check_id": str(uuid.uuid4()),
        }
    original = post(setup, action, body=body)
    replay = post(setup, action, body=body)
    assert original.status_code == replay.status_code == 202
    assert original.data["id"] == replay.data["id"]
    assert setup[1].calls == 1


@pytest.mark.parametrize("purposes", [(), ("CONTEXT_EVIDENCE",)])
def test_superseded_delivery_does_not_block_current_withdrawal_or_context(setup, purposes):
    _inject_scope(setup)
    _inject_scope(setup, purposes)
    assert _guard(setup) is None
    assert post(setup).status_code == 202
    assert ScopeProposalRevision.objects.count() == 2


@pytest.mark.parametrize("action", ["SUBMIT", "APPROVE"])
def test_direct_accepted_command_repository_has_the_same_guard(setup, action):
    _inject_scope(setup)
    _assert_scope_error(lambda: accept(setup[0], action))
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == 0


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_direct_lifecycle_repository_cannot_advance_delivery_scope(setup, action):
    from plane.curve.models import PrdArtifact

    _inject_scope(setup)
    binding, initiative, checkpoint, gate, _, _ = setup[0]

    def callback():
        if action == "approve":
            return decide(initiative, checkpoint, gate)
        artifact = PrdArtifact.objects.get(id=checkpoint.artifact_version.artifact_id)
        return submit(binding, artifact, initiative)

    _assert_scope_error(callback)
    initiative.refresh_from_db()
    assert initiative.version == 2 and initiative.state == "PRD_REVIEW"
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.parametrize("action", ["submit", "approve"])
@pytest.mark.parametrize("phase", ["before", "prepare", "revalidate"])
def test_completion_blocks_delivery_at_every_runtime_fence(setup, action, phase):
    operation_id = _accepted(setup, action)
    if phase == "before":
        _inject_scope(setup)
    elif phase == "prepare":
        setup[1].hook = lambda *_: _inject_scope(setup)
    else:

        def inject(*_):
            _inject_scope(setup)
            return True

        setup[1].local_hook = inject
    result = _complete(setup, operation_id)
    assert result["status"] == "FAILED" and result["effect_applied"] is False
    initiative = Initiative.objects.get(id=setup[0][1].id)
    assert initiative.version == 2 and initiative.state == "PRD_REVIEW"
    assert PrdReviewDecision.objects.count() == 0
    assert Operation.objects.get(id=operation_id).result_ref is None


@pytest.mark.parametrize("action", ["submit", "approve"])
@pytest.mark.parametrize("purposes", [None, (), ("CONTEXT_EVIDENCE",)])
def test_unscoped_empty_and_context_only_keep_legacy_completion(setup, purposes, action):
    if purposes is not None:
        _inject_scope(setup, purposes)
    operation_id = _accepted_for_completion(setup, action)
    first = _complete(setup, operation_id)
    replay = _complete(setup, operation_id)
    assert first["status"] == replay["status"] == "SUCCEEDED"
    assert first["effect_applied"] is True and replay["effect_applied"] is False
    assert PrdReviewDecision.objects.count() == (1 if action == "approve" else 0)


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_successful_completion_replay_cannot_bypass_current_delivery(setup, action):
    operation_id = _accepted_for_completion(setup, action)
    assert _complete(setup, operation_id)["status"] == "SUCCEEDED"
    _inject_scope(setup)
    _assert_scope_error(lambda: _complete(setup, operation_id))
    assert Operation.objects.get(id=operation_id).status == "SUCCEEDED"
    assert PrdReviewDecision.objects.count() == (1 if action == "approve" else 0)


def test_terminal_error_settlement_cannot_bypass_scope_guard(setup):
    operation_id = _accepted(setup)
    assert _complete(setup, operation_id)["status"] == "SUCCEEDED"
    _inject_scope(setup)
    setup[1].resolve_acl = lambda **_: (_ for _ in ()).throw(RuntimeError("synthetic resolver failure"))
    _assert_scope_error(lambda: _complete(setup, operation_id))


def test_final_worker_hook_cannot_commit_delivery_approval(setup):
    operation_id = _accepted(setup)
    original = setup[1].worker_authorization

    def inject_at_success(**kwargs):
        # The domain transition precedes the final worker-authorized Operation
        # transition. The final guard must roll both transitions back together.
        if Initiative.objects.get(id=setup[0][1].id).state == "PLANNING":
            _inject_scope(setup)
        return original(**kwargs)

    setup[1].worker_authorization = inject_at_success
    result = _complete(setup, operation_id)
    assert result["status"] == "FAILED" and result["effect_applied"] is False
    initiative = Initiative.objects.get(id=setup[0][1].id)
    operation = Operation.objects.get(id=operation_id)
    assert initiative.state == "PRD_REVIEW" and initiative.version == 2
    assert operation.result_ref is None and operation.status == "FAILED"
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.parametrize(
    "corruption",
    [
        "missing-head",
        "missing-revision",
        "head-product",
        "head-version",
        "revision-product",
        "revision-version",
        "revision-initiative-version",
        "missing-member",
        "extra-member",
        "digest",
        "delivery-count",
        "member-workspace",
        "member-fingerprint",
    ],
)
def test_damaged_current_scope_fails_closed(setup, corruption):
    head, revision, members = _inject_scope(setup, ("CONTEXT_EVIDENCE",))
    if corruption == "missing-head":
        with _synthetic_scope_write(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM curve_scope_proposal WHERE id = %s", [head.id])
    elif corruption == "missing-revision":
        _raw_change(head, current_revision_id=uuid.uuid4())
    elif corruption == "head-product":
        _raw_change(head, product_id=uuid.uuid4())
    elif corruption == "head-version":
        _raw_change(head, version=2)
    elif corruption == "revision-product":
        _raw_change(revision, product_id=uuid.uuid4())
    elif corruption == "revision-version":
        _raw_change(revision, version=2)
    elif corruption == "revision-initiative-version":
        _raw_change(revision, initiative_version=99)
    elif corruption == "missing-member":
        with _synthetic_scope_write(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM curve_scope_proposal_item WHERE id = %s", [members[0].id])
    elif corruption == "extra-member":
        _raw_change(revision, item_count=0)
    elif corruption == "digest":
        _raw_change(revision, membership_digest="sha256:" + "0" * 64)
    elif corruption == "delivery-count":
        _raw_change(revision, delivery_count=1)
    elif corruption == "member-workspace":
        _raw_change(members[0], workspace_id=uuid.uuid4())
    elif corruption == "member-fingerprint":
        _raw_change(members[0], source_fingerprint="sha256:" + "0" * 64)
    _assert_scope_error(lambda: _guard(setup))
    response = post(setup)
    assert response.status_code == 503 and response.data["code"] == CODE
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == 0


def test_guard_requires_initiative_transaction_even_when_unscoped(setup):
    initiative = setup[0][1]
    _assert_scope_error(
        lambda: require_legacy_prd_scope(
            workspace_id=initiative.workspace_id, initiative_id=initiative.id, action="CURVE.PRD.APPROVE"
        )
    )


def test_negative_review_is_not_a_scope_approval(setup):
    _inject_scope(setup)
    operation_id = _accepted(setup, "return-for-revision")
    assert _complete(setup, operation_id)["status"] == "SUCCEEDED"
    assert PrdReviewDecision.objects.get().state == "CHANGES_REQUESTED"


@pytest.mark.parametrize("phase", ["before", "prepare", "policy-failure"])
def test_scope_does_not_prevent_safe_requested_cancellation(setup, phase):
    operation_id = _accepted(setup)

    def cancel(*_):
        _inject_scope(setup)
        operation = Operation.objects.get(id=operation_id)
        operation.status = "CANCEL_REQUESTED"
        operation.aggregate_version += 1
        operation.save()

    if phase == "prepare":
        setup[1].hook = cancel
    else:
        cancel()
    if phase == "policy-failure":
        setup[1].resolve_acl = lambda **_: (_ for _ in ()).throw(RuntimeError("synthetic resolver failure"))
    result = _complete(setup, operation_id)
    assert result["status"] == "CANCELLED" and result["effect_applied"] is False
    operation = Operation.objects.get(id=operation_id)
    initiative = Initiative.objects.get(id=setup[0][1].id)
    assert operation.status == "CANCELLED" and operation.result_ref is None
    assert initiative.state == "PRD_REVIEW" and initiative.version == 2
    assert PrdReviewDecision.objects.count() == 0


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_final_repository_write_rechecks_scope_and_rolls_back(setup, monkeypatch, action):
    from plane.curve.models import PrdArtifact

    binding, initiative, checkpoint, gate, _, _ = setup[0]
    original = Initiative.save

    def save_then_inject(subject, *args, **kwargs):
        result = original(subject, *args, **kwargs)
        if subject.id == initiative.id and subject.version == 3:
            _inject_scope(setup)
        return result

    monkeypatch.setattr(Initiative, "save", save_then_inject)

    def transition():
        if action == "approve":
            return decide(initiative, checkpoint, gate)
        artifact = PrdArtifact.objects.get(id=checkpoint.artifact_version.artifact_id)
        return submit(binding, artifact, initiative)

    _assert_scope_error(transition)
    initiative.refresh_from_db()
    assert initiative.version == 2 and initiative.state == "PRD_REVIEW"
    assert PrdReviewDecision.objects.count() == 0
    assert not ScopeProposal.objects.exists()


@pytest.mark.parametrize("action", ["submit", "approve"])
@pytest.mark.parametrize("terminal", ["FAILED", "CANCELLED"])
@pytest.mark.parametrize("policy_failure", [False, True])
def test_delivery_scope_allows_no_effect_failed_or_cancelled_terminal_reads(setup, action, terminal, policy_failure):
    operation_id = _accepted(setup, action)
    operation = Operation.objects.get(id=operation_id)
    operation.status = terminal
    operation.completed_at = timezone.now()
    operation.error = {"code": "SYNTHETIC_TERMINAL", "retryable": False} if terminal == "FAILED" else None
    operation.save(update_fields=["status", "completed_at", "error", "updated_at"])
    original_version = operation.aggregate_version
    _inject_scope(setup)
    if policy_failure:
        setup[1].resolve_acl = lambda **_: (_ for _ in ()).throw(RuntimeError("synthetic resolver failure"))
    result = _complete(setup, operation_id)
    assert result["status"] == terminal and result["effect_applied"] is False
    operation.refresh_from_db()
    initiative = Initiative.objects.get(id=setup[0][1].id)
    assert operation.status == terminal and operation.aggregate_version == original_version
    assert operation.result_ref is None
    assert initiative.state == "PRD_REVIEW" and initiative.version == 2
    assert PrdReviewDecision.objects.count() == 0 and setup[1].preparations == 0


@pytest.mark.parametrize("action", ["submit", "approve"])
def test_delivery_scope_allows_authorized_failure_settlement_after_policy_error(setup, action):
    operation_id = _accepted(setup, action)
    _inject_scope(setup)
    setup[1].resolve_acl = lambda **_: (_ for _ in ()).throw(RuntimeError("synthetic resolver failure"))
    result = _complete(setup, operation_id)
    assert result["status"] == "FAILED" and result["effect_applied"] is False
    operation = Operation.objects.get(id=operation_id)
    initiative = Initiative.objects.get(id=setup[0][1].id)
    assert operation.status == "FAILED" and operation.result_ref is None
    assert operation.error == {"code": "PRD_COMPLETION_REJECTED", "retryable": False}
    assert initiative.state == "PRD_REVIEW" and initiative.version == 2
    assert PrdReviewDecision.objects.count() == 0 and setup[1].preparations == 0


def test_delivery_scope_failure_settlement_still_requires_current_worker_authority(setup):
    from plane.curve.prd_completion import PrdCompletionUnavailable

    operation_id = _accepted(setup)
    _inject_scope(setup)
    setup[1].service_active = False
    with pytest.raises(PrdCompletionUnavailable):
        _complete(setup, operation_id)
    assert Operation.objects.get(id=operation_id).status == "PENDING"
    assert PrdReviewDecision.objects.count() == 0
