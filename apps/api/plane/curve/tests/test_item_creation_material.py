# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from dataclasses import replace
import pytest

from plane.curve.item_creation_input import ItemCreationInputError, normalize_item_creation
from plane.curve.item_creation_material import scope_requirements
from plane.curve.tests.test_item_creation_input import fixture


def test_scope_requirement_is_detached_and_immutable():
    payload = fixture()
    command = normalize_item_creation(payload, 1)
    requirements = scope_requirements(command)
    payload["scope_body"]["digest"] = "changed"
    assert requirements[0].reference == command.as_payload()["scope_body"]
    assert requirements[0].purposes == frozenset({"ITEM_SCOPE"})
    with pytest.raises(TypeError):
        requirements[0].reference["digest"] = "changed"


def test_scope_requirement_revalidates_internal_command():
    command = normalize_item_creation(fixture(), 1)
    for invalid in ({}, replace(command, expected_version=True), replace(command, canonical_payload=b"{}")):
        with pytest.raises(ItemCreationInputError):
            scope_requirements(invalid)


def test_replay_authorizes_original_and_current_scope_in_stable_order():
    command = normalize_item_creation(fixture(), 1)
    retained = {**command.as_payload()["scope_body"], "object_id": "93000000-0000-4000-8000-000000000001"}
    requirements = scope_requirements(command, retained_scope=retained)
    assert [dict(entry.reference) for entry in requirements] == [retained, command.as_payload()["scope_body"]]
    assert all(entry.purposes == frozenset({"ITEM_SCOPE"}) for entry in requirements)
    assert len(scope_requirements(command, retained_scope=command.as_payload()["scope_body"])) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", "sha256:" + "b" * 64),
        ("size_bytes", 1),
        ("media_type", "application/json"),
        ("editor_schema_version", "2.0"),
    ],
)
def test_replay_cannot_rewrite_same_scope_object_metadata(field, value):
    command = normalize_item_creation(fixture(), 1)
    changed = {**command.as_payload()["scope_body"], field: value}
    with pytest.raises(ItemCreationInputError, match="IMMUTABLE_SCOPE_REFERENCE_CONFLICT"):
        scope_requirements(command, retained_scope=changed)
