# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from contextlib import contextmanager
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

import pytest
from django.db import transaction, connections
from django.utils import timezone
from rest_framework.test import APIClient

from plane.db.models import WorkspaceMember
from plane.curve.models import Operation, PrdAcceptedCommand, PrdReviewDecision, DomainEvent, AuditEvent, PrdArtifact
from plane.curve.prd_completion import complete_prd_operation, PrdCompletionPreparation, PrdCompletionUnavailable
from plane.curve.services import sha256_digest
from plane.curve.tests.test_prd_accepted_commands import fixture  # noqa: F401
from plane.curve.tests.test_prd_acceptance_api import SyntheticRuntime, post
from plane.curve.tests.test_prd_checkpoint_models import capture_records
from plane.curve.tests.test_prd_lifecycle_repository import raw_update

pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]
BODY = b'{"text":"' + b"x" * 112 + b'"}'


@pytest.fixture(autouse=True)
def real_digest(monkeypatch):
    assert len(BODY) == 123
    monkeypatch.setattr("plane.curve.tests.test_prd_metadata_models.DIGEST", sha256_digest(BODY))


class SyntheticCompletionRuntime(SyntheticRuntime):
    def __init__(self, records):
        super().__init__()
        self.records = records
        self.preparations = 0
        self.retained = []
        self.hook = None
        self.local_hook = None
        self.service_active = True
        self.capture = None

    def worker_authorization(self, *, workspace_id, operation_id):
        now = timezone.now()
        actor = {"actor_type": "SERVICE", "actor_id": "synthetic-prd-worker"}
        return dict(
            workspace_id=workspace_id,
            operation_id=operation_id,
            actor=actor,
            authorization=dict(
                authorization_id="synthetic-prd-worker-grant",
                authorization_version=1,
                workspace_id=str(workspace_id),
                service=actor,
                active=self.service_active,
                allowed_actions=["CURVE.OPERATION.TRANSITION"],
                issued_at=(now - timedelta(seconds=1)).isoformat(),
                expires_at=(now + timedelta(minutes=1)).isoformat(),
            ),
        )

    @contextmanager
    def prepare_completion(self, *, command):
        assert not transaction.get_connection().in_atomic_block
        self.preparations += 1
        now = timezone.now()
        checkpoint = self.records[2]
        if self.capture is not None:
            snapshot, version, capture = self.capture
            snapshot.created_at = version.created_at = capture.recorded_at = now
            snapshot.digest = snapshot.compute_digest()
        proof = PrdCompletionPreparation(
            operation_id=command.operation_id,
            request_digest=command.request_digest,
            valid_from=now,
            valid_until=now + timedelta(minutes=1),
            checks={
                key: True
                for key in (
                    "provider_capability",
                    "storage_policy",
                    "source_access",
                    "evidence_access",
                    "body_access",
                    "readiness",
                )
            },
            rationale_bytes=None if command.action == "CURVE.PRD.SUBMIT" else b"Synthetic sensitive rationale sentinel",
            normalized_bytes=BODY,
            provider_version=checkpoint.provider_version,
            content_digest=checkpoint.content_digest,
            provider_validation_cutoff=now,
            access_evaluation_id=uuid.uuid4(),
            policy_version_ids=[str(uuid.uuid4())],
            submission=self.capture,
        )
        try:
            if self.hook:
                self.hook(proof, command)
            yield proof
        finally:
            self.retained.append(proof.committed_operation_id)

    def revalidate_completion(self, *, prepared, command):
        assert transaction.get_connection().in_atomic_block
        return self.local_hook(prepared, command) if self.local_hook else True


@pytest.fixture
def setup(fixture, settings):  # noqa: F811 - imported pytest fixture
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    runtime = SyntheticCompletionRuntime(fixture)
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = runtime
    settings.CURVE_PRD_COMPLETION_RUNTIME = runtime
    client = APIClient()
    client.force_authenticate(user=fixture[4])
    return fixture, runtime, client


def accepted(setup, action="approve", **kwargs):
    response = post(setup, action, **kwargs)
    assert response.status_code == 202, response.data
    return uuid.UUID(response.data["id"])


def complete(setup, operation_id):
    return complete_prd_operation(workspace_id=setup[0][5].id, operation_id=operation_id)


@pytest.mark.parametrize("action,state", [("approve", "PLANNING"), ("return-for-revision", "ALIGNING")])
def test_accepted_human_review_completes_and_redelivery_has_no_second_effect(setup, action, state):
    operation_id = accepted(setup, action)
    result = complete(setup, operation_id)
    assert result["status"] == "SUCCEEDED" and result["effect_applied"] is True
    initiative = setup[0][1]
    initiative.refresh_from_db()
    assert initiative.state == state and initiative.version == 3
    decision = PrdReviewDecision.objects.get(id=initiative.controlling_prd_decision_id)
    assert decision.decided_by["actor_id"] == str(setup[0][4].id)
    operation = Operation.objects.get(id=operation_id)
    assert operation.result_ref["resource_version"] == 3 and operation.result_ref["resource_id"] == str(initiative.id)
    assert set(AuditEvent.objects.filter(causation_id=str(operation_id)).values_list("correlation_id", flat=True)) == {
        operation.correlation_id
    }
    count = DomainEvent.objects.count()
    assert complete(setup, operation_id)["effect_applied"] is False
    assert setup[1].preparations == 1 and setup[1].retained == [operation_id]
    assert PrdReviewDecision.objects.count() == 1 and DomainEvent.objects.count() == count
    assert "sentinel" not in repr(list(DomainEvent.objects.values()))
    assert "sentinel" not in repr(list(AuditEvent.objects.values()))


def test_rejection_returns_to_alignment_with_exact_history(setup):
    response_body = dict(setup[0][2].as_record())
    body = {
        key: response_body[key]
        for key in ("artifact_version_id", "content_digest", "provider_version", "evidence_snapshot_id")
    }
    body.update(
        gate_assignment_id=str(setup[0][3].id),
        checkpoint_id=str(setup[0][2].id),
        confirmed_risk_tier="STANDARD",
        rationale="Synthetic sensitive rationale sentinel",
        decision="REJECTED",
    )
    operation_id = accepted(setup, "return-for-revision", body=body)
    assert complete(setup, operation_id)["status"] == "SUCCEEDED"
    assert PrdReviewDecision.objects.get().state == "REJECTED"


@pytest.mark.parametrize("failure", ["body", "rationale", "source-version", "expired", "scope", "access", "policy"])
def test_invalid_current_observation_fails_without_domain_effect(setup, failure):
    operation_id = accepted(setup)

    def mutate(proof, _):
        if failure == "body":
            proof.normalized_bytes = b"Synthetic corrupt body"
        if failure == "rationale":
            proof.rationale_bytes = b"Synthetic different rationale"
        if failure == "source-version":
            proof.provider_version = "changed"
        if failure == "expired":
            proof.valid_until = timezone.now() - timedelta(seconds=1)
        if failure == "scope":
            proof.operation_id = uuid.uuid4()
        if failure == "access":
            proof.checks["evidence_access"] = False
        if failure == "policy":
            proof.policy_version_ids = []

    setup[1].hook = mutate
    result = complete(setup, operation_id)
    assert result["status"] == "FAILED" and result["effect_applied"] is False
    assert PrdReviewDecision.objects.count() == 0 and setup[1].retained == [None]
    setup[0][1].refresh_from_db()
    assert setup[0][1].version == 2 and setup[0][1].state == "PRD_REVIEW"


def test_negative_review_can_address_immutable_submission_after_live_edit(setup):
    operation_id = accepted(setup, "return-for-revision")
    setup[1].hook = lambda proof, _: setattr(proof, "provider_version", "edited-live-version")
    assert complete(setup, operation_id)["status"] == "SUCCEEDED"


@pytest.mark.parametrize("during", [False, True])
def test_revoked_human_authority_fences_completion(setup, during):
    operation_id = accepted(setup)

    def revoke(*_):
        WorkspaceMember.objects.filter(workspace_id=setup[0][5].id, member_id=setup[0][4].id).update(is_active=False)

    if during:
        setup[1].hook = revoke
    else:
        revoke()
    assert complete(setup, operation_id)["status"] == "FAILED"
    assert PrdReviewDecision.objects.count() == 0
    assert setup[1].preparations == int(during)


def test_pause_during_provider_read_fences_approval(setup):
    operation_id = accepted(setup)
    setup[1].hook = lambda *_: raw_update(setup[0][1].id, state="PAUSED", paused_from_state="PRD_REVIEW", version=3)
    assert complete(setup, operation_id)["status"] == "FAILED"
    assert PrdReviewDecision.objects.count() == 0


def test_cancellation_during_provider_read_wins(setup):
    operation_id = accepted(setup)

    def cancel(*_):
        operation = Operation.objects.get(id=operation_id)
        operation.status = "CANCEL_REQUESTED"
        operation.aggregate_version += 1
        operation.save()

    setup[1].hook = cancel
    assert complete(setup, operation_id)["status"] == "CANCELLED"
    assert PrdReviewDecision.objects.count() == 0 and setup[1].retained == [None]


def test_final_local_expiry_is_rechecked(setup):
    operation_id = accepted(setup)

    def expire(proof, _):
        proof.valid_until = timezone.now() - timedelta(seconds=1)
        return True

    setup[1].local_hook = expire
    assert complete(setup, operation_id)["status"] == "FAILED"
    assert PrdReviewDecision.objects.count() == 0


def test_outbox_failure_rolls_back_decision_and_success(setup, monkeypatch):
    operation_id = accepted(setup)
    from plane.curve import services

    append = services._append_operation_event

    def fail_success(**kwargs):
        if kwargs["operation"].status == "SUCCEEDED":
            raise RuntimeError("Synthetic sensitive rationale sentinel")
        return append(**kwargs)

    monkeypatch.setattr(services, "_append_operation_event", fail_success)
    assert complete(setup, operation_id)["status"] == "FAILED"
    assert PrdReviewDecision.objects.count() == 0
    assert Operation.objects.get(id=operation_id).result_ref is None
    setup[0][1].refresh_from_db()
    assert setup[0][1].version == 2


def test_worker_authority_is_required_and_other_workspaces_are_hidden(setup):
    operation_id = accepted(setup)
    setup[1].service_active = False
    with pytest.raises(PrdCompletionUnavailable):
        complete(setup, operation_id)
    assert setup[1].preparations == 0 and Operation.objects.get(id=operation_id).status == "PENDING"
    with pytest.raises(PrdCompletionUnavailable):
        complete_prd_operation(workspace_id=uuid.uuid4(), operation_id=operation_id)


def test_two_accepted_reviews_racing_have_one_winner(setup):
    ids = [accepted(setup, key="synthetic-one"), accepted(setup, "return-for-revision", key="synthetic-two")]
    barrier = Barrier(2)
    setup[1].hook = lambda *_: barrier.wait(timeout=15)

    def run(operation_id):
        try:
            return complete(setup, operation_id)["status"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ids))
    assert sorted(results) == ["FAILED", "SUCCEEDED"]
    assert PrdReviewDecision.objects.count() == 1


def test_submission_commits_new_checkpoint_and_operation_together(setup):
    binding, initiative, old, _, actor, _ = setup[0]
    artifact = PrdArtifact.objects.get(id=old.artifact_version.artifact_id)
    snapshot, version, checkpoint = capture_records(binding, artifact, old.id)
    version.created_by = checkpoint.submitted_or_approved_by = {"actor_type": "HUMAN", "actor_id": str(actor.id)}
    setup[1].capture = (snapshot, version, checkpoint)
    operation_id = accepted(
        setup,
        "submit",
        body=dict(
            external_document_binding_id=str(binding.id),
            evidence_snapshot_id=str(snapshot.id),
            completeness_check_id=str(checkpoint.completeness_check_id),
        ),
    )
    assert complete(setup, operation_id)["status"] == "SUCCEEDED"
    initiative.refresh_from_db()
    assert initiative.version == 3 and initiative.state == "PRD_REVIEW"
    assert initiative.current_prd_checkpoint_id == checkpoint.id and checkpoint.predecessor_id == old.id
    assert PrdAcceptedCommand.objects.count() == 1


def test_return_resubmit_and_approve_completes_the_exact_successor(setup):
    returned = accepted(setup, "return-for-revision", key="synthetic-return")
    assert complete(setup, returned)["status"] == "SUCCEEDED"
    binding, initiative, old, gate, actor, workspace = setup[0]
    initiative.refresh_from_db()
    assert initiative.state == "ALIGNING"
    artifact = PrdArtifact.objects.get(id=old.artifact_version.artifact_id)
    snapshot, version, checkpoint = capture_records(binding, artifact, old.id)
    version.created_by = checkpoint.submitted_or_approved_by = {"actor_type": "HUMAN", "actor_id": str(actor.id)}
    setup[1].capture = (snapshot, version, checkpoint)
    submitted = accepted(
        setup,
        "submit",
        key="synthetic-successor",
        body=dict(
            external_document_binding_id=str(binding.id),
            evidence_snapshot_id=str(snapshot.id),
            completeness_check_id=str(checkpoint.completeness_check_id),
        ),
    )
    assert complete(setup, submitted)["status"] == "SUCCEEDED"
    initiative.refresh_from_db()
    assert initiative.state == "PRD_REVIEW" and initiative.version == 4
    successor_setup = ((binding, initiative, checkpoint, gate, actor, workspace), setup[1], setup[2])
    setup[1].capture = None
    setup[1].records = successor_setup[0]
    approved = accepted(successor_setup, key="synthetic-approve-successor")
    assert complete(successor_setup, approved)["status"] == "SUCCEEDED"
    initiative.refresh_from_db()
    assert initiative.state == "PLANNING" and initiative.version == 5
    assert PrdReviewDecision.objects.get(id=initiative.controlling_prd_decision_id).checkpoint_id == checkpoint.id
    assert PrdReviewDecision.objects.count() == 2


def test_concurrent_same_operation_delivery_commits_once(setup):
    operation_id = accepted(setup)
    barrier = Barrier(2)
    setup[1].hook = lambda *_: barrier.wait(timeout=15)

    def run(_):
        try:
            return complete(setup, operation_id)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert all(result["status"] == "SUCCEEDED" for result in results)
    assert sum(result["effect_applied"] for result in results) == 1
    assert PrdReviewDecision.objects.count() == 1 and setup[1].retained.count(None) == 1


def test_terminal_replay_still_requires_current_worker_authority(setup):
    operation_id = accepted(setup)
    assert complete(setup, operation_id)["status"] == "SUCCEEDED"
    setup[1].service_active = False
    with pytest.raises(PrdCompletionUnavailable):
        complete(setup, operation_id)
    assert PrdReviewDecision.objects.count() == 1


def test_worker_revocation_at_final_commit_rolls_back_domain_effect(setup):
    operation_id = accepted(setup)

    def revoke(*_):
        setup[1].service_active = False

    setup[1].hook = revoke
    with pytest.raises(PrdCompletionUnavailable):
        complete(setup, operation_id)
    assert PrdReviewDecision.objects.count() == 0
    setup[0][1].refresh_from_db()
    assert setup[0][1].version == 2
    operation = Operation.objects.get(id=operation_id)
    assert operation.result_ref is None and operation.status == "RUNNING"


def test_stale_provider_cutoff_cannot_be_reused(setup):
    operation_id = accepted(setup)
    setup[1].hook = lambda proof, _: setattr(
        proof, "provider_validation_cutoff", proof.valid_from - timedelta(seconds=1)
    )
    assert complete(setup, operation_id)["status"] == "FAILED"
    assert PrdReviewDecision.objects.count() == 0
