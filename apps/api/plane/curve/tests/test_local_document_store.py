# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from dataclasses import replace
from io import BytesIO
import os
import uuid

import pytest

from plane.curve.local_document_store import LocalDocumentStore, LocalDocumentUnavailable, MAX_DOCUMENT_BYTES

pytestmark = pytest.mark.unit
WORKSPACE = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "documents"
    path.mkdir(mode=0o700)
    return path


@pytest.mark.parametrize(
    "filename,body",
    [("proposal.md", b"# Requirements"), ("notes.txt", b"Review me"), ("PRD.PDF", b"%PDF-1.7\nsynthetic")],
)
def test_roundtrip_has_private_opaque_path(root, filename, body):
    with LocalDocumentStore(root) as store:
        ref = store.put(workspace_id=WORKSPACE, filename=filename, stream=BytesIO(body))
        assert store.read(workspace_id=WORKSPACE, reference=ref) == body
        paths = list(root.iterdir())
        assert len(paths) == 1 and paths[0].name != filename
        assert paths[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "filename,body",
    [
        ("x.docx", b"no"),
        ("x.pdf", b"not a PDF"),
        ("x.txt", b"\xff"),
        ("x.md", b"a\0b"),
        ("x.md", b""),
        ("x.txt", b"x" * (MAX_DOCUMENT_BYTES + 1)),
    ],
)
def test_invalid_upload_leaves_no_object(root, filename, body):
    with LocalDocumentStore(root) as store, pytest.raises(LocalDocumentUnavailable):
        store.put(workspace_id=WORKSPACE, filename=filename, stream=BytesIO(body))
    assert not list(root.iterdir())


@pytest.mark.parametrize("change", ["workspace", "digest", "length", "permissions", "content", "symlink", "hardlink"])
def test_read_rejects_wrong_scope_or_modified_object(root, change):
    with LocalDocumentStore(root) as store:
        ref = store.put(workspace_id=WORKSPACE, filename="x.md", stream=BytesIO(b"original"))
        path = next(root.iterdir())
        workspace = WORKSPACE
        if change == "workspace":
            workspace = str(uuid.uuid4())
        elif change == "digest":
            ref = replace(ref, content_digest="sha256:" + "0" * 64)
        elif change == "length":
            ref = replace(ref, byte_length=9)
        elif change == "permissions":
            path.chmod(0o644)
        elif change == "content":
            path.write_bytes(b"modified")
        elif change == "symlink":
            target = root / "target"
            path.rename(target)
            path.symlink_to(target)
        elif change == "hardlink":
            os.link(path, root / "alias")
        with pytest.raises(LocalDocumentUnavailable):
            store.read(workspace_id=workspace, reference=ref)


def test_root_must_be_private_and_not_symlink(root):
    root.chmod(0o755)
    with pytest.raises(LocalDocumentUnavailable):
        LocalDocumentStore(root)
    root.chmod(0o700)
    alias = root.parent / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(LocalDocumentUnavailable):
        LocalDocumentStore(alias)
