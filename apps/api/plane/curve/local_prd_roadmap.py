# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Roadmap Product-review subjects with immutable Item scope references.

Runtime authority selects this edition through the qualified Roadmap review
successor. Existing submission editions retain their original standalone or
retained-scope meaning.
"""

from copy import deepcopy

from .item_creation_input import ItemCreationInputError
from .item_creation_material import normalize_scope_reference
from .local_document_store import LocalDocumentUnavailable
from .local_prd_new_work import (
    FIELDS as NEW_WORK_FIELDS,
    SCHEMA_VERSION as NEW_WORK_SCHEMA,
    create_new_work_submission,
    require_current_new_work_submission,
    validate_new_work_submission,
)
from .local_prd_review import _id, _pin, _require

SCHEMA_VERSION = "curve.local-prd-submission/v3-roadmap-candidate"
FIELDS = NEW_WORK_FIELDS | {"roadmap_item_id", "roadmap_item_scope"}


def _standalone_projection(value):
    """Reuse field validation only; never persist or expose this projection."""
    projected = {key: deepcopy(value[key]) for key in NEW_WORK_FIELDS}
    projected["schema_version"] = NEW_WORK_SCHEMA
    projected["digest"] = _pin(projected)
    return projected


def validate_roadmap_submission(value):
    try:
        _require(type(value) is dict and set(value) == FIELDS)
        _require(value["schema_version"] == SCHEMA_VERSION)
        _id(value["roadmap_item_id"])
        _require(normalize_scope_reference(value["roadmap_item_scope"]) == value["roadmap_item_scope"])
        validate_new_work_submission(_standalone_projection(value))
        _require(_pin(value) == value["digest"])
    except (
        ItemCreationInputError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        raise LocalDocumentUnavailable from None
    return deepcopy(value)


def create_roadmap_submission(*, roadmap_item_id, roadmap_item_scope, **metadata):
    value = create_new_work_submission(**metadata)
    value.update(
        schema_version=SCHEMA_VERSION,
        roadmap_item_id=roadmap_item_id,
        roadmap_item_scope=deepcopy(roadmap_item_scope),
    )
    value["digest"] = _pin(value)
    return validate_roadmap_submission(value)


def require_current_roadmap_submission(submission, *, roadmap_item_id, roadmap_item_scope, **current):
    """Match exact document, reviewers and Item scope after native authorization.

    Movement, health and progress remain independently authorized metadata. They
    do not change the approved scope reference. A replacement scope, including
    identical bytes stored as a new object, requires a new Product submission.
    """
    subject = validate_roadmap_submission(submission)
    _require(subject["roadmap_item_id"] == roadmap_item_id)
    _require(subject["roadmap_item_scope"] == roadmap_item_scope)
    require_current_new_work_submission(_standalone_projection(subject), **current)
    return subject
