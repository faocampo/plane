# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Queue
from threading import Event

import pytest

from plane.curve.initiative_services import InitiativeKeywordConflict
from plane.curve.item_creation_services import ItemPlacementConflict
from plane.curve.tests.test_item_creation_commands import (
    scope as scope_fixture,
    prepared as prepared_fixture,
    material as material_fixture,
    command,
    counts,
)
from plane.curve.tests.test_feature_editor_command_races import run
from plane.curve.tests.test_feature_editor_storage_races import wait_for_lock
from plane.curve.tests.test_feature_membership_lifetime import sql

scope = scope_fixture
prepared = prepared_fixture
material = material_fixture
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("conflict", ["same_key", "keyword", "placement"])
def test_concurrent_creation_serializes_and_has_one_complete_pair(scope, prepared, material, monkeypatch, conflict):
    from plane.curve import item_creation_services

    original = item_creation_services._append_item_event
    first_pid, second_pid = Queue(), Queue()
    release = Event()

    def hold_first(*args, **kwargs):
        original(*args, **kwargs)
        first_pid.put(sql("SELECT pg_backend_pid()")[0][0])
        assert release.wait(timeout=30), "Test controller did not release first transaction"

    monkeypatch.setattr(item_creation_services, "_append_item_event", hold_first)
    payload = deepcopy(prepared[3])
    if conflict == "placement":
        payload["initiative"]["keyword"] = "OTHER-KEYWORD"

    def competing():
        second_pid.put(sql("SELECT pg_backend_pid()")[0][0])
        return command(
            scope,
            prepared,
            material,
            key="synthetic-item-create" if conflict == "same_key" else "synthetic-competing",
            payload=payload,
        )

    before = counts(scope)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, lambda: command(scope, prepared, material))
        blocker = first_pid.get(timeout=15)
        second = pool.submit(run, competing)
        try:
            wait_for_lock(blocker, second_pid.get(timeout=15))
            assert not second.done()
        finally:
            release.set()
        created = first.result(timeout=30)
        if conflict == "same_key":
            replay = second.result(timeout=30)
            assert replay.replayed and replay.resource_ref == created.resource_ref
        else:
            with pytest.raises(InitiativeKeywordConflict if conflict == "keyword" else ItemPlacementConflict):
                second.result(timeout=30)
    assert [a - b for a, b in zip(counts(scope), before)] == [1, 1, 2, 2, 2, 1]
