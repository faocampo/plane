# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed protected scope requirements for joint Item creation.

These requirements identify material. The qualified resolver must independently
verify current access and hold its lease through the enclosing durable commit.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from plane.curve.item_creation_input import (
    ItemCreationInputError,
    NormalizedItemCreation,
    normalize_item_creation,
    identity,
    keys,
    text,
)
import re


def normalize_scope_reference(reference):
    keys(reference, ("object_id", "digest", "size_bytes", "media_type", "editor_schema_version"))
    if not isinstance(reference["digest"], str) or re.fullmatch(r"sha256:[a-f0-9]{64}", reference["digest"]) is None:
        raise ItemCreationInputError
    if type(reference["size_bytes"]) is not int or reference["size_bytes"] < 0:
        raise ItemCreationInputError
    return {
        "object_id": identity(reference["object_id"]),
        "digest": reference["digest"],
        "size_bytes": reference["size_bytes"],
        "media_type": text(reference["media_type"], 255),
        "editor_schema_version": text(reference["editor_schema_version"], 100),
    }


@dataclass(frozen=True, slots=True)
class ItemScopeRequirement:
    reference: Mapping
    purposes: frozenset[str] = frozenset({"ITEM_SCOPE"})


def scope_requirements(command, *, retained_scope=None):
    if not isinstance(command, NormalizedItemCreation):
        raise ItemCreationInputError("NORMALIZED_ITEM_CREATION_REQUIRED")
    payload = normalize_item_creation(command.as_payload(), command.expected_version).as_payload()
    requested = normalize_scope_reference(payload["scope_body"])
    references = {requested["object_id"]: requested}
    if retained_scope is not None:
        retained = normalize_scope_reference(retained_scope)
        previous = references.get(retained["object_id"])
        if previous is not None and previous != retained:
            raise ItemCreationInputError("IMMUTABLE_SCOPE_REFERENCE_CONFLICT")
        references[retained["object_id"]] = retained
    return tuple(ItemScopeRequirement(MappingProxyType(references[key])) for key in sorted(references))
