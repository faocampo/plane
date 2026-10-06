"""Current manual-draft authority, exact scoped PRD binding and private receipts."""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .contracts import ACTION, POLICY_KEY, ManualPlanError, policy_digest, require
from .synthetic import SyntheticManualPlanResolverV2
from .validation import canonical_json, digest

_ACTIVE = ContextVar("manual_plan_v2_authorization", default=None)
_TOKEN = object()


@dataclass(frozen=True)
class WriteReceipt:
    workspace_id: uuid.UUID
    product_id: uuid.UUID
    initiative_id: uuid.UUID
    actor_id: uuid.UUID
    decision_id: uuid.UUID
    correlation_id: str
    request_digest: str
    input_identity_digest: str
    validation_receipt_digest: str
    token: object


def require_edition():
    try:
        from plane.curve.scope_reopening_qualification import require_manual_plan_v2_qualification

        require_manual_plan_v2_qualification()
    except Exception:
        # No historical proof, setting or observed catalog can qualify this writer.
        raise ManualPlanError("EDITION_UNAVAILABLE") from None


def require_enabled(request, workspace_slug):
    from plane.curve.config import is_curve_enabled_for_workspace

    require(
        getattr(settings, "CURVE_MANUAL_PLAN_DRAFT_V2_ENABLED", False) is True
        and getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL"
        and is_curve_enabled_for_workspace(workspace_slug)
        and getattr(request.user, "is_authenticated", False)
    )


def assert_active_receipt(receipt):
    if (
        type(receipt) is not WriteReceipt
        or receipt.token is not _TOKEN
        or _ACTIVE.get() is not receipt
        or not transaction.get_connection().in_atomic_block
    ):
        raise PermissionError("An active manual-plan authorization receipt is required")


def load_native(*, request, workspace_slug, initiative_id):
    from plane.db.models import Workspace
    from plane.curve.models import Initiative, PrdReviewDecision
    from plane.curve.scoped_prd_models import ScopedPrdSubject, ScopedPrdDecision
    from plane.curve.scoped_prd_policy import require_scoped_current, _record_payload

    require(transaction.get_connection().in_atomic_block)
    require_enabled(request, workspace_slug)
    workspace = Workspace.objects.select_for_update().filter(slug=workspace_slug).first()
    require(workspace is not None)
    initiative = Initiative.objects.find_by_id(workspace_id=workspace.id, record_id=initiative_id, for_update=True)
    require(
        initiative is not None
        and initiative.mode == "STANDALONE"
        and initiative.state == "PLANNING"
        and initiative.pending_scope_reopening_id is None
    )
    subject = (
        ScopedPrdSubject.objects.select_for_update()
        .filter(
            workspace_id=workspace.id,
            initiative_id=initiative.id,
            checkpoint_id=initiative.current_prd_checkpoint_id,
        )
        .first()
    )
    require(subject is not None)
    context = require_scoped_current(
        workspace_id=workspace.id, initiative_id=initiative.id, actor_id=request.user.id, subject=subject
    )
    sidecar = (
        ScopedPrdDecision.objects.select_for_update()
        .filter(
            workspace_id=workspace.id,
            initiative_id=initiative.id,
            scoped_subject_id=subject.id,
            decision_id=initiative.controlling_prd_decision_id,
        )
        .first()
    )
    decision = (
        PrdReviewDecision.objects.select_for_update()
        .filter(
            workspace_id=workspace.id,
            initiative_id=initiative.id,
            id=initiative.controlling_prd_decision_id,
        )
        .first()
    )
    require(sidecar is not None and decision is not None)
    original = _record_payload(subject, "Subject")
    approved = _record_payload(sidecar, "Decision")
    product_approver = next(item for item in context.reviewers if item["gate_type"] == "PRD_APPROVAL")
    require(
        approved["state"] == decision.state == "APPROVED"
        and approved["scoped_subject_digest"] == subject.digest
        and decision.checkpoint_id == subject.checkpoint_id
        and decision.gate_assignment_id == uuid.UUID(product_approver["gate_assignment_id"])
        and decision.decided_by == dict(actor_type="HUMAN", actor_id=product_approver["approver_user_id"])
        and str(sidecar.created_by) == product_approver["approver_user_id"]
        and str(decision.artifact_version_id) == original["artifact_version_id"]
        and str(decision.evidence_snapshot_id) == original["evidence_snapshot_id"]
        and decision.content_digest == original["content_digest"]
        and decision.confirmed_risk_tier == initiative.risk_tier,
    )
    return context, subject


def _principals(context, owners=()):
    return sorted({str(context.actor_id), *owners, *(item["approver_user_id"] for item in context.reviewers)})


def bind_inputs(context, subject, captured):
    identity, facts = captured.identity, captured.facts
    original = subject.as_record()
    require(
        identity["approved_subject_ref"] == dict(entity_id=str(subject.id), digest=subject.digest)
        and identity["scope_revision_ref"]
        == dict(entity_id=str(context.revision.id), digest=context.revision.membership_digest)
        and identity["gate_assignments"] == list(context.reviewers)
        and identity["prd_artifact_version_id"] == original["artifact_version_id"]
        and identity["prd_content_digest"] == original["content_digest"]
        and identity["evidence_snapshot_id"] == original["evidence_snapshot_id"]
    )
    code_approver = next(
        item["approver_user_id"] for item in context.reviewers if item["gate_type"] == "CODE_READINESS"
    )
    delivery = sorted(
        (
            dict(provider_installation_id=str(item.provider_installation_id), source_issue_id=str(item.source_issue_id))
            for item in context.members
            if item.purpose == "PROPOSED_DELIVERY"
        ),
        key=lambda item: (item["provider_installation_id"], item["source_issue_id"]),
    )
    require(
        facts["initiative_key"] == context.initiative.keyword
        and facts["risk_tier"] == context.initiative.risk_tier
        and facts["code_approver_id"] == code_approver
        and facts["proposed_delivery_refs"] == delivery
    )
    require(identity["workflow_ref"]["entity_id"] == str(context.initiative.workflow_version_id))
    return identity


def require_retained_material(identity, reference, *, material_version_id, access_envelope_id, classification=None):
    """Bind original PRD material to already captured, currently authorized bytes."""
    matches = [item for item in identity["protected_inputs"] if item["object_ref"] == reference]
    require(len(matches) == 1)
    original = matches[0]
    require(
        original["material_version_id"] == str(material_version_id)
        and original["access_envelope_id"] == str(access_envelope_id)
        and (classification is None or original["classification"] == classification)
    )


def require_prd_materials(context, captured):
    """Locked immutable PRD membership; catalog grants alone cannot invent it.

    All referenced bytes were captured with current per-object grants for every
    principal. This is the fixed synthetic local profile, not a provider ACL.
    """
    from plane.curve.prd_models import PrdArtifactVersion, PrdEvidenceSnapshot, PrdEvidenceItemVersion

    identity = captured.identity
    version = (
        PrdArtifactVersion.objects.select_for_update()
        .filter(
            workspace_id=context.workspace.id,
            initiative_id=context.initiative.id,
            id=identity["prd_artifact_version_id"],
            evidence_snapshot_id=identity["evidence_snapshot_id"],
        )
        .first()
    )
    require(version is not None and version.body_digest == identity["prd_content_digest"])
    version.validate_metadata()
    require_retained_material(
        identity,
        version.as_record()["body"],
        material_version_id=version.id,
        access_envelope_id=version.access_envelope_id,
    )
    snapshot = (
        PrdEvidenceSnapshot.objects.select_for_update()
        .filter(
            workspace_id=context.workspace.id,
            initiative_id=context.initiative.id,
            id=identity["evidence_snapshot_id"],
            artifact_version_id=version.id,
        )
        .first()
    )
    require(snapshot is not None and len(snapshot.items) <= 512)
    snapshot.validate_metadata()
    for member in snapshot.items:
        # Conservatively retain every selected item, not only those marked material.
        item = (
            PrdEvidenceItemVersion.objects.select_for_update()
            .filter(
                workspace_id=context.workspace.id,
                evidence_id=member["evidence_item_id"],
                version=member["evidence_item_version"],
            )
            .first()
        )
        require(item is not None)
        recorded_envelope_digest = item.envelope_digest
        item.validate_metadata()
        record = item.record
        require(
            item.envelope_digest == recorded_envelope_digest == member["access_envelope_digest"]
            and record["access_envelope"]["id"] == member["access_envelope_id"]
            and record["content_digest"] == member["content_digest"]
            and record["source_version"] == member["source_version"]
            and record["content"] is not None
        )
        for reference in (record["content"], member["selected_excerpt_ref"]):
            if reference is not None:
                require_retained_material(
                    identity,
                    reference,
                    material_version_id=item.row_id,
                    access_envelope_id=member["access_envelope_id"],
                    classification=record["classification"],
                )


def capture_authorized(*, context, subject, resolver, definition_ref, action):
    from plane.curve.scoped_prd_policy import require_scoped_current

    require(type(resolver) is SyntheticManualPlanResolverV2, "EDITION_UNAVAILABLE")
    captured = resolver.capture(
        workspace_id=context.workspace.id,
        initiative_id=context.initiative.id,
        definition_ref=definition_ref,
        principals=_principals(context),
        action=action,
    )
    if action == "SAVE":
        require(
            context.initiative.creator_user_id == context.actor_id
            or str(context.actor_id) in captured.technical_contributor_ids
        )
    bind_inputs(context, subject, captured)
    # Every named owner is a current active human with source access, not merely
    # a UUID that passed the definition schema. All three reviewers were checked
    # by the incumbent scoped reader, with the conservative observation fence.
    for owner in captured.identity["human_owner_ids"]:
        require_scoped_current(
            workspace_id=context.workspace.id,
            initiative_id=context.initiative.id,
            actor_id=uuid.UUID(owner),
            subject=subject,
        )
    final = resolver.capture(
        workspace_id=context.workspace.id,
        initiative_id=context.initiative.id,
        definition_ref=definition_ref,
        principals=_principals(context, captured.identity["human_owner_ids"]),
        action=action,
    )
    require(final.identity == captured.identity and final.file_fence == captured.file_fence)
    require_prd_materials(context, final)
    return final


def authority_fence(context, subject, captured):
    # Original identity stays separate from mutable source/ACL generations.
    return (
        context.fence,
        context.initiative.creator_user_id,
        context.initiative.workflow_version_id,
        context.initiative.current_prd_checkpoint_id,
        context.initiative.controlling_prd_decision_id,
        context.initiative.pending_scope_reopening_id,
        subject.id,
        subject.digest,
        captured.catalog_generation,
        canonical_json(list(captured.grants)),
        captured.file_fence,
    )


@contextmanager
def record_save_authorization(*, request, context, command, captured, validation_receipt):
    from plane.curve.config import curve_policy_recorder
    from plane.curve.models import PolicyDecision
    from plane.curve.policy_services import _next_policy_sequence, correlation_id_for_request

    require(transaction.get_connection().in_atomic_block)
    actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
    now = timezone.now()
    decision = PolicyDecision.objects.create(
        workspace_id=context.workspace.id,
        sequence=_next_policy_sequence(
            workspace_id=context.workspace.id, resource_type="INITIATIVE", resource_id=context.initiative.id
        ),
        action=ACTION,
        resource_type="INITIATIVE",
        resource_id=context.initiative.id,
        resource_version=context.initiative.version,
        subject=actor,
        effective_principal=actor,
        effect="ALLOW",
        reason_codes=["ALLOW"],
        policy_key=POLICY_KEY,
        policy_version=2,
        policy_manifest_digest=policy_digest(),
        input_digest=digest(
            canonical_json(
                dict(
                    request_digest=command.request_digest,
                    input_identity_digest=captured.identity["digest"],
                    catalog_generation=captured.catalog_generation,
                    grants=list(captured.grants),
                )
            )
        ),
        normalized_classification="INTERNAL",
        permitted_projection=["MANUAL_PLAN_DRAFT_METADATA_V2"],
        correlation_id=correlation_id_for_request(request),
        evaluated_at=now,
        recorded_at=now,
        recorded_by=curve_policy_recorder(),
    )
    receipt = WriteReceipt(
        context.workspace.id,
        context.product.id,
        context.initiative.id,
        context.actor_id,
        decision.id,
        decision.correlation_id,
        command.request_digest,
        captured.identity["digest"],
        validation_receipt["digest"],
        _TOKEN,
    )
    token = _ACTIVE.set(receipt)
    try:
        yield receipt
    finally:
        _ACTIVE.reset(token)
