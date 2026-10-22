# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import base64
import hashlib
from io import BytesIO
import json
from dataclasses import replace

import pytest

from plane.curve.local_document_capture import capture_local_document, NORMALIZATION_VERSION
from plane.curve.local_document_store import LocalDocumentStore, LocalDocumentUnavailable

pytestmark = pytest.mark.unit
WORKSPACE = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    with LocalDocumentStore(root) as value:
        yield value


@pytest.mark.parametrize(
    "filename,body",
    [
        ("x.md", "# PRD\r\n\nRésumé: café ☕\n<script>literal text</script>".encode()),
        ("x.txt", b"\xef\xbb\xbfLeading BOM\r\nTrailing spaces  \n"),
        ("x.pdf", b"%PDF-1.7\n\x00\xff\x01synthetic bytes\n%%EOF"),
    ],
)
def test_capture_preserves_exact_bytes_and_source_identity(store, filename, body):
    ref = store.put(workspace_id=WORKSPACE, filename=filename, stream=BytesIO(body))
    result = capture_local_document(store=store, workspace_id=WORKSPACE, reference=ref)
    snapshot = json.loads(result.normalized_bytes)
    decoded = (
        base64.b64decode(snapshot["content"], validate=True)
        if snapshot["encoding"] == "base64"
        else snapshot["content"].encode("utf-8")
    )
    assert decoded == body
    assert snapshot["schema_version"] == NORMALIZATION_VERSION
    assert snapshot["source"] == dict(
        workspace_id=WORKSPACE,
        object_id=ref.object_id,
        digest=ref.content_digest,
        size_bytes=len(body),
        media_type=ref.media_type,
    )
    assert result.content_digest == "sha256:" + hashlib.sha256(result.normalized_bytes).hexdigest()
    assert (
        result.normalized_bytes
        == capture_local_document(store=store, workspace_id=WORKSPACE, reference=ref).normalized_bytes
    )
    assert snapshot["content"] not in repr(result)


def test_replacement_is_a_distinct_snapshot_even_with_identical_bytes(store):
    refs = [store.put(workspace_id=WORKSPACE, filename="x.md", stream=BytesIO(b"# PRD")) for _ in range(2)]
    captures = [capture_local_document(store=store, workspace_id=WORKSPACE, reference=ref) for ref in refs]
    assert refs[0].content_digest == refs[1].content_digest
    assert captures[0].content_digest != captures[1].content_digest


@pytest.mark.parametrize("change", ["workspace", "digest", "media"])
def test_capture_refuses_invalid_reference(store, change):
    ref = store.put(workspace_id=WORKSPACE, filename="x.md", stream=BytesIO(b"# PRD"))
    if change == "workspace":
        ref = replace(ref, workspace_id="00000000-0000-4000-8000-000000000002")
    elif change == "digest":
        ref = replace(ref, content_digest="sha256:" + "0" * 64)
    else:
        ref = replace(ref, media_type="application/pdf")
    with pytest.raises(LocalDocumentUnavailable):
        capture_local_document(store=store, workspace_id=WORKSPACE, reference=ref)


@pytest.mark.parametrize("filename,body", [("x.txt", b"review this"), ("x.pdf", b"%PDF-1.7\nsynthetic")])
def test_persisted_snapshot_roundtrip_after_reopening_store(store, tmp_path, filename, body):
    from plane.curve.local_document_capture import read_local_document_snapshot

    source = store.put(workspace_id=WORKSPACE, filename=filename, stream=BytesIO(body))
    snapshot = store.put_snapshot(workspace_id=WORKSPACE, source=source)
    assert snapshot.media_type == "application/json"
    store.close()
    with LocalDocumentStore(tmp_path / "documents") as reopened:
        capture = read_local_document_snapshot(store=reopened, workspace_id=WORKSPACE, reference=snapshot)
    assert capture.source == source
    assert capture.content_digest == snapshot.content_digest
    assert len(capture.normalized_bytes) == snapshot.byte_length


def test_public_upload_does_not_accept_snapshot_json(store):
    with pytest.raises(LocalDocumentUnavailable):
        store.put(workspace_id=WORKSPACE, filename="snapshot.json", stream=BytesIO(b"{}"))


def test_maximum_raw_upload_can_expand_into_snapshot(store):
    from plane.curve.local_document_capture import read_local_document_snapshot
    from plane.curve.local_document_store import MAX_DOCUMENT_BYTES, MAX_SNAPSHOT_BYTES

    source = store.put(workspace_id=WORKSPACE, filename="x.txt", stream=BytesIO(b"\x01" * MAX_DOCUMENT_BYTES))
    snapshot = store.put_snapshot(workspace_id=WORKSPACE, source=source)
    assert MAX_DOCUMENT_BYTES < snapshot.byte_length <= MAX_SNAPSHOT_BYTES
    assert read_local_document_snapshot(store=store, workspace_id=WORKSPACE, reference=snapshot).source == source


def test_read_snapshot_rechecks_original_file(store, tmp_path):
    from plane.curve.local_document_capture import read_local_document_snapshot

    source = store.put(workspace_id=WORKSPACE, filename="x.md", stream=BytesIO(b"original"))
    snapshot = store.put_snapshot(workspace_id=WORKSPACE, source=source)
    (tmp_path / "documents" / f"{WORKSPACE}-{source.object_id}").write_bytes(b"modified")
    with pytest.raises(LocalDocumentUnavailable):
        read_local_document_snapshot(store=store, workspace_id=WORKSPACE, reference=snapshot)
