# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed inputs for Product-scoped Feature editor management commands.

Workspace, Product, actor, membership generation and grant identity are resolved
by the authorized command adapter. This module supplies no authorization.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from uuid import UUID


class FeatureEditorInputError(Exception):
    code = "FEATURE_EDITOR_COMMAND_INVALID"


@dataclass(frozen=True, slots=True)
class NormalizedEditorCommand:
    action: str
    payload: Mapping[str, str]
    expected_version: int | None


def normalize_editor_command(action, payload, expected_version):
    if not isinstance(payload, dict):
        raise FeatureEditorInputError
    if action == "GRANT_FEATURE_EDITOR":
        if set(payload) != {"member_id"} or expected_version is not None:
            raise FeatureEditorInputError
        member_id = payload["member_id"]
        if not isinstance(member_id, str):
            raise FeatureEditorInputError
        try:
            member_id = str(UUID(member_id))
        except (ValueError, AttributeError) as error:
            raise FeatureEditorInputError from error
        values = {"member_id": member_id}
    elif action == "REVOKE_FEATURE_EDITOR":
        if payload or type(expected_version) is not int or not 1 <= expected_version <= 9223372036854775807:
            raise FeatureEditorInputError
        values = {}
    else:
        raise FeatureEditorInputError
    return NormalizedEditorCommand(action, MappingProxyType(values), expected_version)
