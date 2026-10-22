# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811
from types import SimpleNamespace
import pytest
from django.db import transaction, connection
from importlib import import_module
from plane.db.models import WorkspaceMember
from plane.curve.models import (
    LocalPrdReopening,
    LocalPrdDecision,
    IdempotencyRecord,
    PolicyDecision,
    DomainEvent,
    OutboxEvent,
    AuditEvent,
)
from plane.curve.local_prd_reopening_services import execute_local_reopening
from plane.curve.prd_commands import PrdCommandError
from plane.curve.services import IdempotencyConflict
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage  # noqa: F401
from plane.curve.tests.test_local_document_authority import local  # noqa: F401
from plane.curve.tests.test_local_document_services import store  # noqa: F401
from plane.curve.tests.test_local_plan_authority import approved  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def subject(approved):
    source, submission, decision = approved
    return dict(
        source_id=source["id"],
        source_digest=source["digest"],
        submission_id=submission["id"],
        submission_digest=submission["digest"],
        decision_id=decision["id"],
        decision_digest=decision["digest"],
    )


def command(local, approved, **overrides):
    args = dict(
        request=local.request,
        workspace_slug=local.workspace.slug,
        initiative_id=local.initiative.id,
        expected_version=local.initiative.version,
        raw_idempotency_key="reopen-approved-prd",
        **subject(approved),
    )
    result = execute_local_reopening(**(args | overrides))
    local.initiative.refresh_from_db()
    return result


def test_reopen_is_atomic_and_exact_retry_preserves_original_outcome(local, approved):
    version = local.initiative.version
    first = command(local, approved)
    assert local.initiative.state == "ALIGNING" and local.initiative.version == version + 1
    assert LocalPrdDecision.objects.get(id=approved[2]["id"]).state == "APPROVED"
    assert command(local, approved, expected_version=version).data == first.data
    assert command(local, approved, expected_version=version).replayed
    assert LocalPrdReopening.objects.count() == 1
    assert DomainEvent.objects.filter(event_type="CURVE.LOCAL_PRD.REOPEN_V1").count() == 1
    assert OutboxEvent.objects.filter(destination="CURVE_LOCAL_PRD_REOPENING_V1").count() == 1
    assert AuditEvent.objects.filter(action="CURVE.LOCAL_PRD.REOPEN", outcome="NO_EFFECT").count() == 2
    module = import_module("plane.curve.migrations.0041_local_prd_reopening_command")
    with (
        transaction.atomic(),
        connection.schema_editor() as editor,
        pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"),
    ):
        module.require_empty_reverse(None, editor)


def test_changed_request_cannot_reuse_the_command_key(local, approved):
    version = local.initiative.version
    command(local, approved)
    with pytest.raises(IdempotencyConflict):
        command(local, approved, expected_version=version, decision_digest="sha256:" + "a" * 64)
    assert LocalPrdReopening.objects.count() == 1


@pytest.mark.parametrize("damage", ["technical_actor", "stale_version", "wrong_decision", "wrong_source"])
def test_reopening_requires_current_owner_and_exact_approval(local, approved, damage):
    overrides = {
        "technical_actor": dict(request=SimpleNamespace(user=local.reviewers[1])),
        "stale_version": dict(expected_version=local.initiative.version - 1),
        "wrong_decision": dict(decision_digest="sha256:" + "a" * 64),
        "wrong_source": dict(source_digest="sha256:" + "a" * 64),
    }[damage]
    with pytest.raises(PrdCommandError):
        command(local, approved, **overrides)
    assert not LocalPrdReopening.objects.exists()
    local.initiative.refresh_from_db()
    assert local.initiative.state == "PLANNING"


@pytest.mark.parametrize("failure", ["outbox", "audit"])
def test_reopening_failure_rolls_back_every_effect(local, approved, monkeypatch, failure):
    from plane.curve import local_prd_reopening_services as service

    before = local.initiative.version

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic reopening failure")

    if failure == "outbox":
        monkeypatch.setattr(OutboxEvent.objects, "create", fail)
    else:
        monkeypatch.setattr(service, "_append_audit_event", fail)
    with pytest.raises(RuntimeError, match="synthetic reopening failure"):
        command(local, approved)
    local.initiative.refresh_from_db()
    assert local.initiative.state == "PLANNING" and local.initiative.version == before
    assert not LocalPrdReopening.objects.exists()
    assert not IdempotencyRecord.objects.filter(command_scope__startswith="CURVE.LOCAL_PRD.REOPEN:").exists()
    assert not PolicyDecision.objects.filter(policy_key="CURVE_LOCAL_PRD_REOPENING_POLICY").exists()
    assert not DomainEvent.objects.filter(event_type="CURVE.LOCAL_PRD.REOPEN_V1").exists()


def test_replay_rechecks_current_owner_access(local, approved):
    version = local.initiative.version
    command(local, approved)
    WorkspaceMember.objects.filter(workspace=local.workspace, member=local.user).update(is_active=False)
    with pytest.raises(PrdCommandError):
        command(local, approved, expected_version=version)
    assert LocalPrdReopening.objects.count() == 1


def test_empty_reopening_command_migration_roundtrip():
    from django.db.migrations.executor import MigrationExecutor

    module = import_module("plane.curve.migrations.0041_local_prd_reopening_command")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0040_local_prd_reopening_lifecycle")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0041_local_prd_reopening_command")])
        with connection.cursor() as cursor:
            assert module._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)
