# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Versioned local PRD source metadata; never an access or approval grant.

The native writer owns locking, actor authorization, version allocation and
persistence. ExternalDocumentBinding remains the external-provider contract.
No provider identity or URL is fabricated for an uploaded file.
"""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import uuid

from .local_document_capture import NORMALIZATION_VERSION, read_local_document_snapshot
from .local_document_store import MAX_DOCUMENT_BYTES, MAX_SNAPSHOT_BYTES, LocalDocumentUnavailable, StoredDocument

SCHEMA_VERSION = "curve.local-prd-source/v1-candidate"
_FIELDS = {
    "schema_version",
    "source_kind",
    "id",
    "workspace_id",
    "initiative_id",
    "version",
    "predecessor_id",
    "uploaded_by",
    "uploaded_at",
    "original",
    "snapshot",
    "normalization_schema_version",
    "digest",
}
_REF_FIELDS = {"object_id", "digest", "size_bytes", "media_type"}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_INSTANT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z\Z")


def _require(condition):
    if not condition:
        raise LocalDocumentUnavailable


def _id(value):
    _require(type(value) is str and str(uuid.UUID(value)) == value)


def _digest(value):
    _require(type(value) is str and _DIGEST.fullmatch(value) is not None)


def _metadata_digest(value):
    raw = json.dumps(
        {k: v for k, v in value.items() if k != "digest"}, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _reference(value, *, snapshot):
    _require(type(value) is dict and set(value) == _REF_FIELDS)
    _id(value["object_id"])
    _digest(value["digest"])
    _require(
        type(value["size_bytes"]) is int
        and 0 < value["size_bytes"] <= (MAX_SNAPSHOT_BYTES if snapshot else MAX_DOCUMENT_BYTES)
    )
    _require(
        value["media_type"]
        in (("application/json",) if snapshot else ("application/pdf", "text/markdown", "text/plain"))
    )


def validate_local_document_record(value):
    try:
        _require(type(value) is dict and set(value) == _FIELDS)
        _require(value["schema_version"] == SCHEMA_VERSION and value["source_kind"] == "LOCAL_UPLOAD")
        _require(value["normalization_schema_version"] == NORMALIZATION_VERSION)
        for key in ("id", "workspace_id", "initiative_id", "uploaded_by"):
            _id(value[key])
        _require(type(value["version"]) is int and 1 <= value["version"] <= 9007199254740991)
        if value["version"] == 1:
            _require(value["predecessor_id"] is None)
        else:
            _id(value["predecessor_id"])
            _require(value["predecessor_id"] != value["id"])
        _require(type(value["uploaded_at"]) is str and _INSTANT.fullmatch(value["uploaded_at"]) is not None)
        datetime.fromisoformat(value["uploaded_at"].replace("Z", "+00:00"))
        _reference(value["original"], snapshot=False)
        _reference(value["snapshot"], snapshot=True)
        _require(value["original"]["object_id"] != value["snapshot"]["object_id"])
        _digest(value["digest"])
        _require(_metadata_digest(value) == value["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def _ref(value):
    return dict(
        object_id=value.object_id,
        digest=value.content_digest,
        size_bytes=value.byte_length,
        media_type=value.media_type,
    )


def create_local_document_record(
    *, store, workspace_id, initiative_id, actor_id, uploaded_at, snapshot, predecessor=None
):
    """Build exact metadata from stored bytes after the caller's upload authorization."""
    _require(type(snapshot) is StoredDocument)
    capture = read_local_document_snapshot(store=store, workspace_id=workspace_id, reference=snapshot)
    previous = validate_local_document_record(predecessor) if predecessor is not None else None
    if previous:
        _require(previous["workspace_id"] == workspace_id and previous["initiative_id"] == initiative_id)
        _require(previous["original"]["object_id"] != capture.source.object_id)
        _require(previous["snapshot"]["object_id"] != snapshot.object_id)
    value = dict(
        schema_version=SCHEMA_VERSION,
        source_kind="LOCAL_UPLOAD",
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        initiative_id=initiative_id,
        version=previous["version"] + 1 if previous else 1,
        predecessor_id=previous["id"] if previous else None,
        uploaded_by=actor_id,
        uploaded_at=uploaded_at,
        original=_ref(capture.source),
        snapshot=_ref(snapshot),
        normalization_schema_version=NORMALIZATION_VERSION,
    )
    value["digest"] = _metadata_digest(value)
    return validate_local_document_record(value)
