import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

import pytest
from django.db import close_old_connections
from django.utils import timezone

from plane.curve.models import (
    AuditEvent,
    AuditOutcome,
    DomainEvent,
    IdempotencyRecord,
    InboxMessage,
    Operation,
    OperationStatus,
    OperationType,
    OutboxEvent,
    OutboxState,
)
from plane.curve.services import (
    CommandAlreadyInProgress,
    CurveResourceNotFound,
    IdempotencyConflict,
    InvalidCommand,
    InvalidOperationTransition,
    InvalidRelayClaim,
    OptimisticConcurrencyError,
    acknowledge_outbox,
    claim_due_outbox,
    create_operation,
    dead_letter_outbox,
    idempotency_key_digest,
    operation_response_digest,
    receive_inbox_message,
    recover_expired_outbox_claims,
    retry_outbox,
    transition_operation,
)
import plane.curve.services as curve_services


pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]

ACTOR = {"actor_type": "HUMAN", "actor_id": "federico"}
REQUEST = b'{"command":"CREATE_FOUNDATION_PROBE"}'
SAFE_ERROR = {"code": "TRANSIENT_TEST", "retryable": True}


def target_ref(workspace_id):
    return {
        "resource_type": "WORKSPACE",
        "resource_id": str(workspace_id),
        "resource_version": 1,
    }


def create_command(workspace_id, raw_key="curve-test-idempotency-key", request=REQUEST):
    return create_operation(
        workspace_id=workspace_id,
        principal_scope="HUMAN:federico",
        command_scope=f"CREATE_FOUNDATION_PROBE:{workspace_id}",
        raw_idempotency_key=raw_key,
        canonical_request=request,
        operation_type=OperationType.FOUNDATION_PROBE,
        command_type="CREATE_FOUNDATION_PROBE",
        target=target_ref(workspace_id),
        actor=ACTOR,
        correlation_id="curve-service-test",
    )


def test_create_operation_commits_aggregate_event_outbox_audit_and_replay_record():
    workspace_id = uuid.uuid4()
    result = create_command(workspace_id)

    assert result.replayed is False
    assert Operation.objects.filter(workspace_id=workspace_id, id=result.operation.id).count() == 1
    assert (
        DomainEvent.objects.filter(
            workspace_id=workspace_id,
            aggregate_id=result.operation.id,
            sequence=1,
        ).count()
        == 1
    )
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == 1
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace_id,
            target_id=result.operation.id,
            outcome=AuditOutcome.SUCCEEDED,
        ).count()
        == 1
    )
    record = IdempotencyRecord.objects.get(workspace_id=workspace_id)
    assert record.key_digest == idempotency_key_digest("curve-test-idempotency-key")
    assert record.response_resource_ref == {
        "resource_type": "OPERATION",
        "resource_id": str(result.operation.id),
        "resource_version": 1,
    }
    assert result.response_status == record.response_status == 201
    assert (
        result.response_digest
        == record.response_digest
        == operation_response_digest(
            response_status=201,
            resource_ref=record.response_resource_ref,
        )
    )
    assert record.response_digest != record.request_digest


@pytest.mark.parametrize(
    "overrides",
    [
        {"operation_type": "UNRECOGNIZED"},
        {"command_type": "lowercase-command"},
        {"actor": {"actor_type": "AGENT", "actor_id": "agent", "extra": True}},
        {"target": {"resource_type": "WORKSPACE", "resource_id": "not-a-uuid"}},
        {"destination": "lowercase-destination"},
    ],
)
def test_create_rejects_non_contract_command_metadata_without_database_effects(overrides):
    workspace_id = uuid.uuid4()
    arguments = {
        "workspace_id": workspace_id,
        "principal_scope": "HUMAN:federico",
        "command_scope": f"CREATE_FOUNDATION_PROBE:{workspace_id}",
        "raw_idempotency_key": "invalid-command-test",
        "canonical_request": REQUEST,
        "operation_type": OperationType.FOUNDATION_PROBE,
        "command_type": "CREATE_FOUNDATION_PROBE",
        "target": target_ref(workspace_id),
        "actor": ACTOR,
        "correlation_id": "curve-invalid-command-test",
    }
    arguments.update(overrides)

    with pytest.raises(InvalidCommand):
        create_operation(**arguments)

    assert Operation.objects.filter(workspace_id=workspace_id).count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace_id).count() == 0


def test_same_request_replays_database_operation_without_duplicate_effects():
    workspace_id = uuid.uuid4()
    first = create_command(workspace_id)
    replay = create_command(workspace_id)

    assert replay.replayed is True
    assert replay.operation.id == first.operation.id
    assert replay.response_status == first.response_status
    assert replay.response_digest == first.response_digest
    assert replay.response_resource_ref == first.response_resource_ref
    assert Operation.objects.filter(workspace_id=workspace_id).count() == 1
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == 1
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == 1
    assert AuditEvent.objects.filter(workspace_id=workspace_id).count() == 1


def test_same_request_replays_original_response_reference_after_operation_advances():
    workspace_id = uuid.uuid4()
    first = create_command(workspace_id)
    transition_operation(
        workspace_id=workspace_id,
        operation_id=first.operation.id,
        expected_version=1,
        status=OperationStatus.QUEUED,
        actor=ACTOR,
        correlation_id="curve-service-test",
    )
    event_count = DomainEvent.objects.filter(workspace_id=workspace_id).count()
    outbox_count = OutboxEvent.objects.filter(workspace_id=workspace_id).count()

    replay = create_command(workspace_id)

    assert replay.replayed is True
    assert replay.response_status == first.response_status == 201
    assert replay.response_digest == first.response_digest
    assert replay.response_resource_ref == first.response_resource_ref
    assert replay.response_resource_ref["resource_version"] == 1
    assert replay.operation.aggregate_version == 2
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == event_count
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == outbox_count


def _concurrent_command(workspace_id, barrier):
    close_old_connections()
    barrier.wait()
    try:
        return create_command(workspace_id)
    finally:
        close_old_connections()


def test_concurrent_same_request_commits_one_operation_and_replays_one_result():
    from threading import Barrier

    workspace_id = uuid.uuid4()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: _concurrent_command(workspace_id, barrier),
                range(2),
            )
        )

    assert {result.operation.id for result in results} == {Operation.objects.get(workspace_id=workspace_id).id}
    assert sorted(result.replayed for result in results) == [False, True]
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == 1
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == 1


def test_changed_request_with_same_key_is_no_effect_and_audited():
    workspace_id = uuid.uuid4()
    first = create_command(workspace_id)

    with pytest.raises(IdempotencyConflict):
        create_command(workspace_id, request=b'{"command":"DIFFERENT"}')

    assert Operation.objects.filter(workspace_id=workspace_id).count() == 1
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == 1
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == 1
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace_id,
            target_id=workspace_id,
            outcome=AuditOutcome.NO_EFFECT,
        ).count()
        == 1
    )
    assert Operation.objects.get(id=first.operation.id).aggregate_version == 1


def test_command_transaction_rolls_back_every_record_when_audit_append_fails(monkeypatch):
    workspace_id = uuid.uuid4()

    def fail_audit(**kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(curve_services, "_append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        create_command(workspace_id)

    assert Operation.objects.filter(workspace_id=workspace_id).count() == 0
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == 0
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == 0
    assert IdempotencyRecord.objects.filter(workspace_id=workspace_id).count() == 0


def test_raw_idempotency_key_is_absent_from_all_persisted_records():
    workspace_id = uuid.uuid4()
    raw_key = "raw-key-that-must-never-cross-the-command-boundary"
    create_command(workspace_id, raw_key=raw_key)

    persisted = {
        "operations": list(Operation.objects.filter(workspace_id=workspace_id).values()),
        "events": list(DomainEvent.objects.filter(workspace_id=workspace_id).values()),
        "outbox": list(OutboxEvent.objects.filter(workspace_id=workspace_id).values()),
        "idempotency": list(IdempotencyRecord.objects.filter(workspace_id=workspace_id).values()),
        "audit": list(AuditEvent.objects.filter(workspace_id=workspace_id).values()),
    }
    assert raw_key not in json.dumps(persisted, default=str)


def test_existing_in_progress_request_is_not_executed_again():
    workspace_id = uuid.uuid4()
    IdempotencyRecord.objects.create(
        workspace_id=workspace_id,
        principal_scope="HUMAN:federico",
        command_scope=f"CREATE_FOUNDATION_PROBE:{workspace_id}",
        key_digest=idempotency_key_digest("curve-test-idempotency-key"),
        request_digest=f"sha256:{__import__('hashlib').sha256(REQUEST).hexdigest()}",
        expires_at=timezone.now() + timedelta(days=1),
    )

    with pytest.raises(CommandAlreadyInProgress):
        create_command(workspace_id)
    assert Operation.objects.filter(workspace_id=workspace_id).count() == 0


def test_stale_version_writes_only_no_effect_audit():
    workspace_id = uuid.uuid4()
    operation = create_command(workspace_id).operation
    initial_event_count = DomainEvent.objects.filter(workspace_id=workspace_id).count()
    initial_outbox_count = OutboxEvent.objects.filter(workspace_id=workspace_id).count()

    with pytest.raises(OptimisticConcurrencyError):
        transition_operation(
            workspace_id=workspace_id,
            operation_id=operation.id,
            expected_version=99,
            status=OperationStatus.RUNNING,
            actor=ACTOR,
            correlation_id="curve-service-test",
        )

    operation.refresh_from_db()
    assert operation.aggregate_version == 1
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == initial_event_count
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == initial_outbox_count
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace_id,
            target_id=operation.id,
            outcome=AuditOutcome.NO_EFFECT,
        ).count()
        == 1
    )


def test_transition_is_workspace_scoped_and_follows_the_operation_state_matrix():
    workspace_id = uuid.uuid4()
    operation = create_command(workspace_id).operation

    with pytest.raises(CurveResourceNotFound):
        transition_operation(
            workspace_id=uuid.uuid4(),
            operation_id=operation.id,
            expected_version=1,
            status=OperationStatus.RUNNING,
            actor=ACTOR,
            correlation_id="curve-service-test",
        )

    queued = transition_operation(
        workspace_id=workspace_id,
        operation_id=operation.id,
        expected_version=1,
        status=OperationStatus.QUEUED,
        actor=ACTOR,
        correlation_id="curve-service-test",
    )
    running = transition_operation(
        workspace_id=workspace_id,
        operation_id=operation.id,
        expected_version=2,
        status=OperationStatus.RUNNING,
        actor=ACTOR,
        correlation_id="curve-service-test",
        progress_percent=10,
    )
    assert queued.aggregate_version == 2
    assert running.aggregate_version == 3
    assert running.started_at is not None
    assert DomainEvent.objects.filter(
        workspace_id=workspace_id,
        aggregate_id=operation.id,
        sequence=3,
    ).exists()


def test_invalid_or_terminal_operation_transition_is_no_effect_and_audited():
    workspace_id = uuid.uuid4()
    operation = create_command(workspace_id).operation
    initial_event_count = DomainEvent.objects.filter(workspace_id=workspace_id).count()
    initial_outbox_count = OutboxEvent.objects.filter(workspace_id=workspace_id).count()

    with pytest.raises(InvalidOperationTransition):
        transition_operation(
            workspace_id=workspace_id,
            operation_id=operation.id,
            expected_version=1,
            status=OperationStatus.RUNNING,
            actor=ACTOR,
            correlation_id="curve-service-test",
        )

    operation.refresh_from_db()
    assert operation.status == OperationStatus.PENDING
    assert operation.aggregate_version == 1
    assert DomainEvent.objects.filter(workspace_id=workspace_id).count() == initial_event_count
    assert OutboxEvent.objects.filter(workspace_id=workspace_id).count() == initial_outbox_count
    assert (
        AuditEvent.objects.filter(
            workspace_id=workspace_id,
            target_id=operation.id,
            action="CURVE.OPERATION.INVALID_TRANSITION",
            outcome=AuditOutcome.NO_EFFECT,
        ).count()
        == 1
    )

    failed = transition_operation(
        workspace_id=workspace_id,
        operation_id=operation.id,
        expected_version=1,
        status=OperationStatus.FAILED,
        error={"code": "TERMINAL_TEST", "retryable": False},
        actor=ACTOR,
        correlation_id="curve-service-test",
    )
    with pytest.raises(InvalidOperationTransition):
        transition_operation(
            workspace_id=workspace_id,
            operation_id=operation.id,
            expected_version=failed.aggregate_version,
            status=OperationStatus.QUEUED,
            actor=ACTOR,
            correlation_id="curve-service-test",
        )


def test_relay_rejects_invalid_claim_and_retry_parameters_before_mutation():
    workspace_id = uuid.uuid4()
    item = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
    )

    with pytest.raises(InvalidCommand):
        claim_due_outbox(
            workspace_id=workspace_id,
            worker_id="relay-a",
            limit=0,
            lease_duration=timedelta(minutes=1),
        )
    with pytest.raises(InvalidCommand):
        claim_due_outbox(
            workspace_id=workspace_id,
            worker_id="relay-a",
            limit=1,
            lease_duration=timedelta(0),
        )
    with pytest.raises(InvalidCommand):
        claim_due_outbox(
            workspace_id=workspace_id,
            worker_id="relay-a",
            limit=1,
            lease_duration=timedelta(minutes=16),
        )
    with pytest.raises(InvalidCommand):
        claim_due_outbox(
            workspace_id=workspace_id,
            worker_id="relay-a",
            limit=1,
            lease_duration=timedelta(minutes=1),
            now=timezone.now().replace(tzinfo=None),
        )

    item.refresh_from_db()
    assert item.state == OutboxState.PENDING

    now = timezone.now()
    claim_due_outbox(
        workspace_id=workspace_id,
        worker_id="relay-a",
        limit=1,
        lease_duration=timedelta(minutes=1),
        now=now,
    )
    with pytest.raises(InvalidCommand):
        retry_outbox(
            workspace_id=workspace_id,
            outbox_id=item.id,
            worker_id="relay-a",
            next_attempt_at=now,
            error=SAFE_ERROR,
            now=now,
        )
    with pytest.raises(InvalidCommand):
        retry_outbox(
            workspace_id=workspace_id,
            outbox_id=item.id,
            worker_id="relay-a",
            next_attempt_at=now + timedelta(minutes=1),
            error={"code": "unsafe code", "retryable": True},
            now=now,
        )
    with pytest.raises(InvalidCommand):
        retry_outbox(
            workspace_id=workspace_id,
            outbox_id=item.id,
            worker_id="relay-a",
            next_attempt_at=(now + timedelta(minutes=1)).replace(tzinfo=None),
            error=SAFE_ERROR,
            now=now,
        )

    item.refresh_from_db()
    assert item.state == OutboxState.CLAIMED


def test_outbox_mutation_is_workspace_scoped_without_existence_disclosure():
    workspace_id = uuid.uuid4()
    now = timezone.now()
    item = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
    )
    claim_due_outbox(
        workspace_id=workspace_id,
        worker_id="relay-a",
        limit=1,
        lease_duration=timedelta(minutes=1),
        now=now,
    )

    with pytest.raises(InvalidRelayClaim):
        acknowledge_outbox(
            workspace_id=uuid.uuid4(),
            outbox_id=item.id,
            worker_id="relay-a",
            now=now,
        )

    item.refresh_from_db()
    assert item.state == OutboxState.CLAIMED


def test_claim_ack_retry_and_dead_letter_require_matching_active_lease():
    workspace_id = uuid.uuid4()
    now = timezone.now()
    first = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
    )
    second = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
    )
    third = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
    )

    claimed = claim_due_outbox(
        workspace_id=workspace_id,
        worker_id="relay-a",
        limit=3,
        lease_duration=timedelta(minutes=1),
        now=now,
    )
    assert {item.id for item in claimed} == {first.id, second.id, third.id}
    assert all(item.attempt_count == 1 for item in claimed)

    acknowledged = acknowledge_outbox(
        workspace_id=workspace_id,
        outbox_id=first.id,
        worker_id="relay-a",
        now=now,
    )
    assert acknowledged.state == OutboxState.DELIVERED

    retried = retry_outbox(
        workspace_id=workspace_id,
        outbox_id=second.id,
        worker_id="relay-a",
        next_attempt_at=now + timedelta(minutes=5),
        error=SAFE_ERROR,
        now=now,
    )
    assert retried.state == OutboxState.RETRY_SCHEDULED

    dead = dead_letter_outbox(
        workspace_id=workspace_id,
        outbox_id=third.id,
        worker_id="relay-a",
        error={"code": "TERMINAL_TEST", "retryable": False},
        now=now,
    )
    assert dead.state == OutboxState.DEAD_LETTER

    with pytest.raises(InvalidRelayClaim):
        acknowledge_outbox(
            workspace_id=workspace_id,
            outbox_id=first.id,
            worker_id="relay-b",
            now=now,
        )


def test_expired_claim_recovery_is_explicit_and_audited():
    workspace_id = uuid.uuid4()
    item = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
        state=OutboxState.CLAIMED,
        claimed_by="lost-relay",
        claimed_until=timezone.now() - timedelta(seconds=1),
        attempt_count=1,
    )

    recovered = recover_expired_outbox_claims(
        workspace_id=workspace_id,
        actor=ACTOR,
        correlation_id="curve-recovery-test",
    )
    item.refresh_from_db()
    assert [candidate.id for candidate in recovered] == [item.id]
    assert item.state == OutboxState.RETRY_SCHEDULED
    assert item.last_error == {"code": "CLAIM_EXPIRED", "retryable": True}
    assert item.attempt_count == 1
    assert AuditEvent.objects.filter(
        workspace_id=workspace_id,
        target_type="OUTBOX_EVENT",
        target_id=item.id,
    ).exists()


def test_inbox_receive_is_workspace_scoped_and_idempotent():
    workspace_id = uuid.uuid4()
    event_id = uuid.uuid4()
    first, first_created = receive_inbox_message(
        workspace_id=workspace_id,
        consumer_id="curve-consumer",
        event_id=event_id,
    )
    replay, replay_created = receive_inbox_message(
        workspace_id=workspace_id,
        consumer_id="curve-consumer",
        event_id=event_id,
    )
    other_workspace, other_created = receive_inbox_message(
        workspace_id=uuid.uuid4(),
        consumer_id="curve-consumer",
        event_id=event_id,
    )

    assert first_created is True
    assert replay_created is False
    assert replay.id == first.id
    assert other_created is True
    assert other_workspace.id != first.id
    assert InboxMessage.objects.filter(event_id=event_id).count() == 2


def _concurrent_claim(workspace_id, barrier):
    close_old_connections()
    barrier.wait()
    try:
        return claim_due_outbox(
            workspace_id=workspace_id,
            worker_id=str(uuid.uuid4()),
            limit=1,
            lease_duration=timedelta(minutes=1),
        )
    finally:
        close_old_connections()


def test_two_claimers_do_not_receive_the_same_outbox_row():
    from threading import Barrier

    workspace_id = uuid.uuid4()
    item = OutboxEvent.objects.create(
        workspace_id=workspace_id,
        event_id=uuid.uuid4(),
        destination="CURVE_LOCAL",
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _concurrent_claim(workspace_id, barrier), range(2)))

    claimed_ids = [candidate.id for result in results for candidate in result]
    assert claimed_ids == [item.id]


def _competing_insert(factory, barrier):
    close_old_connections()
    barrier.wait()
    try:
        factory()
        return True
    except Exception as error:
        from django.db import IntegrityError

        if isinstance(error, IntegrityError):
            return False
        raise
    finally:
        close_old_connections()


def test_concurrent_workspace_uniqueness_collisions_commit_exactly_one_record():
    from threading import Barrier

    workspace_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()
    event_id = uuid.uuid4()
    target_id = uuid.uuid4()
    factories = [
        lambda: DomainEvent.objects.create(
            workspace_id=workspace_id,
            event_type="curve.operation.created",
            aggregate_type="OPERATION",
            aggregate_id=aggregate_id,
            aggregate_version=1,
            sequence=1,
            actor=ACTOR,
            correlation_id="curve-concurrency-test",
            payload_schema="operation-event-v1.schema.json",
            payload={"status": "PENDING"},
        ),
        lambda: OutboxEvent.objects.create(
            workspace_id=workspace_id,
            event_id=event_id,
            destination="CURVE_CONCURRENCY_TEST",
        ),
        lambda: InboxMessage.objects.create(
            workspace_id=workspace_id,
            consumer_id="curve-concurrency-test",
            event_id=event_id,
        ),
        lambda: IdempotencyRecord.objects.create(
            workspace_id=workspace_id,
            principal_scope="HUMAN:federico",
            command_scope="CURVE_CONCURRENCY_TEST",
            key_digest=idempotency_key_digest("concurrent-key"),
            request_digest=idempotency_key_digest("concurrent-request"),
            expires_at=timezone.now() + timedelta(days=1),
        ),
        lambda: AuditEvent.objects.create(
            workspace_id=workspace_id,
            sequence=1,
            action="CURVE.CONCURRENCY.TEST",
            target_type="OPERATION",
            target_id=target_id,
            target_ref={
                "resource_type": "OPERATION",
                "resource_id": str(target_id),
                "resource_version": 1,
            },
            outcome=AuditOutcome.SUCCEEDED,
            actor=ACTOR,
            correlation_id="curve-concurrency-test",
        ),
    ]

    for factory in factories:
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            committed = list(
                executor.map(
                    lambda _: _competing_insert(factory, barrier),
                    range(2),
                )
            )
        assert sorted(committed) == [False, True]
