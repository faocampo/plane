# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Native storage boundaries; command permissions and protected payloads have separate acceptance."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.db import connection, transaction, DatabaseError
from django.db.migrations.executor import MigrationExecutor
from plane.curve.models import Product, Initiative, Roadmap, Milestone, Feature, RoadmapItem, RoadmapItemHistory

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def sql(statement, args=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, args)


@pytest.fixture
def graph():
    workspace, user = uuid4(), uuid4()
    actor = {"actor_type": "HUMAN", "actor_id": str(user)}
    product = Product.objects.create(
        workspace_id=workspace,
        key="synthetic-product",
        name="Synthetic Product",
        timezone="UTC",
        owner_user_id=user,
        created_by=actor,
        updated_by=actor,
    )
    common = dict(workspace_id=workspace, product_id=product.id, created_by=actor, updated_by=actor)
    roadmap = Roadmap.objects.create(**common, name="Synthetic Roadmap", owner_user_id=user)
    milestone = Milestone.objects.create(
        **common, roadmap_id=roadmap.id, name="Synthetic Milestone", type="PRODUCT_OUTCOME", position=0
    )
    return common, roadmap, milestone, user


def pair(graph, *, item_first=False, feature=None):
    common, roadmap, milestone, user = graph
    item_id, initiative_id = uuid4(), uuid4()
    if feature is None:
        feature = Feature.objects.create(**common, name="Synthetic Feature")

    def create_item():
        return RoadmapItem.objects.create(
            **common,
            id=item_id,
            roadmap_id=roadmap.id,
            milestone_id=milestone.id,
            feature_id=feature.id,
            defining_initiative_id=initiative_id,
            owner_user_id=user,
            scope_body={},
            priority="MEDIUM",
            confidence="MEDIUM",
            health="OFF_TRACK",
        )

    def create_initiative():
        return Initiative.objects.create(
            **common,
            id=initiative_id,
            mode="ROADMAP",
            roadmap_item_id=item_id,
            keyword="synthetic-" + initiative_id.hex[:12],
            title="Synthetic Initiative",
            description={},
            risk_tier="LOW",
            creator_user_id=user,
        )

    with transaction.atomic():
        if item_first:
            item = create_item()
            create_initiative()
        else:
            create_initiative()
            item = create_item()
        sql("SET CONSTRAINTS ALL IMMEDIATE")
    return item


@pytest.mark.parametrize("item_first", [False, True])
def test_reciprocal_pair_accepts_both_insertion_orders(graph, item_first):
    item = pair(graph, item_first=item_first)
    assert Initiative.objects.get(id=item.defining_initiative_id).roadmap_item_id == item.id
    item.refresh_from_db()
    assert item.health == "OFF_TRACK"


@pytest.mark.parametrize(
    "change",
    [
        "health='INVALID'",
        "declared_progress=101",
        "declared_progress=-1",
        "planned_start='2026-10-01'",
        "planned_start='2026-10-02', planned_end='2026-10-01'",
        "status='COMMITTED', planned_start='2026-10-01', planned_end='2026-10-02'",
        "tombstoned_at=CURRENT_TIMESTAMP, tombstoned_by='{}'",
        "tombstoned_at=CURRENT_TIMESTAMP, tombstoned_by='{}', tombstone_reason=' '",
    ],
)
def test_invalid_item_state_is_rejected_without_changing_retained_row(graph, change):
    item = pair(graph)
    before = RoadmapItem.objects.filter(id=item.id).values().get()
    with pytest.raises(DatabaseError), transaction.atomic():
        sql("UPDATE curve_roadmap_item SET " + change + " WHERE id=%s", [item.id])
    assert RoadmapItem.objects.filter(id=item.id).values().get() == before


@pytest.mark.parametrize("side", ["initiative", "item"])
def test_reciprocal_half_link_cannot_commit(graph, side):
    item = pair(graph)
    with pytest.raises(DatabaseError), transaction.atomic():
        if side == "initiative":
            sql("UPDATE curve_initiative SET roadmap_item_id=%s WHERE id=%s", [uuid4(), item.defining_initiative_id])
        else:
            sql("UPDATE curve_roadmap_item SET defining_initiative_id=%s WHERE id=%s", [uuid4(), item.id])
        sql("SET CONSTRAINTS ALL IMMEDIATE")
    item.refresh_from_db()
    assert Initiative.objects.get(id=item.defining_initiative_id).roadmap_item_id == item.id


def test_cross_workspace_product_reference_cannot_commit(graph):
    common, _, _, user = graph
    with pytest.raises(DatabaseError), transaction.atomic():
        Roadmap.objects.create(**dict(common, workspace_id=uuid4()), name="Synthetic Invalid", owner_user_id=user)
        sql("SET CONSTRAINTS ALL IMMEDIATE")


def test_atomic_position_swap_and_duplicate_final_position(graph):
    common, roadmap, milestone, _ = graph
    second = Milestone.objects.create(
        **common, roadmap_id=roadmap.id, name="Second", type="PRODUCT_OUTCOME", position=1
    )
    with transaction.atomic():
        sql("UPDATE curve_milestone SET position=1 WHERE id=%s", [milestone.id])
        sql("UPDATE curve_milestone SET position=0 WHERE id=%s", [second.id])
        sql("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(DatabaseError), transaction.atomic():
        sql("UPDATE curve_milestone SET position=0 WHERE id=%s", [milestone.id])
        sql("SET CONSTRAINTS ALL IMMEDIATE")
    assert list(Milestone.objects.order_by("position").values_list("id", flat=True)) == [second.id, milestone.id]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid='curve_milestone'::regclass "
            "AND tgname='curve_mstone_position_recheck' AND tgisinternal AND tgenabled='O'"
        )
        assert cursor.fetchone()[0] == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE curve_roadmap_item_history SET sequence=2",
        "DELETE FROM curve_roadmap_item_history",
        "TRUNCATE curve_roadmap_item_history",
    ],
)
def test_item_history_remains_append_only(graph, statement):
    item = pair(graph)
    RoadmapItemHistory.objects.create(
        workspace_id=item.workspace_id,
        product_id=item.product_id,
        roadmap_item_id=item.id,
        sequence=1,
        recorded_at=item.updated_at,
        recorded_by=item.updated_by,
        change_type="PROGRESS_CHANGED",
        before_version=1,
        after_version=2,
        payload={},
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        sql(statement)
    assert RoadmapItemHistory.objects.get(roadmap_item_id=item.id).sequence == 1


@pytest.mark.parametrize("table", ["curve_roadmap", "curve_milestone", "curve_feature", "curve_roadmap_item"])
def test_aggregate_deletion_is_refused(graph, table):
    pair(graph)
    with pytest.raises(DatabaseError), transaction.atomic():
        sql("DELETE FROM " + table)


def test_populated_reverse_is_refused(graph):
    pair(graph)
    with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE"), transaction.atomic():
        MigrationExecutor(connection).migrate([("curve", "0042_local_new_work_review")])
    from plane.curve.scope_reopening_qualification import require_reopening_qualification

    with transaction.atomic():
        require_reopening_qualification()


def test_upgrade_and_empty_reverse_preserve_existing_product_and_historical_seals():
    module = import_module("plane.curve.migrations.0043_roadmap_domain")
    previous = import_module("plane.curve.migrations.0042_local_new_work_review")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0042_local_new_work_review")])
        user, workspace = uuid4(), uuid4()
        actor = {"actor_type": "HUMAN", "actor_id": str(user)}
        product = Product.objects.create(
            workspace_id=workspace,
            key="preserved",
            name="Synthetic Preserved",
            timezone="UTC",
            owner_user_id=user,
            created_by=actor,
            updated_by=actor,
        )
        before = Product.objects.filter(id=product.id).values().get()
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM curve_local_new_work_coverage")
            seal = cursor.fetchall()
        for _ in range(2):
            MigrationExecutor(connection).migrate([("curve", "0043_roadmap_domain")])
            assert Product.objects.filter(id=product.id).values().get() == before
            with connection.cursor() as cursor:
                assert previous._catalog(cursor) == module.CURRENT_CATALOG_DIGEST
                cursor.execute("SELECT * FROM curve_local_new_work_coverage")
                assert cursor.fetchall() == seal
                cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
            MigrationExecutor(connection).migrate([("curve", "0042_local_new_work_review")])
            with connection.cursor() as cursor:
                assert previous._catalog(cursor) == module.BASELINE_CATALOG_DIGEST
                cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)


def test_concurrent_duplicate_feature_placement_has_one_atomic_winner(graph):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections

    common, _, milestone, _ = graph
    feature = Feature.objects.create(**common, name="Shared Synthetic Feature")
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            pair(graph, feature=feature)
            return "accepted"
        except DatabaseError as error:
            assert error.__cause__.diag.constraint_name == "curve_ritem_placement_uq"
            return "rejected"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == ["accepted", "rejected"]
    item = RoadmapItem.objects.get(milestone_id=milestone.id, feature_id=feature.id)
    assert Initiative.objects.filter(workspace_id=common["workspace_id"]).count() == 1
    assert Initiative.objects.get(id=item.defining_initiative_id).roadmap_item_id == item.id


@pytest.mark.parametrize("kind", ["roadmap", "milestone", "feature", "item"])
def test_application_clock_rollback_preserves_creation_and_version_order(graph, monkeypatch, kind):
    from datetime import timedelta
    from django.utils import timezone

    common, roadmap, milestone, _ = graph
    if kind == "roadmap":
        record = roadmap
    elif kind == "milestone":
        record = milestone
    elif kind == "feature":
        record = Feature.objects.create(**common, name="Synthetic Clock Feature")
    else:
        record = pair(graph)
    original_created, original_actor = record.created_at, record.created_by
    instant = record.updated_at - timedelta(hours=1)
    monkeypatch.setattr(timezone, "now", lambda: instant)
    record.version += 1
    record.save()
    record.refresh_from_db()
    assert record.created_at == original_created
    assert record.created_by == original_actor
    assert record.updated_at == instant < original_created
    assert record.updated_at.utcoffset() == timedelta(0)
    assert record.version == 2
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT column_name, column_default FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
              AND column_name IN ('created_at','updated_at') ORDER BY column_name""",
            [record._meta.db_table],
        )
        assert cursor.fetchall() == [("created_at", None), ("updated_at", None)]
