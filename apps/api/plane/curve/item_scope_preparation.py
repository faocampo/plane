# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Local protected scope storage adapter; callers owe fresh native authorization.

This module is not an endpoint or policy grant. The command service must resolve
current Roadmap ownership and membership lifetime, record its policy decision,
and hold native locks while using this adapter. References are server generated;
request data cannot select identities, classification, destination or grants.
"""

from copy import deepcopy
from dataclasses import dataclass
import fcntl
import os
from types import MappingProxyType
from uuid import uuid4

from plane.curve.item_local_material import (
    CATALOG_LIMIT,
    DESTINATION,
    ItemMaterialUnavailable,
    LocalItemMaterialResolver,
    _canonical,
    _counter,
    _decode,
    _digest,
    _require,
    _uuid,
)
from plane.curve.manual_plan_v2.synthetic import _stamp


SCOPE_LIMIT = 20000
SCOPE_SCHEMA = "curve.item-scope-markdown/v1-candidate"


def normalize_scope_document(payload):
    _require(type(payload) is dict and set(payload) == {"body"}, "ITEM_SCOPE_INPUT_INVALID")
    body = payload["body"]
    _require(
        type(body) is str and 1 <= len(body) <= SCOPE_LIMIT and body.strip() and "\x00" not in body,
        "ITEM_SCOPE_INPUT_INVALID",
    )
    try:
        raw = _canonical({"schema_version": "1.0", "format": "MARKDOWN", "body": body})
        body.encode("utf-8", errors="strict")
    except (UnicodeError, ValueError):
        raise ItemMaterialUnavailable("ITEM_SCOPE_INPUT_INVALID") from None
    _require(len(raw) <= 128 * 1024, "ITEM_SCOPE_INPUT_INVALID")
    return raw


@dataclass(frozen=True, slots=True)
class ItemScopeStorageContext:
    """Storage coordinates supplied by the authorized service, never decoded from a request."""

    workspace_id: str
    product_id: str
    roadmap_id: str
    actor_id: str
    membership_id: str
    membership_generation: int

    def validate(self):
        for value in (self.workspace_id, self.product_id, self.roadmap_id, self.actor_id, self.membership_id):
            _uuid(value)
        _counter(self.membership_generation, 0)


def _root_current(resolver):
    current = resolver._files._open_root(resolver._files.root)
    try:
        observed, retained = os.fstat(current), os.fstat(resolver._files.root_fd)
        _require((observed.st_dev, observed.st_ino) == (retained.st_dev, retained.st_ino))
    finally:
        os.close(current)


def _write_new(resolver, name, raw):
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=resolver._files.root_fd
    )
    try:
        pending = memoryview(raw)
        while pending:
            written = os.write(descriptor, pending)
            _require(written > 0)
            pending = pending[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_scope_document(resolver, *, context, payload):
    """Publish immutable bytes and an actor-only catalog entry under the stable lock.

    No existing grant is changed. Failure can retain an unreferenced private file;
    it never returns a usable reference before catalog durability. Database receipt
    replay and cleanup after proven non-reference belong to the command service.
    The exclusive lock prevents readers from observing partial catalog publication.
    """
    _require(type(resolver) is LocalItemMaterialResolver and resolver._lease_token is None)
    _require(type(context) is ItemScopeStorageContext)
    context.validate()
    raw = normalize_scope_document(payload)
    object_id = str(uuid4())
    reference = dict(
        object_id=object_id,
        digest=_digest(raw),
        size_bytes=len(raw),
        media_type="application/json",
        editor_schema_version=SCOPE_SCHEMA,
    )
    temporary = None
    try:
        with resolver._lock(fcntl.LOCK_EX) as lock_fence:
            previous, catalog_fence = resolver._files._read("catalog.json", CATALOG_LIMIT)
            catalog = _decode(previous)
            _require(len(catalog["objects"]) < 512, "ITEM_SCOPE_CAPACITY_REACHED")
            _require(object_id not in catalog["objects"])
            replacement = deepcopy(catalog)
            replacement["generation"] += 1
            replacement["objects"][object_id] = dict(
                workspace_id=context.workspace_id,
                product_id=context.product_id,
                roadmap_id=context.roadmap_id,
                reference=reference,
                access_envelope_id=str(uuid4()),
                classification="RESTRICTED",
                destination=DESTINATION,
                grants={
                    context.actor_id: dict(
                        membership_id=context.membership_id,
                        membership_generation=context.membership_generation,
                        acl_generation=1,
                        can_read=True,
                    )
                },
            )
            proposed = _canonical(replacement)
            _decode(proposed)
            _root_current(resolver)
            _write_new(resolver, object_id, raw)
            os.fsync(resolver._files.root_fd)
            temporary = ".scope-catalog-" + str(uuid4())
            _write_new(resolver, temporary, proposed)
            # Directory mtime changes are ours; the root identity and stable lock
            # still must match. Reopen by path before publication to detect swaps.
            _root_current(resolver)
            resolver._files.root_stamp = _stamp(os.fstat(resolver._files.root_fd))
            current_catalog, _ = resolver._files._read("catalog.json", CATALOG_LIMIT)
            _require(current_catalog == previous, "ITEM_SCOPE_CATALOG_CHANGED")
            resolver._files.recheck((lock_fence, catalog_fence))
            os.replace(
                temporary, "catalog.json", src_dir_fd=resolver._files.root_fd, dst_dir_fd=resolver._files.root_fd
            )
            temporary = None
            os.fsync(resolver._files.root_fd)
            resolver._files.root_stamp = _stamp(os.fstat(resolver._files.root_fd))
        return MappingProxyType(reference)
    except ItemMaterialUnavailable:
        raise
    except (OSError, ValueError, TypeError, AttributeError) as error:
        raise ItemMaterialUnavailable("ITEM_SCOPE_STORAGE_UNAVAILABLE") from error
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=resolver._files.root_fd)
            except FileNotFoundError:
                pass
