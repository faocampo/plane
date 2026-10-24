# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Lossless local upload snapshot; protected bytes never become workflow metadata.

Authorization is the consuming capture runtime's responsibility. This function
reads an authorized server-owned storage reference and produces immutable bytes
suitable for a document checkpoint. It supplies no readiness or approval result.
"""

import base64
import hashlib
import json
from dataclasses import dataclass

from .local_document_store import LocalDocumentStore, LocalDocumentUnavailable, StoredDocument

NORMALIZATION_VERSION = "curve.local-upload.normalized/v1-candidate"


@dataclass(frozen=True, repr=False)
class CapturedLocalDocument:
    source: StoredDocument
    normalized_bytes: bytes
    content_digest: str
    normalization_schema_version: str = NORMALIZATION_VERSION


def capture_local_document(*, store, workspace_id, reference):
    if type(store) is not LocalDocumentStore or type(reference) is not StoredDocument:
        raise LocalDocumentUnavailable
    body = store.read(workspace_id=workspace_id, reference=reference)
    if reference.media_type == "application/pdf":
        if not body.startswith(b"%PDF-"):
            raise LocalDocumentUnavailable
        encoding = "base64"
        content = base64.b64encode(body).decode("ascii")
    elif reference.media_type in {"text/plain", "text/markdown"}:
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError:
            raise LocalDocumentUnavailable from None
        if "\x00" in content:
            raise LocalDocumentUnavailable
        encoding = "utf-8"
    else:
        raise LocalDocumentUnavailable
    normalized = json.dumps(
        {
            "schema_version": NORMALIZATION_VERSION,
            "source": {
                "workspace_id": reference.workspace_id,
                "object_id": reference.object_id,
                "digest": reference.content_digest,
                "size_bytes": reference.byte_length,
                "media_type": reference.media_type,
            },
            "encoding": encoding,
            "content": content,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return CapturedLocalDocument(reference, normalized, "sha256:" + hashlib.sha256(normalized).hexdigest())


def read_local_document_snapshot(*, store, workspace_id, reference):
    """Validate persisted snapshot and original upload together before presentation."""
    if type(store) is not LocalDocumentStore or type(reference) is not StoredDocument:
        raise LocalDocumentUnavailable
    if reference.media_type != "application/json":
        raise LocalDocumentUnavailable
    normalized = store.read(workspace_id=workspace_id, reference=reference)
    try:
        value = json.loads(normalized)
        if type(value) is not dict or set(value) != {"schema_version", "source", "encoding", "content"}:
            raise LocalDocumentUnavailable
        if value["schema_version"] != NORMALIZATION_VERSION:
            raise LocalDocumentUnavailable
        source = value["source"]
        if type(source) is not dict or set(source) != {
            "workspace_id",
            "object_id",
            "digest",
            "size_bytes",
            "media_type",
        }:
            raise LocalDocumentUnavailable
        original = StoredDocument(
            source["workspace_id"], source["object_id"], source["digest"], source["size_bytes"], source["media_type"]
        )
        capture = capture_local_document(store=store, workspace_id=workspace_id, reference=original)
        if capture.normalized_bytes != normalized or capture.content_digest != reference.content_digest:
            raise LocalDocumentUnavailable
        return capture
    except (ValueError, TypeError, KeyError, RecursionError):
        raise LocalDocumentUnavailable from None
