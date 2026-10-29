# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import os
from types import MappingProxyType
from unittest.mock import patch
from uuid import UUID

import pytest

from plane.curve.item_creation_material import ItemScopeRequirement
from plane.curve.item_local_material import EDITION, LocalItemMaterialResolver, ItemMaterialUnavailable
from plane.curve.item_scope_preparation import (
    ItemScopeStorageContext,
    normalize_scope_document,
    prepare_scope_document,
)


IDS = [f"96000000-0000-4000-8000-{n:012d}" for n in range(1, 7)]
CONTEXT = ItemScopeStorageContext(*IDS[:5], 0)


@pytest.fixture
def material(tmp_path):
    tmp_path.chmod(0o700)
    for name, raw in (
        ("catalog.lock", b""),
        ("catalog.json", json.dumps(dict(schema_version=EDITION, generation=1, objects={})).encode()),
    ):
        path = tmp_path / name
        path.write_bytes(raw)
        path.chmod(0o600)
    return tmp_path


def capture(resolver, ref, **overrides):
    params = dict(
        workspace_id=CONTEXT.workspace_id,
        product_id=CONTEXT.product_id,
        roadmap_id=CONTEXT.roadmap_id,
        actor_id=CONTEXT.actor_id,
        membership_id=CONTEXT.membership_id,
        membership_generation=0,
    )
    params.update(overrides)
    return resolver.capture(**params, requirements=(ItemScopeRequirement(MappingProxyType(dict(ref))),))


def test_prepared_bytes_are_immutable_scoped_and_readable_by_exact_membership(material):
    with LocalItemMaterialResolver(str(material)) as resolver:
        ref = prepare_scope_document(resolver, context=CONTEXT, payload={"body": "# Example\nCafé outcome"})
        assert (material / ref["object_id"]).read_bytes() == normalize_scope_document(
            {"body": "# Example\nCafé outcome"}
        )
        with resolver.lease():
            observed = capture(resolver, ref)
            resolver.revalidate(observed)
            assert observed.observations[0]["classification"] == "RESTRICTED"
        for difference in ({"actor_id": IDS[5]}, {"membership_generation": 1}, {"roadmap_id": IDS[5]}):
            with resolver.lease(), pytest.raises(ItemMaterialUnavailable):
                capture(resolver, ref, **difference)
    catalog = json.loads((material / "catalog.json").read_bytes())
    assert catalog["generation"] == 2
    assert list(catalog["objects"][ref["object_id"]]["grants"]) == [CONTEXT.actor_id]
    assert os.stat(material / ref["object_id"]).st_mode & 0o777 == 0o600
    with pytest.raises(TypeError):
        ref["size_bytes"] = 0


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"body": ""},
        {"body": "   "},
        {"body": "\x00"},
        {"body": "\ud800"},
        {"body": "a" * 20001},
        {"body": "Example", "grants": {}},
        {"body": "Example", "object_id": IDS[5]},
    ],
)
def test_invalid_input_never_writes_or_accepts_authority(material, payload):
    before = (material / "catalog.json").read_bytes()
    with LocalItemMaterialResolver(str(material)) as resolver, pytest.raises(ItemMaterialUnavailable):
        prepare_scope_document(resolver, context=CONTEXT, payload=payload)
    assert (material / "catalog.json").read_bytes() == before
    assert sorted(path.name for path in material.iterdir()) == ["catalog.json", "catalog.lock"]


def test_new_preparations_preserve_previous_objects_and_grants(material):
    with LocalItemMaterialResolver(str(material)) as resolver:
        first = prepare_scope_document(resolver, context=CONTEXT, payload={"body": "First"})
        previous = json.loads((material / "catalog.json").read_bytes())["objects"]
        second = prepare_scope_document(resolver, context=CONTEXT, payload={"body": "Second"})
        assert first["object_id"] != second["object_id"]
        current = json.loads((material / "catalog.json").read_bytes())
        assert current["generation"] == 3
        assert current["objects"][first["object_id"]] == previous[first["object_id"]]
        with resolver.lease():
            capture(resolver, first)
            capture(resolver, second)


def test_preparation_waits_for_reader_lease_without_writing(material):
    with LocalItemMaterialResolver(str(material)) as reader, reader.lease():
        with LocalItemMaterialResolver(str(material)) as writer, pytest.raises(ItemMaterialUnavailable):
            prepare_scope_document(writer, context=CONTEXT, payload={"body": "Blocked"})
    assert json.loads((material / "catalog.json").read_bytes())["objects"] == {}
    assert sorted(path.name for path in material.iterdir()) == ["catalog.json", "catalog.lock"]


def test_catalog_publication_failure_retains_no_readable_grant(material):
    before = (material / "catalog.json").read_bytes()
    with LocalItemMaterialResolver(str(material)) as resolver:
        with patch("plane.curve.item_scope_preparation.os.replace", side_effect=OSError("synthetic failure")):
            with pytest.raises(ItemMaterialUnavailable):
                prepare_scope_document(resolver, context=CONTEXT, payload={"body": "Retained orphan"})
    assert (material / "catalog.json").read_bytes() == before
    assert not list(material.glob(".scope-catalog-*"))
    assert len([p for p in material.iterdir() if p.name not in {"catalog.json", "catalog.lock"}]) == 1


def test_identity_collision_cannot_overwrite_existing_material(material):
    with LocalItemMaterialResolver(str(material)) as resolver:
        first = prepare_scope_document(resolver, context=CONTEXT, payload={"body": "Original"})
        before = (material / first["object_id"]).read_bytes()
        with patch("plane.curve.item_scope_preparation.uuid4", return_value=UUID(first["object_id"])):
            with pytest.raises(ItemMaterialUnavailable):
                prepare_scope_document(resolver, context=CONTEXT, payload={"body": "Replacement"})
        assert (material / first["object_id"]).read_bytes() == before


def test_catalog_symlink_is_rejected(material):
    target = material / "catalog-original.json"
    (material / "catalog.json").rename(target)
    (material / "catalog.json").symlink_to(target)
    with LocalItemMaterialResolver(str(material)) as resolver, pytest.raises((ItemMaterialUnavailable, ValueError)):
        prepare_scope_document(resolver, context=CONTEXT, payload={"body": "Rejected"})
    assert json.loads(target.read_bytes())["objects"] == {}


def test_noncooperative_catalog_change_is_never_overwritten(material, monkeypatch):
    from plane.curve import item_scope_preparation as preparation

    original = preparation._write_new
    changed = dict(schema_version=EDITION, generation=9, objects={})

    def change_after_body(resolver, name, raw):
        original(resolver, name, raw)
        if not name.startswith("."):
            (material / "catalog.json").write_text(json.dumps(changed))

    monkeypatch.setattr(preparation, "_write_new", change_after_body)
    with LocalItemMaterialResolver(str(material)) as resolver, pytest.raises(ItemMaterialUnavailable):
        prepare_scope_document(resolver, context=CONTEXT, payload={"body": "Concurrent scope"})
    assert json.loads((material / "catalog.json").read_bytes()) == changed
    assert not list(material.glob(".scope-catalog-*"))
