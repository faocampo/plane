# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Closed retained result for a server-created reciprocal Initiative/Item pair."""

from uuid import UUID

from plane.curve.services import ReplayResourceUnavailable, operation_response_digest


def pair_reference(*, item_id, initiative_id):
    result = {
        "resource_type": "ROADMAP_ITEM",
        "resource_id": str(item_id),
        "resource_version": 1,
        "initiative_ref": {
            "resource_type": "INITIATIVE",
            "resource_id": str(initiative_id),
            "resource_version": 1,
        },
    }
    validate_pair_reference(result)
    return result


def validate_pair_reference(reference):
    if type(reference) is not dict or set(reference) != {
        "resource_type",
        "resource_id",
        "resource_version",
        "initiative_ref",
    }:
        raise ReplayResourceUnavailable
    initiative = reference["initiative_ref"]
    if type(initiative) is not dict or set(initiative) != {"resource_type", "resource_id", "resource_version"}:
        raise ReplayResourceUnavailable
    identities = []
    for value, resource_type in ((reference, "ROADMAP_ITEM"), (initiative, "INITIATIVE")):
        if (
            value["resource_type"] != resource_type
            or type(value["resource_version"]) is not int
            or value["resource_version"] != 1
        ):
            raise ReplayResourceUnavailable
        try:
            identity = UUID(value["resource_id"])
        except (ValueError, TypeError, AttributeError) as error:
            raise ReplayResourceUnavailable from error
        if str(identity) != value["resource_id"]:
            raise ReplayResourceUnavailable
        identities.append(identity)
    if identities[0] == identities[1]:
        raise ReplayResourceUnavailable
    return tuple(identities)


def validate_retained_creation(record):
    identities = validate_pair_reference(record.response_resource_ref)
    if (
        record.state != "COMPLETED"
        or type(record.response_status) is not int
        or record.response_status != 201
        or record.response_digest
        != operation_response_digest(response_status=201, resource_ref=record.response_resource_ref)
    ):
        raise ReplayResourceUnavailable
    return identities
