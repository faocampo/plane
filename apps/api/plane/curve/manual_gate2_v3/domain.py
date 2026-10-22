# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Exact plan-v3 subjects for the shared exclusive-reservation transition kernel.

This adapter verifies two-stage retained plan inputs. Native authorization,
transactional storage and HTTP dispatch require their own qualified successor.
"""

from plane.curve.manual_plan_v3.contracts import validate
from plane.curve.manual_plan_v3.validation import (
    canonical_json,
    digest,
    metadata_digest,
    validate_definition,
)
from plane.curve.manual_gate2_v2.domain import (
    Claim,
    CurrentAuthority,
    Decision,
    Gate2Denied,
    History,
    Ledger,
    Reconciliation,
    Subject,
    TaskKey,
    hold,
    reconcile,
    transition,
    require,
    _id,
)

__all__ = [
    "Claim",
    "CurrentAuthority",
    "Decision",
    "Gate2Denied",
    "History",
    "Ledger",
    "Reconciliation",
    "Subject",
    "TaskKey",
    "hold",
    "reconcile",
    "transition",
    "prepare_subject",
    "subject_from_verified_receipt",
]


def prepare_subject(*, revision, identity, receipt, definition, facts, controlling_prd_decision_id):
    """Pre-lock preparation from verified draft plus freshly derived facts.

    Production must supply facts from derive_semantic_facts in the bounded Linux
    worker, and independently recheck retained DB rows/current native authority.
    This computation alone is not a qualified review-subject persistence path.
    """
    require(receipt == validate_definition(definition, identity, facts))
    return subject_from_verified_receipt(
        revision=revision,
        identity=identity,
        receipt=receipt,
        facts=facts,
        controlling_prd_decision_id=controlling_prd_decision_id,
    )


def subject_from_verified_receipt(*, revision, identity, receipt, facts, controlling_prd_decision_id):
    """Internal adapter boundary after the bounded worker verified these exact captured bytes.

    Never accept a caller-supplied receipt or facts here. The adapter independently
    matches the receipt to the retained revision and rechecks native/material fences.
    """
    validate("manual-plan-draft-revision-v3", revision)
    validate("manual-plan-input-identity-v3", identity)
    validate("manual-plan-validation-receipt-v3", receipt)
    require(revision["digest"] == metadata_digest(revision))
    require(identity["digest"] == metadata_digest(identity))
    require(receipt["digest"] == metadata_digest(receipt))
    require(receipt["input_identity_digest"] == identity["digest"])
    require(receipt["definition_digest"] == identity["definition_ref"]["digest"])
    require(identity["workspace_id"] == revision["workspace_id"])
    require(identity["initiative_id"] == revision["initiative_id"])
    for key in ("definition_ref", "approved_subject_ref", "manual_profile_ref"):
        require(revision[key] == identity[key])
    assignments = identity["gate_assignments"]
    require(tuple(item["gate_type"] for item in assignments) == ("PLAN_APPROVAL", "PRD_APPROVAL"))
    require(len({item["gate_assignment_id"] for item in assignments}) == 2)
    require(facts["risk_tier"] in {"LOW", "STANDARD", "HIGH"})
    # Current two-stage policy requires distinct reviewers above LOW risk.
    if facts["risk_tier"] in {"STANDARD", "HIGH"}:
        require(len({item["approver_user_id"] for item in assignments}) == 2)
    tasks = tuple(
        TaskKey(
            revision["workspace_id"],
            item["provider_installation_id"],
            item["source_issue_id"],
        )
        for item in facts["proposed_delivery_refs"]
    )
    require(tasks and tasks == tuple(sorted(set(tasks))))
    metadata = dict(
        edition="MANUAL_GATE2_TWO_STAGE_TRANSITION_V3",
        workspace_id=revision["workspace_id"],
        product_id=revision["product_id"],
        initiative_id=revision["initiative_id"],
        draft_revision_id=revision["id"],
        draft_revision=revision["revision"],
        draft_digest=revision["digest"],
        input_identity=identity,
        validation_receipt_digest=receipt["digest"],
        validator_edition=receipt["validator_edition"],
        controlling_prd_decision_id=_id(controlling_prd_decision_id),
        risk_tier=facts["risk_tier"],
        semantic_facts_digest=digest(canonical_json(facts)),
        tasks=[
            dict(
                workspace_id=t.workspace_id,
                installation_id=t.installation_id,
                issue_id=t.issue_id,
            )
            for t in tasks
        ],
    )
    return Subject(canonical_json(metadata))
