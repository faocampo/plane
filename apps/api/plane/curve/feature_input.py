# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Prepared Feature command inputs; runtime authorization remains separate."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from uuid import UUID
import re


class FeatureInputError(Exception):
    code = "FEATURE_COMMAND_INVALID"


@dataclass(frozen=True, slots=True)
class NormalizedFeatureCommand:
    action: str
    name: str
    description: Mapping | None
    expected_version: int | None

    def as_payload(self):
        return {
            "name": self.name,
            "description": dict(self.description) if self.description is not None else None,
        }


def _require_storable_text(value, limit):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or "\x00" in value:
        raise FeatureInputError
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise FeatureInputError from None


def normalize_feature_command(action, payload, expected_version):
    if action == "CREATE_FEATURE":
        if expected_version is not None:
            raise FeatureInputError
    elif action == "UPDATE_FEATURE":
        if type(expected_version) is not int or not 1 <= expected_version <= 9223372036854775807:
            raise FeatureInputError
    else:
        raise FeatureInputError
    if not isinstance(payload, dict) or set(payload) != {"name", "description"}:
        raise FeatureInputError
    name = payload["name"]
    _require_storable_text(name, 255)
    if not name.strip():
        raise FeatureInputError
    supplied = payload["description"]
    description = None
    if supplied is not None:
        keys = {"object_id", "digest", "size_bytes", "media_type", "editor_schema_version"}
        if not isinstance(supplied, dict) or set(supplied) != keys:
            raise FeatureInputError
        if not isinstance(supplied["object_id"], str):
            raise FeatureInputError
        try:
            object_id = str(UUID(supplied["object_id"]))
        except (ValueError, AttributeError) as error:
            raise FeatureInputError from error
        if not isinstance(supplied["digest"], str) or re.fullmatch(r"sha256:[a-f0-9]{64}", supplied["digest"]) is None:
            raise FeatureInputError
        if type(supplied["size_bytes"]) is not int or supplied["size_bytes"] < 0:
            raise FeatureInputError
        for key, limit in (("media_type", 255), ("editor_schema_version", 100)):
            _require_storable_text(supplied[key], limit)
        description = MappingProxyType({**supplied, "object_id": object_id})
    return NormalizedFeatureCommand(action, name, description, expected_version)
