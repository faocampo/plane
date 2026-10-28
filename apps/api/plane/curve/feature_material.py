# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Immutable material requirements; these identify inputs, never grant access.

The native adapter must resolve every entry through its qualified protected
object authority under current scope and retain/revalidate the resulting fences.
A cleared description still requires access to the retained material.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from plane.curve.feature_input import NormalizedFeatureCommand, normalize_feature_command


class FeatureMaterialError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FeatureMaterialRequirement:
    reference: Mapping
    purposes: frozenset[str]


def description_requirements(command, *, retained_description):
    if not isinstance(command, NormalizedFeatureCommand):
        raise FeatureMaterialError("NORMALIZED_FEATURE_COMMAND_REQUIRED")
    # Revalidate even internal constructed dataclasses; their type is no receipt.
    normalized = normalize_feature_command(command.action, command.as_payload(), command.expected_version)
    if command.action == "CREATE_FEATURE" and retained_description is not None:
        raise FeatureMaterialError("CREATE_HAS_RETAINED_DESCRIPTION")
    retained = normalize_feature_command(
        "UPDATE_FEATURE",
        {"name": normalized.name, "description": retained_description},
        1,
    ).description
    by_id = {}
    for purpose, reference in (
        ("RETAINED", retained),
        ("REQUESTED", normalized.description),
    ):
        if reference is None:
            continue
        identity = reference["object_id"]
        previous = by_id.get(identity)
        if previous is not None:
            if previous.reference != reference:
                raise FeatureMaterialError("IMMUTABLE_OBJECT_REFERENCE_CONFLICT")
            purposes = previous.purposes | {purpose}
        else:
            purposes = frozenset({purpose})
        by_id[identity] = FeatureMaterialRequirement(MappingProxyType(dict(reference)), frozenset(purposes))
    # Stable acquisition order for a native adapter locking several objects.
    return tuple(by_id[identity] for identity in sorted(by_id))
