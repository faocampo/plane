# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection, transaction
from plane.curve.models import (
    AuditEvent,
    DomainEvent,
    IdempotencyRecord,
    Milestone,
    OutboxEvent,
    PolicyDecision,
    Product,
    Roadmap,
)
from plane.curve.policy_services import CurvePolicyDenied
from plane.curve.roadmap_policy import RoadmapFormatUnavailable, assert_receipt
from plane.curve.roadmap_services import RoadmapCommandError, execute_hierarchy_command
from plane.curve.services import IdempotencyConflict, OptimisticConcurrencyError, ReplayResourceUnavailable
from plane.db.models import User, Workspace, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def scope(settings):
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "roadmap-command-test"
    owner = User.objects.create(email="owner@example.invalid", username="owner@example.invalid")
    admin = User.objects.create(email="admin@example.invalid", username="admin@example.invalid")
    member = User.objects.create(email="member@example.invalid", username="member@example.invalid")
    workspace = Workspace.objects.create(name="Synthetic workspace", slug="alpha", owner=admin)
    for user, role in [(owner, 15), (admin, 20), (member, 15)]:
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=role, is_active=True)
    actor = {"actor_type": "HUMAN", "actor_id": str(owner.id)}
    product = Product.objects.create(
        workspace_id=workspace.id,
        key="synthetic",
        name="Synthetic Product",
        timezone="UTC",
        owner_user_id=owner.id,
        created_by=actor,
        updated_by=actor,
    )
    return SimpleNamespace(owner=owner, admin=admin, member=member, workspace=workspace, product=product)


def command(scope, action="CREATE_ROADMAP", payload=None, key="synthetic-command-1", user=None, **kwargs):
    request = SimpleNamespace(user=user or scope.owner, headers={})
    return execute_hierarchy_command(
        request=request,
        workspace_slug="alpha",
        product_id=scope.product.id,
        action=action,
        payload={"name": "Synthetic roadmap"} if payload is None else payload,
        raw_idempotency_key=key,
        **kwargs,
    )


def roadmap(scope, **kwargs):
    result = command(scope, **kwargs)
    return Roadmap.objects.get(id=result.resource_ref["resource_id"])


def counts(scope):
    return [
        model.objects.filter(workspace_id=scope.workspace.id).count()
        for model in (Roadmap, Milestone, DomainEvent, OutboxEvent, IdempotencyRecord)
    ]


def milestone(scope, parent, position, key):
    parent.refresh_from_db()
    result = command(
        scope,
        "CREATE_MILESTONE",
        {"name": "Synthetic milestone", "type": "PRODUCT_OUTCOME", "position": position},
        key,
        roadmap_id=parent.id,
        expected_version=parent.version,
    )
    return Milestone.objects.get(id=result.resource_ref["resource_id"])


@pytest.mark.parametrize("creator", ["owner", "admin"])
def test_creator_is_owner_and_retry_preserves_original_result(scope, creator):
    user = getattr(scope, creator)
    first = command(scope, user=user)
    second = command(scope, user=user)
    row = Roadmap.objects.get(id=first.resource_ref["resource_id"])
    assert row.owner_user_id == user.id
    assert first.resource_ref == second.resource_ref
    assert first.response_digest == second.response_digest
    assert second.replayed and not first.replayed
    assert counts(scope) == [1, 0, 1, 1, 1]
    assert AuditEvent.objects.filter(workspace_id=scope.workspace.id).count() == 2
    assert PolicyDecision.objects.filter(workspace_id=scope.workspace.id).count() == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "  "},
        {"name": "Roadmap", "owner_user_id": str(uuid4())},
        {"name": "Roadmap", "actor": {}},
        {"name": "Roadmap", "schema_version": "1.0"},
        {"name": "Roadmap", "horizon_start": "2026-02-30"},
        {"name": "Roadmap", "horizon_start": "2026-03-02", "horizon_end": "2026-03-01"},
    ],
)
def test_invalid_or_forged_creation_has_no_effect(scope, payload):
    with pytest.raises(RoadmapCommandError):
        command(scope, payload=payload)
    assert counts(scope) == [0, 0, 0, 0, 0]
    assert AuditEvent.objects.get(workspace_id=scope.workspace.id).outcome == "NO_EFFECT"


def test_member_has_no_creation_permission(scope):
    with pytest.raises(CurvePolicyDenied):
        command(scope, user=scope.member)
    assert counts(scope) == [0, 0, 0, 0, 0]


@pytest.mark.parametrize("revocation", ["membership", "user", "bot", "product"])
def test_fresh_authority_precedes_successful_replay(scope, revocation):
    command(scope)
    if revocation == "membership":
        WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    elif revocation == "user":
        User.objects.filter(id=scope.owner.id).update(is_active=False)
    elif revocation == "bot":
        User.objects.filter(id=scope.owner.id).update(is_bot=True)
    else:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE curve_product SET state='ARCHIVED', archived_at=CURRENT_TIMESTAMP, "
                "archived_by=created_by WHERE id=%s",
                [scope.product.id],
            )
    with pytest.raises(CurvePolicyDenied):
        command(scope)
    assert counts(scope) == [1, 0, 1, 1, 1]


def test_conflicting_reuse_keeps_original_record(scope):
    row = roadmap(scope)
    with pytest.raises(IdempotencyConflict):
        command(scope, payload={"name": "Changed"})
    row.refresh_from_db()
    assert row.name == "Synthetic roadmap"
    assert counts(scope) == [1, 0, 1, 1, 1]


def test_admin_does_not_override_roadmap_owner(scope):
    row = roadmap(scope)
    with pytest.raises(CurvePolicyDenied):
        command(
            scope,
            "UPDATE_ROADMAP",
            {"name": "Changed"},
            "update",
            user=scope.admin,
            roadmap_id=row.id,
            expected_version=1,
        )
    row.refresh_from_db()
    assert row.version == 1


def test_stale_new_key_rejects_but_original_update_replays(scope):
    row = roadmap(scope)
    args = dict(action="UPDATE_ROADMAP", payload={"name": "Changed"}, roadmap_id=row.id, expected_version=1)
    first = command(scope, key="update", **args)
    replay = command(scope, key="update", **args)
    with pytest.raises(OptimisticConcurrencyError):
        command(scope, key="different", **args)
    assert first.resource_ref == replay.resource_ref
    assert Roadmap.objects.get(id=row.id).version == 2
    assert counts(scope) == [1, 0, 2, 2, 2]


def test_milestone_creation_advances_parent_and_replay_does_not(scope):
    row = roadmap(scope)
    item = milestone(scope, row, 0, "milestone")
    command(
        scope,
        "CREATE_MILESTONE",
        {"name": "Synthetic milestone", "type": "PRODUCT_OUTCOME", "position": 0},
        "milestone",
        roadmap_id=row.id,
        expected_version=1,
    )
    row.refresh_from_db()
    assert row.version == 2 and item.version == 1
    assert counts(scope) == [1, 1, 3, 3, 2]


def test_reorder_is_atomic_with_exact_parent_and_complete_set(scope):
    row = roadmap(scope)
    a, b = milestone(scope, row, 0, "a"), milestone(scope, row, 1, "b")
    before = counts(scope)
    with pytest.raises(RoadmapCommandError):
        command(
            scope,
            "REORDER_MILESTONES",
            {"milestone_ids": [str(a.id)]},
            "missing",
            roadmap_id=row.id,
            expected_version=3,
        )
    assert counts(scope) == before
    first = command(
        scope,
        "REORDER_MILESTONES",
        {"milestone_ids": [str(b.id), str(a.id)]},
        "order",
        roadmap_id=row.id,
        expected_version=3,
    )
    command(
        scope,
        "REORDER_MILESTONES",
        {"milestone_ids": [str(b.id), str(a.id)]},
        "order",
        roadmap_id=row.id,
        expected_version=3,
    )
    a.refresh_from_db()
    b.refresh_from_db()
    row.refresh_from_db()
    assert (a.position, b.position, a.version, b.version, row.version) == (1, 0, 2, 2, 4)
    assert first.resource_ref["resource_version"] == 4


@pytest.mark.parametrize("failure", ["event", "outbox", "audit", "receipt"])
def test_injected_failure_rolls_back_all_effects(scope, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic write failure")

    if failure == "event":
        monkeypatch.setattr(DomainEvent.objects, "create", fail)
    elif failure == "outbox":
        monkeypatch.setattr(OutboxEvent.objects, "create", fail)
    elif failure == "audit":
        monkeypatch.setattr("plane.curve.roadmap_services.append_audit", fail)
    else:
        monkeypatch.setattr(IdempotencyRecord, "save", fail)
    with pytest.raises(RuntimeError):
        command(scope)
    assert counts(scope) == [0, 0, 0, 0, 0]
    assert PolicyDecision.objects.filter(workspace_id=scope.workspace.id).count() == 0


def test_foreign_product_and_roadmap_are_unavailable(scope):
    parent = roadmap(scope)
    actor = {"actor_type": "HUMAN", "actor_id": str(scope.owner.id)}
    other = Product.objects.create(
        workspace_id=uuid4(),
        key="other",
        name="Other",
        timezone="UTC",
        owner_user_id=scope.owner.id,
        created_by=actor,
        updated_by=actor,
    )
    scope.product = other
    with pytest.raises(CurvePolicyDenied):
        command(scope, "UPDATE_ROADMAP", {"name": "Changed"}, "cross", roadmap_id=parent.id, expected_version=1)
    assert Roadmap.objects.get(id=parent.id).name == "Synthetic roadmap"


def test_transferred_owner_cannot_read_old_creation_receipt(scope):
    parent = roadmap(scope)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE curve_roadmap SET owner_user_id=%s WHERE id=%s", [scope.member.id, parent.id])
    with pytest.raises(ReplayResourceUnavailable):
        command(scope)


def test_unsupported_format_rejects_before_replay(scope):
    parent = roadmap(scope)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE curve_roadmap SET schema_version='99' WHERE id=%s", [parent.id])
    with pytest.raises(RoadmapFormatUnavailable):
        command(scope)


def test_receipt_cannot_be_forged_or_used_without_active_context():
    with transaction.atomic(), pytest.raises(PermissionError):
        assert_receipt(SimpleNamespace(_token=object()))


def test_concurrent_identical_creation_has_one_result(scope):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections

    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return command(scope)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0].resource_ref == results[1].resource_ref
    assert sorted(result.replayed for result in results) == [False, True]
    assert counts(scope) == [1, 0, 1, 1, 1]


def test_concurrent_updates_on_one_version_have_one_winner(scope):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections

    parent = roadmap(scope)
    barrier = Barrier(2)

    def run(key):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                command(scope, "UPDATE_ROADMAP", {"name": key}, key, roadmap_id=parent.id, expected_version=1)
                return "accepted"
            except OptimisticConcurrencyError:
                return "stale"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, key) for key in ["first", "second"]]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(results) == ["accepted", "stale"]
    assert Roadmap.objects.get(id=parent.id).version == 2
    assert counts(scope) == [1, 0, 2, 2, 2]


def test_reorder_failure_restores_all_positions_versions_and_events(scope, monkeypatch):
    parent = roadmap(scope)
    a, b = milestone(scope, parent, 0, "a"), milestone(scope, parent, 1, "b")
    before = counts(scope)
    original = OutboxEvent.objects.create
    seen = []

    def fail_second(**kwargs):
        seen.append(1)
        if len(seen) == 2:
            raise RuntimeError("synthetic partial reorder failure")
        return original(**kwargs)

    monkeypatch.setattr(OutboxEvent.objects, "create", fail_second)
    with pytest.raises(RuntimeError):
        command(
            scope,
            "REORDER_MILESTONES",
            {"milestone_ids": [str(b.id), str(a.id)]},
            "order",
            roadmap_id=parent.id,
            expected_version=3,
        )
    a.refresh_from_db()
    b.refresh_from_db()
    parent.refresh_from_db()
    assert (a.position, b.position, a.version, b.version, parent.version) == (0, 1, 1, 1, 3)
    assert counts(scope) == before


def test_policy_evidence_blocks_migration_reversal(scope):
    from django.db.migrations.executor import MigrationExecutor

    command(scope)
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
            MigrationExecutor(connection).migrate([("curve", "0044_roadmap_metadata_history")])
        assert ("curve", "0045_roadmap_hierarchy_commands") in MigrationExecutor(connection).loader.applied_migrations
        with connection.cursor() as cursor:
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(latest)


def test_empty_policy_migration_roundtrip_preserves_previous_seal():
    from django.db.migrations.executor import MigrationExecutor

    latest = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0044_roadmap_metadata_history")])
        with connection.cursor() as cursor:
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(latest)
    with connection.cursor() as cursor:
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")


@pytest.mark.parametrize("damage", ["proof", "source", "migration", "missing", "symlink"])
def test_unqualified_runtime_cannot_write(scope, monkeypatch, damage):
    from pathlib import Path
    from plane.curve import scope_reopening_qualification as qualification
    from plane.curve.prd_commands import PrdCommandError

    target = qualification.ROADMAP_HIERARCHY_SUCCESSOR_PATH
    if damage == "source":
        target = Path(qualification.__file__).parent / "roadmap_services.py"
    elif damage == "migration":
        target = Path(qualification.__file__).parent / "migrations/0045_roadmap_hierarchy_commands.py"
    if damage in {"proof", "source", "migration"}:
        original = Path.read_bytes
        monkeypatch.setattr(
            Path, "read_bytes", lambda path: original(path) + b" " if path == target else original(path)
        )
    elif damage == "missing":
        original = Path.exists
        monkeypatch.setattr(Path, "exists", lambda path: False if path == target else original(path))
    else:
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(PrdCommandError):
        command(scope)
    assert counts(scope) == [0, 0, 0, 0, 0]


def test_event_contract_rejects_unknown_fields_and_wrong_resource_type(scope):
    from copy import deepcopy
    from jsonschema import ValidationError
    from plane.curve.roadmap_services import _EVENT_VALIDATOR

    roadmap(scope)
    event = DomainEvent.objects.get(workspace_id=scope.workspace.id)
    _EVENT_VALIDATOR.validate(event.payload)
    malformed = deepcopy(event.payload)
    malformed["approval"] = "APPROVED"
    with pytest.raises(ValidationError):
        _EVENT_VALIDATOR.validate(malformed)
    malformed = deepcopy(event.payload)
    malformed["action"] = "CREATE_MILESTONE"
    with pytest.raises(ValidationError):
        _EVENT_VALIDATOR.validate(malformed)


def test_milestone_metadata_uses_its_version_and_preserves_parent_order(scope):
    parent = roadmap(scope)
    item = milestone(scope, parent, 4, "milestone")
    changed = command(
        scope,
        "UPDATE_MILESTONE",
        {"name": "Changed", "type": "CALENDAR_PERIOD", "target_start": "2026-10-01"},
        "milestone-update",
        roadmap_id=parent.id,
        milestone_id=item.id,
        expected_version=1,
    )
    item.refresh_from_db()
    parent.refresh_from_db()
    assert item.name == "Changed" and item.position == 4 and item.version == 2
    assert parent.version == 2
    assert changed.resource_ref["resource_id"] == str(item.id)


@pytest.mark.parametrize("deferred", [False, True])
def test_command_preserves_callers_unrelated_constraint_modes(scope, deferred):
    from django.db import IntegrityError

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE synthetic_mode_probe (id integer PRIMARY KEY, value integer, "
                "CONSTRAINT synthetic_mode_probe_uq UNIQUE (value) DEFERRABLE INITIALLY "
                + ("DEFERRED" if deferred else "IMMEDIATE")
                + ") ON COMMIT DROP"
            )
            cursor.execute("INSERT INTO synthetic_mode_probe VALUES (1, 1)")
            if deferred:
                cursor.execute("INSERT INTO synthetic_mode_probe VALUES (2, 1)")
        result = command(scope)
        assert Roadmap.objects.filter(id=result.resource_ref["resource_id"]).exists()
        if deferred:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM synthetic_mode_probe WHERE id=2")
        else:
            with pytest.raises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO synthetic_mode_probe VALUES (2, 1)")


def test_deferred_hierarchy_failure_rolls_back_the_command(scope, monkeypatch):
    from django.db import IntegrityError
    from plane.curve import roadmap_services

    parent = roadmap(scope)
    a, b = milestone(scope, parent, 0, "a"), milestone(scope, parent, 1, "b")
    before = counts(scope)
    original = roadmap_services._update

    def collide(record, values, actor):
        if isinstance(record, Milestone) and "position" in values:
            values = {**values, "position": 0}
        return original(record, values, actor)

    monkeypatch.setattr(roadmap_services, "_update", collide)
    with pytest.raises(IntegrityError):
        command(
            scope,
            "REORDER_MILESTONES",
            {"milestone_ids": [str(b.id), str(a.id)]},
            "synthetic-collision",
            roadmap_id=parent.id,
            expected_version=3,
        )
    assert counts(scope) == before
    a.refresh_from_db()
    b.refresh_from_db()
    parent.refresh_from_db()
    assert (a.position, b.position, a.version, b.version, parent.version) == (0, 1, 1, 1, 3)
