# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Current native permission and exact subjects for local Product actions.

Must be called under the consuming command's transaction both before protected
I/O and again before effects. This result is not a transferable approval receipt.
"""

from dataclasses import dataclass

from .local_document_authority import require_local_document_authority
from .local_document_store import LocalDocumentUnavailable
from .local_prd_review import require_current_submission
from .local_prd_review_models import LocalPrdSubmission, LocalPrdDecision
from .local_prd_reopening_models import LocalPrdReopening
from .local_prd_reopening import require_replacement_source
from .prd_commands import PrdCommandError


@dataclass(frozen=True, repr=False)
class LocalReviewAuthority:
    document: object
    submission: object
    decision: object
    reopening: object
    action: str
    submission_is_current: bool
    fence: tuple


def _require(condition, code="LOCAL_REVIEW_UNAVAILABLE", status=404):
    if not condition:
        raise PrdCommandError(code, status)


def submission_inputs(document):
    context = document.context
    if context.head is None:
        return dict(
            source=document.current_source.as_record(),
            product_id=str(context.product.id),
            product_version=context.product.version,
            business_intent=context.initiative.business_intent,
            reviewers=[dict(item) for item in context.reviewers],
            risk_tier=context.initiative.risk_tier,
        )
    return dict(
        source=document.current_source.as_record(),
        scope_revision_id=str(context.revision.id),
        scope_revision=context.revision.version,
        membership_digest=context.revision.membership_digest,
        reviewers=[dict(item) for item in context.reviewers],
        risk_tier=context.initiative.risk_tier,
    )


def require_current_document_submission(submission, document):
    if document.context.head is None:
        from .local_prd_new_work import require_current_new_work_submission

        return require_current_new_work_submission(submission, **submission_inputs(document))
    return require_current_submission(submission, **submission_inputs(document))


def create_document_submission(document, **metadata):
    if document.context.head is None:
        from .local_prd_new_work import create_new_work_submission

        return create_new_work_submission(**submission_inputs(document), **metadata)
    from .local_prd_review import create_submission

    return create_submission(**submission_inputs(document), **metadata)


def require_local_review_authority(
    *,
    request,
    workspace_slug,
    initiative_id,
    action,
    expected_version=None,
    source_id=None,
    source_digest=None,
    submission_id=None,
    submission_digest=None,
):
    _require(action in {"READ", "SUBMIT", "APPROVE", "REQUEST_CHANGES"})
    document = require_local_document_authority(
        request=request,
        workspace_slug=workspace_slug,
        initiative_id=initiative_id,
        action="READ",
        expected_version=expected_version,
    )
    context = document.context
    initiative = context.initiative
    if action != "READ":
        _require(type(expected_version) is int and expected_version > 0, "LOCAL_REVIEW_VERSION_REQUIRED", 428)
    latest = (
        LocalPrdSubmission.objects.select_for_update()
        .filter(workspace_id=context.workspace.id, initiative_id=initiative.id)
        .order_by("-initiative_version")
        .first()
    )
    decision = None
    if latest is not None:
        latest.validate_metadata()
        decision = (
            LocalPrdDecision.objects.select_for_update()
            .filter(
                workspace_id=context.workspace.id,
                initiative_id=initiative.id,
                submission_id=latest.id,
            )
            .first()
        )
        if decision is not None:
            decision.validate_metadata()
    reopening = None
    effective_state = initiative.paused_from_state if initiative.state == "PAUSED" else initiative.state
    if (
        latest is not None
        and decision is not None
        and decision.state == "APPROVED"
        and effective_state in {"ALIGNING", "CANCELLED"}
    ):
        reopening = (
            LocalPrdReopening.objects.select_for_update()
            .filter(
                workspace_id=context.workspace.id,
                initiative_id=initiative.id,
                submission_id=latest.id,
                decision_id=decision.id,
                initiative_version__lt=initiative.version,
            )
            .first()
        )
        if reopening is not None:
            reopening.validate_metadata()
    submission_is_current = False
    if latest is not None and document.current_source is not None:
        try:
            require_current_document_submission(latest.as_record(), document)
            submission_is_current = reopening is None
        except LocalDocumentUnavailable:
            pass
    if action != "READ":
        _require(initiative.current_prd_checkpoint_id is None, "LOCAL_REVIEW_SUBJECT_CHANGED", 409)
        source = document.current_source
        _require(source is not None, "LOCAL_REVIEW_SOURCE_REQUIRED", 409)
        _require(
            type(source_id) is str and source_id == str(source.id) and source_digest == source.digest,
            "LOCAL_REVIEW_SOURCE_CHANGED",
            409,
        )
        if action == "SUBMIT":
            _require(context.actor_id == initiative.creator_user_id)
            _require(initiative.state == "ALIGNING", "LOCAL_REVIEW_STATE_CHANGED", 409)
            _require(submission_id is None and submission_digest is None, "LOCAL_REVIEW_SUBJECT_INVALID", 422)
            # A returned document needs a replacement. Old approvals never carry
            # over to new source IDs, even when uploaded bytes happen to match.
            _require(
                latest is None
                or (
                    decision is not None
                    and (decision.state == "CHANGES_REQUESTED" or reopening is not None)
                    and str(latest.source_id) != str(source.id)
                ),
                "LOCAL_REVIEW_REPLACEMENT_REQUIRED",
                409,
            )
            if reopening is not None:
                try:
                    require_replacement_source(
                        reopening.as_record(), latest.as_record(), decision.as_record(), source.as_record()
                    )
                except LocalDocumentUnavailable:
                    raise PrdCommandError("LOCAL_REVIEW_REPLACEMENT_REQUIRED", 409) from None
        else:
            _require(initiative.state == "PRD_REVIEW", "LOCAL_REVIEW_STATE_CHANGED", 409)
            reviewer = next(item for item in context.reviewers if item["gate_type"] == "PRD_APPROVAL")
            _require(str(context.actor_id) == reviewer["approver_user_id"])
            _require(
                latest is not None
                and str(initiative.current_local_prd_submission_id) == str(latest.id)
                and initiative.controlling_local_prd_decision_id is None
                and decision is None
                and submission_id == str(latest.id)
                and submission_digest == latest.digest,
                "LOCAL_REVIEW_SUBJECT_CHANGED",
                409,
            )
            # An external checkpoint remains owned by its original review path.
            _require(initiative.current_prd_checkpoint_id is None, "LOCAL_REVIEW_SUBJECT_CHANGED", 409)
            _require(initiative.version == latest.initiative_version + 1, "LOCAL_REVIEW_VERSION_CHANGED", 409)
            try:
                require_current_document_submission(latest.as_record(), document)
            except LocalDocumentUnavailable:
                raise PrdCommandError("LOCAL_REVIEW_SUBJECT_CHANGED", 409) from None
    fence = (
        document.fence,
        (str(latest.id), latest.digest, latest.initiative_version) if latest else None,
        (str(decision.id), decision.digest, decision.state) if decision else None,
        (str(reopening.id), reopening.digest) if reopening else None,
        action,
    )
    return LocalReviewAuthority(document, latest, decision, reopening, action, submission_is_current, fence)
