# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Native local plan preparation, tied to the current Product approval."""

from dataclasses import dataclass
from .local_prd_review_authority import require_local_review_authority
from .prd_commands import PrdCommandError


@dataclass(frozen=True, repr=False)
class LocalPlanAuthority:
    product_review: object

    @property
    def context(self):
        return self.product_review.document.context

    action: str
    current_revision: object
    submission: object
    decision: object
    revision_is_current: bool
    fence: tuple


def require_local_plan_authority(
    *,
    request,
    workspace_slug,
    initiative_id,
    action,
    expected_version=None,
    prd_submission_id=None,
    prd_submission_digest=None,
    prd_decision_id=None,
    prd_decision_digest=None,
    plan_revision_id=None,
    plan_revision_digest=None,
    submission_id=None,
    submission_digest=None,
):
    if action not in {"READ", "UPLOAD", "READ_UPLOAD_RESULT", "SUBMIT", "APPROVE", "REQUEST_CHANGES"}:
        raise PrdCommandError("LOCAL_PLAN_UNAVAILABLE", 404)
    review = require_local_review_authority(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action="READ",
        expected_version=expected_version,
    )
    context = review.document.context
    init = context.initiative
    if (
        init.mode != "STANDALONE"
        or init.state != "PLANNING"
        or not review.submission_is_current
        or review.submission is None
        or review.decision is None
        or review.decision.state != "APPROVED"
        or init.current_prd_checkpoint_id is not None
        or init.controlling_prd_decision_id is not None
        or init.current_local_prd_submission_id != review.submission.id
        or init.controlling_local_prd_decision_id != review.decision.id
    ):
        raise PrdCommandError("LOCAL_PLAN_PRODUCT_APPROVAL_REQUIRED", 409)
    if action != "READ":
        if type(expected_version) is not int or expected_version <= 0:
            raise PrdCommandError("LOCAL_PLAN_VERSION_REQUIRED", 428)
        if action in {"UPLOAD", "READ_UPLOAD_RESULT", "SUBMIT"} and context.actor_id != init.creator_user_id:
            raise PrdCommandError("LOCAL_PLAN_UNAVAILABLE", 404)
        if (
            prd_submission_id != str(review.submission.id)
            or prd_submission_digest != review.submission.digest
            or prd_decision_id != str(review.decision.id)
            or prd_decision_digest != review.decision.digest
        ):
            raise PrdCommandError("LOCAL_PLAN_PRODUCT_APPROVAL_CHANGED", 409)
    from .local_plan_models import LocalPlanRevision, LocalPlanSubmission, LocalPlanDecision

    current = (
        LocalPlanRevision.objects.select_for_update()
        .filter(workspace_id=context.workspace.id, initiative_id=init.id)
        .order_by("-version")
        .first()
    )
    if current is not None:
        current.validate_metadata()
    submission = None
    decision = None
    revision_is_current = bool(
        current is not None
        and str(current.prd_submission_id) == str(review.submission.id)
        and str(current.prd_decision_id) == str(review.decision.id)
    )
    if current is not None:
        submission = (
            LocalPlanSubmission.objects.select_for_update()
            .filter(workspace_id=context.workspace.id, initiative_id=init.id, plan_revision_id=current.id)
            .first()
        )
        if submission is not None:
            submission.validate_metadata()
            decision = (
                LocalPlanDecision.objects.select_for_update()
                .filter(workspace_id=context.workspace.id, initiative_id=init.id, plan_submission_id=submission.id)
                .first()
            )
            if decision is not None:
                decision.validate_metadata()
    if action == "UPLOAD" and revision_is_current and submission is not None:
        if decision is None or decision.state != "CHANGES_REQUESTED":
            raise PrdCommandError("LOCAL_PLAN_REVIEW_LOCKED", 409)
    if action in {"SUBMIT", "APPROVE", "REQUEST_CHANGES"}:
        if not revision_is_current or plan_revision_id != str(current.id) or plan_revision_digest != current.digest:
            raise PrdCommandError("LOCAL_PLAN_REVISION_CHANGED", 409)
        if action == "SUBMIT":
            if submission_id is not None or submission_digest is not None:
                raise PrdCommandError("LOCAL_PLAN_SUBJECT_INVALID", 422)
            if submission is not None:
                raise PrdCommandError("LOCAL_PLAN_REPLACEMENT_REQUIRED", 409)
        else:
            reviewer = next(item for item in context.reviewers if item["gate_type"] == "PLAN_APPROVAL")
            if str(context.actor_id) != reviewer["approver_user_id"]:
                raise PrdCommandError("LOCAL_PLAN_UNAVAILABLE", 404)
            if (
                submission is None
                or decision is not None
                or submission_id != str(submission.id)
                or submission_digest != submission.digest
                or submission.payload["technical_gate_assignment_id"] != reviewer["gate_assignment_id"]
                or submission.payload["technical_approver_id"] != reviewer["approver_user_id"]
            ):
                raise PrdCommandError("LOCAL_PLAN_SUBJECT_CHANGED", 409)
    return LocalPlanAuthority(
        review,
        action,
        current,
        submission,
        decision,
        revision_is_current,
        (
            review.fence,
            action,
            str(init.current_local_prd_submission_id),
            str(init.controlling_local_prd_decision_id),
            (str(current.id), current.version, current.digest) if current else None,
            (str(submission.id), submission.digest) if submission else None,
            (str(decision.id), decision.digest, decision.state) if decision else None,
        ),
    )
