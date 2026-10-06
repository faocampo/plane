"""Complete migration reversal and retained-evidence refusal on real PostgreSQL."""

# ruff: noqa: F401,F811 -- imported pytest fixtures are collected here.
from importlib import import_module
from contextlib import contextmanager
import uuid

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from plane.curve.models import AuditEvent, DomainEvent, PolicyDecision
from plane.curve.manual_plan_v2.models import ManualPlanDraftV2, ManualPlanRevisionV2
from plane.curve.scope_reopening_qualification import require_manual_plan_v2_qualification
from plane.curve.services import _append_audit_event
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from native_fixture import prepare_native_fixture
from test_manual_persistence import command, counts, save

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
MIGRATION = import_module("plane.curve.migrations.0024_manual_draft_reconstruction")
PREVIOUS = [("curve", "0023_scope_reopening")]
CURRENT = [("curve", "0024_manual_draft_reconstruction")]


@pytest.fixture
def native(bridge, settings, tmp_path):
    return prepare_native_fixture(bridge, settings, tmp_path)


def catalog():
    with transaction.atomic(), connection.cursor() as cursor:
        return MIGRATION._catalog(cursor)


@contextmanager
def historical_manual_catalog():
    """Exercise the immutable historical step, then restore all installed successors.

    No qualification check is bypassed: current-source checks run only after the
    full installed leaf is restored, and each historical physical pin is exact.
    """
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes("curve")
    try:
        executor.migrate(CURRENT)
        yield
    finally:
        MigrationExecutor(connection).migrate(leaves)
    with transaction.atomic():
        require_manual_plan_v2_qualification()


def test_complete_empty_reverse_and_forward_preserve_exact_catalogs():
    with historical_manual_catalog():
        _empty_reverse_and_forward()


def _empty_reverse_and_forward():
    assert not ManualPlanRevisionV2.objects.exists() and not ManualPlanDraftV2.objects.exists()
    assert catalog() == MIGRATION.CURRENT_CATALOG_DIGEST
    try:
        MigrationExecutor(connection).migrate(PREVIOUS)
        assert catalog() == MIGRATION.BASELINE_CATALOG_DIGEST
        assert not MigrationRecorder.Migration.objects.filter(app="curve", name=CURRENT[0][1]).exists()
        with connection.cursor() as cursor:
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
            cursor.execute("SELECT to_regclass('curve_manual_plan_v2_coverage')")
            assert cursor.fetchone()[0] is None
    finally:
        MigrationExecutor(connection).migrate(CURRENT)
    assert catalog() == MIGRATION.CURRENT_CATALOG_DIGEST


def test_complete_reverse_refuses_saved_and_replayed_evidence_without_changing_it(native):
    value = command(native)
    first = save(native, value)
    save(native, value)
    before = counts()
    with historical_manual_catalog():
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
            MigrationExecutor(connection).migrate(PREVIOUS)
        assert counts() == before
        assert ManualPlanRevisionV2.objects.get(id=first.data["id"]).as_record() == first.data
        assert catalog() == MIGRATION.CURRENT_CATALOG_DIGEST


def test_no_effect_audit_alone_prevents_reverse(native):
    assert not ManualPlanRevisionV2.objects.exists() and not ManualPlanDraftV2.objects.exists()
    assert not PolicyDecision.objects.filter(policy_key="CURVE_MANUAL_PLAN_DRAFT_POLICY_V2").exists()
    assert not DomainEvent.objects.filter(event_type="CURVE.MANUAL_PLAN_DRAFT_SAVED_V2").exists()
    actor = dict(actor_type="HUMAN", actor_id=str(native.user.id))
    with transaction.atomic():
        audit = _append_audit_event(
            workspace_id=native.workspace.id,
            action="CURVE.MANUAL_PLAN_DRAFT.SAVE_V2",
            target_ref=dict(
                resource_type="MANUAL_PLAN_DRAFT_REVISION_V2", resource_id=str(uuid.uuid4()), resource_version=1
            ),
            outcome="NO_EFFECT",
            actor=actor,
            effective_principal=actor,
            correlation_id="synthetic-retained-audit",
        )
    before = counts()
    with historical_manual_catalog():
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
            MigrationExecutor(connection).migrate(PREVIOUS)
        assert AuditEvent.objects.filter(id=audit.id, outcome="NO_EFFECT").exists()
        assert counts() == before and catalog() == MIGRATION.CURRENT_CATALOG_DIGEST
