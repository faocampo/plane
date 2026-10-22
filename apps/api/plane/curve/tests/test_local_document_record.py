# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from io import BytesIO

import pytest

from plane.curve.local_document_store import LocalDocumentStore, LocalDocumentUnavailable
from plane.curve.local_document_record import (
    create_local_document_record,
    validate_local_document_record,
    _metadata_digest,
)

pytestmark = pytest.mark.unit
WORKSPACE = "00000000-0000-4000-8000-000000000001"
INITIATIVE = "00000000-0000-4000-8000-000000000002"
ACTOR = "00000000-0000-4000-8000-000000000003"


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    with LocalDocumentStore(root) as value:
        yield value


def uploaded(store, predecessor=None, **overrides):
    source = store.put(workspace_id=WORKSPACE, filename="requirements.md", stream=BytesIO(b"# Synthetic requirements"))
    snapshot = store.put_snapshot(workspace_id=WORKSPACE, source=source)
    arguments = dict(
        store=store,
        workspace_id=WORKSPACE,
        initiative_id=INITIATIVE,
        actor_id=ACTOR,
        uploaded_at="2026-10-21T12:00:00Z",
        snapshot=snapshot,
        predecessor=predecessor,
    )
    return create_local_document_record(**(arguments | overrides))


def test_uploaded_source_has_exact_stored_references_and_version_chain(store):
    first = uploaded(store)
    second = uploaded(store, predecessor=first)
    assert first["version"] == 1 and first["predecessor_id"] is None
    assert second["version"] == 2 and second["predecessor_id"] == first["id"]
    assert first["original"]["digest"] == second["original"]["digest"]
    assert first["snapshot"]["digest"] != second["snapshot"]["digest"]
    assert first["source_kind"] == "LOCAL_UPLOAD"
    assert set(first).isdisjoint({"canonical_url", "provider_connection_id", "content", "filename"})
    copy = validate_local_document_record(first)
    copy["original"]["digest"] = "changed"
    assert first["original"]["digest"] != "changed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "1.0"),
        ("source_kind", "GOOGLE_DOCS"),
        ("version", True),
        ("uploaded_at", "2026-02-31T12:00:00Z"),
        ("uploaded_by", "actor"),
        ("predecessor_id", ACTOR),
        ("normalization_schema_version", "unknown"),
        ("digest", "sha256:" + "0" * 64),
        ("canonical_url", "https://example.invalid"),
    ],
)
def test_closed_source_contract_rejects_invalid_or_changed_metadata(store, field, value):
    record = deepcopy(uploaded(store))
    record[field] = value
    if field != "digest":
        record["digest"] = _metadata_digest(record)
    with pytest.raises(LocalDocumentUnavailable):
        validate_local_document_record(record)


def test_successor_cannot_cross_initiative(store):
    first = uploaded(store)
    with pytest.raises(LocalDocumentUnavailable):
        uploaded(store, predecessor=first, initiative_id=ACTOR)


def test_successor_cannot_reuse_existing_upload(store):
    from plane.curve.local_document_store import StoredDocument

    first = uploaded(store)
    ref = first["snapshot"]
    snapshot = StoredDocument(WORKSPACE, ref["object_id"], ref["digest"], ref["size_bytes"], ref["media_type"])
    with pytest.raises(LocalDocumentUnavailable):
        uploaded(store, predecessor=first, snapshot=snapshot)
