# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Real PostgreSQL graph/retention attacks against synthetic, receipt-owned C2a."""

# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime
import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from plane.curve.models import (
    AuditEvent,
    DocumentCheckpoint,
    DomainEvent,
    OutboxEvent,
    PrdReadinessRecord,
    PrdReviewDecision,
)
from plane.curve.policy_services import execute_authorized_mutation
from plane.curve.prd_policy_context import build_prd_policy_context
from plane.curve.prd_metadata_validation import metadata_digest as base_digest
from plane.curve.scoped_prd_contracts import metadata_digest
from plane.curve.scoped_prd_models import (
    ScopedPrdAcceptedCommand,
    ScopedPrdDecision,
    ScopedPrdObservation,
    ScopedPrdReadiness,
    ScopedPrdSubject,
)
from plane.curve.scoped_prd_repository import authorize_record_write
from plane.curve.tests.test_prd_review_models import decision_for
from plane.curve.tests.test_scoped_prd_bridge import (  # noqa: F401
    accept,
    bridge,
    complete,
    configuration,
    context,
    observe,
    review_command,
    submission,
    submit,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def _reseal(payload):
    payload["digest"] = metadata_digest(payload)
    return payload


def _insert_untrusted(record):
    """Bypass the Python receipt boundary deliberately; DB guards must still apply."""
    record.save_base(force_insert=True)


@contextmanager
def _omit_deferred_guard(table, name):
    """Disposable fixture only: model an ordinary record predating this edition.

    Restore the guard before testing the attempted retrofit. No production
    application path is allowed to disable triggers or manufacture provenance.
    """
    q = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {q(table)} DISABLE TRIGGER {q(name)}")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {q(table)} ENABLE TRIGGER {q(name)}")


def _no_submission_effect(bridge):
    bridge.initiative.refresh_from_db()
    assert bridge.initiative.state == "ALIGNING"
    assert bridge.initiative.current_prd_checkpoint_id is None
    assert not DocumentCheckpoint.objects.exists()
    assert not PrdReadinessRecord.objects.exists()
    assert not ScopedPrdReadiness.objects.exists()
    assert not ScopedPrdSubject.objects.exists()
    assert not AuditEvent.objects.filter(action="CURVE.PRD.SUBMIT.COMPLETION", outcome="SUCCEEDED").exists()
    assert not DomainEvent.objects.filter(aggregate_type="OPERATION", payload__status="SUCCEEDED").exists()


def test_all_scoped_metadata_and_accepted_commands_are_database_immutable(bridge):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject)).operation
    assert complete(bridge, operation)["status"] == "SUCCEEDED"
    for model in (
        ScopedPrdObservation,
        ScopedPrdReadiness,
        ScopedPrdSubject,
        ScopedPrdDecision,
        ScopedPrdAcceptedCommand,
    ):
        record = model.objects.first()
        table = connection.ops.quote_name(model._meta.db_table)
        pk = connection.ops.quote_name(model._meta.pk.column)
        for sql in (f"UPDATE {table} SET {pk}={pk} WHERE {pk}=%s", f"DELETE FROM {table} WHERE {pk}=%s"):
            with pytest.raises(DatabaseError, match="immutable"), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, [record.pk])
        assert model.objects.filter(pk=record.pk).exists()


@pytest.mark.parametrize("attack", ["digest", "unknown_body", "typed_id", "workspace", "initiative", "product"])
def test_raw_observation_rejects_digest_shape_and_cross_tenant_substitution(bridge, attack):
    original = observe(bridge).data
    payload = deepcopy(original)
    payload["id"] = str(uuid.uuid4())
    if attack == "unknown_body":
        payload["body"] = "Synthetic body must never persist"
    elif attack in {"workspace", "initiative", "product"}:
        payload[attack + "_id"] = str(uuid.uuid4())
    _reseal(payload)
    if attack == "digest":
        payload["digest"] = "sha256:" + "0" * 64
    record = ScopedPrdObservation.from_payload(payload)
    if attack == "typed_id":
        record.product_id = uuid.uuid4()
    with pytest.raises(DatabaseError), transaction.atomic():
        _insert_untrusted(record)
    assert ScopedPrdObservation.objects.count() == 1
    assert ScopedPrdObservation.objects.get(id=original["id"]).as_record() == original


def test_projection_is_a_deep_copy_and_validated_columns_cannot_substitute(bridge):
    observation = ScopedPrdObservation.objects.get(id=observe(bridge).data["id"])
    projected = observation.as_record()
    projected["members"][0]["purpose"] = "CONTEXT_EVIDENCE"
    assert projected != observation.as_record()
    observation.initiative_id = uuid.uuid4()
    with pytest.raises(Exception, match="SCOPED_PRD_RECORD_SUBSTITUTION"):
        observation.validate_metadata()


@pytest.mark.parametrize("verb", ["insert", "update", "delete"])
def test_private_transaction_provenance_cannot_be_caller_forged(bridge, verb):
    observation = observe(bridge).data
    with (
        pytest.raises(DatabaseError, match="PROVENANCE_TRIGGER_REQUIRED"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        if verb == "insert":
            cursor.execute(
                "INSERT INTO curve_scoped_prd_provenance "
                "VALUES ('curve_document_checkpoint',%s,%s,pg_current_xact_id())",
                [bridge.workspace.id, uuid.uuid4()],
            )
        elif verb == "update":
            cursor.execute(
                "UPDATE curve_scoped_prd_provenance SET transaction_id=pg_current_xact_id() WHERE record_id=%s",
                [observation["id"]],
            )
        else:
            cursor.execute("DELETE FROM curve_scoped_prd_provenance WHERE record_id=%s", [observation["id"]])


def test_transaction_provenance_is_savepoint_safe_and_not_reusable(bridge):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_current_xact_id()")
            transaction_id = cursor.fetchone()[0]
        with transaction.atomic():
            event = DomainEvent.objects.create(
                workspace_id=bridge.workspace.id,
                event_type="synthetic.provenance_probe",
                aggregate_type="SYNTHETIC_PROBE",
                aggregate_id=uuid.uuid4(),
                aggregate_version=1,
                sequence=1,
                actor={"actor_type": "HUMAN", "actor_id": str(bridge.user.id)},
                correlation_id="savepoint-probe",
                payload_schema="synthetic-probe-v1",
                payload={},
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT transaction_id,curve_sprd_created_here(record_kind,workspace_id,record_id) "
                "FROM curve_scoped_prd_provenance WHERE record_kind='curve_domain_event' AND record_id=%s",
                [event.id],
            )
            assert cursor.fetchone() == (transaction_id, True)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT curve_sprd_created_here('curve_domain_event',%s,%s)", [bridge.workspace.id, event.id])
        assert cursor.fetchone() == (False,)


def test_old_structural_readiness_cannot_acquire_new_scoped_authority(bridge):
    subject, _, _ = submit(bridge)
    previous = ScopedPrdReadiness.objects.get(id=subject.scoped_readiness_id)
    payload = previous.as_record()
    payload["id"] = str(uuid.uuid4())
    record = ScopedPrdReadiness.from_payload(_reseal(payload))
    with pytest.raises(DatabaseError, match="READINESS_PROVENANCE_INVALID"), transaction.atomic():
        _insert_untrusted(record)
    assert ScopedPrdReadiness.objects.count() == 1


def test_old_checkpoint_cannot_acquire_scoped_authority_with_fresh_readiness(bridge):
    from plane.curve.prd_checkpoint_repository import append_document_checkpoint_metadata
    from plane.curve.prd_metadata_validation import instant

    command = submission(bridge)
    operation = accept(bridge, command).operation
    accepted = ScopedPrdAcceptedCommand.objects.get(operation_id=operation.id)
    observation = ScopedPrdObservation.objects.get(id=accepted.subject["observation_set_id"])
    with bridge.runtime.prepare_completion(command=accepted) as prepared:
        snapshot, version, checkpoint = prepared.submission
        report = prepared.readiness_report.as_dict()
        # Construct pre-edition ordinary history. Only its deferred sidecar
        # requirement is omitted; ordinary checkpoint graph checks remain active.
        with _omit_deferred_guard("curve_document_checkpoint", "curve_sprd_base_cp_commit"):
            append_document_checkpoint_metadata(
                workspace_id=bridge.workspace.id,
                initiative_id=bridge.initiative.id,
                expected_initiative_version=bridge.initiative.version,
                artifact_id=bridge.artifact.id,
                expected_parent_version_id=None,
                expected_predecessor_id=None,
                snapshot=snapshot,
                version=version,
                checkpoint=checkpoint,
            )
    entity = {
        key: observation.payload[key]
        for key in ("schema_version", "policy_edition", "workspace_id", "product_id", "initiative_id")
    }
    scope = {
        key: observation.payload[key]
        for key in ("proposal_id", "scope_revision_id", "scope_revision", "membership_digest")
    }
    base = PrdReadinessRecord(
        id=checkpoint.completeness_check_id,
        workspace_id=bridge.workspace.id,
        initiative_id=bridge.initiative.id,
        binding_id=bridge.binding.id,
        policy_decision_id=operation.policy_version_ref["resource_id"],
        payload=report,
    )
    ready_payload = _reseal(
        dict(
            entity,
            id=str(uuid.uuid4()),
            base_readiness_id=str(base.id),
            base_readiness_digest=base_digest(report),
            **scope,
            observation_set_id=str(observation.id),
            observation_digest=observation.digest,
        )
    )
    ready = ScopedPrdReadiness.from_payload(ready_payload)
    subject_payload = _reseal(
        dict(
            entity,
            id=str(uuid.uuid4()),
            checkpoint_id=str(checkpoint.id),
            artifact_version_id=str(version.id),
            content_digest=checkpoint.content_digest,
            provider_version=checkpoint.provider_version,
            evidence_snapshot_id=str(snapshot.id),
            **scope,
            observation_set_id=str(observation.id),
            observation_digest=observation.digest,
            scoped_readiness_id=str(ready.id),
            scoped_readiness_digest=ready.digest,
            members=[
                {key: value for key, value in member.items() if key not in {"source_version", "source_fingerprint"}}
                for member in observation.payload["members"]
            ],
            created_by=str(bridge.user.id),
            recorded_at=instant(timezone.now()),
            controlling=False,
        )
    )
    subject = ScopedPrdSubject.from_payload(subject_payload, submission_operation_id=operation.id)
    with pytest.raises(DatabaseError, match="CHECKPOINT_PROVENANCE_INVALID"), transaction.atomic():
        base.save()
        _insert_untrusted(ready)
        _insert_untrusted(subject)
    assert DocumentCheckpoint.objects.filter(id=checkpoint.id).exists()
    assert not ScopedPrdSubject.objects.exists() and not ScopedPrdReadiness.objects.exists()


def test_old_ordinary_decision_cannot_be_retrofitted_with_a_scoped_decision(bridge):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject, "return-for-revision")).operation
    checkpoint = DocumentCheckpoint.objects.get(id=subject.checkpoint_id)
    decision = decision_for(checkpoint, bridge.gates[0], state="CHANGES_REQUESTED")
    from plane.curve.prd_metadata_validation import instant

    decision.decided_at = decision.provider_validation_cutoff = datetime.fromisoformat(
        instant(timezone.now()).replace("Z", "+00:00")
    )
    # Persist only synthetic legacy history, in a distinct committed transaction.
    with _omit_deferred_guard("curve_prd_review_decision", "curve_sprd_base_dec_commit"), transaction.atomic():
        decision.save()
    payload = {
        key: value
        for key, value in subject.as_record().items()
        if key
        in {
            "schema_version",
            "policy_edition",
            "workspace_id",
            "product_id",
            "initiative_id",
            "created_by",
            "controlling",
        }
    }
    from plane.curve.prd_metadata_validation import instant

    payload.update(
        id=str(uuid.uuid4()),
        decision_id=str(decision.id),
        scoped_subject_id=str(subject.id),
        scoped_subject_digest=subject.digest,
        state=decision.state,
        recorded_at=instant(decision.decided_at),
    )
    record = ScopedPrdDecision.from_payload(_reseal(payload), review_operation_id=operation.id)
    with pytest.raises(DatabaseError, match="DECISION_PROVENANCE_INVALID"), transaction.atomic():
        _insert_untrusted(record)
    assert not ScopedPrdDecision.objects.exists()


@pytest.mark.parametrize("state", ["CHANGES_REQUESTED", "REJECTED"])
def test_direct_ordinary_negative_decision_requires_same_transaction_scoped_sidecar(bridge, state):
    subject, _, _ = submit(bridge)
    checkpoint = DocumentCheckpoint.objects.get(id=subject.checkpoint_id)
    decision = decision_for(checkpoint, bridge.gates[0], state=state)
    with pytest.raises(DatabaseError, match="DECISION_SIDECAR_REQUIRED"), transaction.atomic():
        decision.save()
    assert not PrdReviewDecision.objects.exists()
    bridge.initiative.refresh_from_db()
    assert bridge.initiative.state == "PRD_REVIEW"


def test_repository_rejects_active_receipt_for_the_wrong_action(bridge):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject, "return-for-revision")).operation
    record = ScopedPrdAcceptedCommand.objects.get(operation_id=operation.id)

    def build():
        return build_prd_policy_context(
            request=bridge.request,
            workspace_slug=bridge.workspace.slug,
            initiative_id=bridge.initiative.id,
            action="CURVE.PRD.APPROVE",
            acl_resolver=bridge.runtime.resolve_acl,
            for_update=True,
        )

    def mutate(receipt, _):
        return authorize_record_write(receipt, record, record.action)

    with pytest.raises(PermissionError):
        execute_authorized_mutation(context_builder=build, mutation_callback=mutate)
    assert not PrdReviewDecision.objects.exists() and not ScopedPrdDecision.objects.exists()


@pytest.mark.parametrize("field", ["base_readiness_id", "evidence_snapshot_id"])
def test_same_transaction_readiness_cannot_split_the_checkpoint_graph(bridge, monkeypatch, field):
    operation = accept(bridge, submission(bridge)).operation
    original_save = ScopedPrdSubject.save
    failures = []

    def substituted_save(subject, *args, **kwargs):
        ready = ScopedPrdReadiness.objects.get(id=subject.scoped_readiness_id)
        base = PrdReadinessRecord.objects.get(id=ready.base_readiness_id)
        altered = deepcopy(base.payload)
        altered["id"] = str(uuid.uuid4())
        if field == "evidence_snapshot_id":
            altered["evidence_snapshot_id"] = str(uuid.uuid4())
        replacement = PrdReadinessRecord(
            id=uuid.UUID(altered["id"]),
            workspace_id=base.workspace_id,
            initiative_id=base.initiative_id,
            binding_id=base.binding_id,
            policy_decision_id=base.policy_decision_id,
            payload=altered,
        )
        replacement.save()
        ready_payload = ready.as_record()
        ready_payload.update(
            id=str(uuid.uuid4()), base_readiness_id=str(replacement.id), base_readiness_digest=base_digest(altered)
        )
        replacement_ready = ScopedPrdReadiness.from_payload(_reseal(ready_payload))
        replacement_ready.save()
        subject.scoped_readiness_id = replacement_ready.id
        subject.payload["scoped_readiness_id"] = str(replacement_ready.id)
        subject.payload["scoped_readiness_digest"] = replacement_ready.digest
        subject.digest = subject.payload["digest"] = metadata_digest(subject.payload)
        try:
            return original_save(subject, *args, **kwargs)
        except DatabaseError as error:
            failures.append(str(error))
            raise

    monkeypatch.setattr(ScopedPrdSubject, "save", substituted_save)
    assert complete(bridge, operation)["status"] == "FAILED"
    assert any("CHECKPOINT_PROVENANCE_INVALID" in failure for failure in failures)
    _no_submission_effect(bridge)


@pytest.mark.parametrize("missing", ["subject", "readiness", "success_outbox", "success_audit"])
def test_partial_submission_graph_rolls_back_at_commit(bridge, monkeypatch, missing):
    operation = accept(bridge, submission(bridge)).operation
    if missing in {"subject", "readiness"}:
        model = ScopedPrdSubject if missing == "subject" else ScopedPrdReadiness
        monkeypatch.setattr(model, "save", lambda *_args, **_kwargs: None)
    elif missing == "success_outbox":
        original = OutboxEvent.save

        def omit(outbox, *args, **kwargs):
            if (
                outbox.destination == "CURVE_SCOPED_PRD_CANDIDATE_V1"
                and DomainEvent.objects.filter(id=outbox.event_id, payload__status="SUCCEEDED").exists()
            ):
                return None
            return original(outbox, *args, **kwargs)

        monkeypatch.setattr(OutboxEvent, "save", omit)
    else:
        from plane.curve import scoped_prd_completion

        original = scoped_prd_completion._append_audit_event

        def change_outcome(**kwargs):
            if kwargs["action"] == "CURVE.PRD.SUBMIT.COMPLETION" and kwargs["outcome"] == "SUCCEEDED":
                kwargs["outcome"] = "NO_EFFECT"
            return original(**kwargs)

        monkeypatch.setattr(scoped_prd_completion, "_append_audit_event", change_outcome)
    assert complete(bridge, operation)["status"] == "FAILED"
    _no_submission_effect(bridge)


def test_missing_review_sidecar_rolls_back_ordinary_negative_decision(bridge, monkeypatch):
    subject, _, _ = submit(bridge)
    operation = accept(bridge, review_command(bridge, subject, "return-for-revision")).operation
    monkeypatch.setattr(ScopedPrdDecision, "save", lambda *_args, **_kwargs: None)
    assert complete(bridge, operation)["status"] == "FAILED"
    assert not PrdReviewDecision.objects.exists() and not ScopedPrdDecision.objects.exists()
    bridge.initiative.refresh_from_db()
    assert (
        bridge.initiative.state == "PRD_REVIEW" and bridge.initiative.current_prd_checkpoint_id == subject.checkpoint_id
    )


@pytest.mark.parametrize("mutation", ["command_type", "target", "actor", "terminal_result"])
def test_scoped_operation_identity_and_terminal_result_are_immutable(bridge, mutation):
    if mutation == "terminal_result":
        _, _, operation = submit(bridge)
        assignment = "result_ref='{}'::jsonb"
    else:
        operation = accept(bridge, submission(bridge)).operation
        assignment = {
            "command_type": "command_type='PRD_SUBMIT'",
            "target": "target='{}'::jsonb",
            "actor": "created_by='{}'::jsonb",
        }[mutation]
    with (
        pytest.raises(DatabaseError, match="OPERATION_IDENTITY_IMMUTABLE"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f"UPDATE curve_operation SET {assignment} WHERE id=%s", [operation.id])


def test_fresh_operation_guard_allows_worker_policy_updates_and_cancellation(bridge):
    from plane.curve.policy_services import request_operation_cancellation

    operation = accept(bridge, submission(bridge)).operation
    acceptance_policy = deepcopy(operation.policy_version_ref)
    phases = []

    def cancel_during_prepare(*_):
        operation.refresh_from_db()
        phases.append(operation.status)
        assert operation.status == "RUNNING"
        assert operation.policy_version_ref != acceptance_policy
        request_operation_cancellation(
            request=bridge.request,
            workspace_slug=bridge.workspace.slug,
            operation_id=operation.id,
            expected_version=operation.aggregate_version,
            raw_idempotency_key="integrity-cancel",
            canonical_request=b"{}",
        )

    bridge.runtime.hook = cancel_during_prepare
    assert complete(bridge, operation)["status"] == "CANCELLED"
    assert phases == ["RUNNING"]
    _no_submission_effect(bridge)
