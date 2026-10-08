# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Manual save orchestration: validate before locks, authorize and commit atomically."""

import uuid

from django.db import transaction

from .contracts import ACTION, ManualPlanError, require, resource_ref
from .policy import (
    authority_fence,
    capture_authorized,
    load_native,
    record_save_authorization,
    require_edition,
    require_enabled,
)
from .repository import (
    DraftResult,
    command_identity,
    load_head,
    publish_new_revision,
    replay_revision,
    request_digest_from_revision,
)
from .synthetic import SyntheticManualPlanResolverV2
from .validator_worker import validate_in_worker


def _preflight(*, request, workspace_slug, command, resolver):
    """Uncached read-only membership checks; no row locks or domain writes."""
    from plane.db.models import User, Workspace, WorkspaceMember

    require(not transaction.get_connection().in_atomic_block, "VALIDATION_UNAVAILABLE")
    require_enabled(request, workspace_slug)
    workspace = Workspace.objects.filter(slug=workspace_slug).first()
    require(workspace is not None)
    actor_id = uuid.UUID(str(request.user.id))
    require(
        User.objects.filter(id=actor_id, is_active=True, is_bot=False).exists()
        and WorkspaceMember.objects.filter(
            workspace_id=workspace.id, member_id=actor_id, is_active=True, role__in=[5, 15, 20]
        ).exists()
    )
    initial = resolver.capture(
        workspace_id=workspace.id,
        initiative_id=command.initiative_id,
        definition_ref=command.payload["definition_ref"],
        principals=[actor_id],
        action="SAVE",
    )
    principals = sorted(
        {
            str(actor_id),
            *initial.identity["human_owner_ids"],
            *(item["approver_user_id"] for item in initial.identity["gate_assignments"]),
        }
    )
    require(
        User.objects.filter(id__in=principals, is_active=True, is_bot=False).count() == len(principals)
        and WorkspaceMember.objects.filter(
            workspace_id=workspace.id, member_id__in=principals, is_active=True, role__in=[5, 15, 20]
        ).count()
        == len(principals)
    )
    captured = resolver.capture(
        workspace_id=workspace.id,
        initiative_id=command.initiative_id,
        definition_ref=command.payload["definition_ref"],
        principals=principals,
        action="SAVE",
    )
    require(initial.identity == captured.identity and initial.file_fence == captured.file_fence)
    return captured


def save_manual_plan(*, request, workspace_slug, command):
    from plane.curve.models import AuditEvent
    from plane.curve.product_services import _load_or_create_idempotency
    from plane.curve.services import _append_audit_event, CommandAlreadyInProgress, IdempotencyConflict

    try:
        require_enabled(request, workspace_slug)
        with SyntheticManualPlanResolverV2.from_settings() as resolver:
            captured = _preflight(request=request, workspace_slug=workspace_slug, command=command, resolver=resolver)
            validation = validate_in_worker(captured)
            # Neither native row locks nor a write transaction span worker time.
            with transaction.atomic():
                require_edition()
                context, subject = load_native(
                    request=request, workspace_slug=workspace_slug, initiative_id=command.initiative_id
                )
                current = capture_authorized(
                    context=context,
                    subject=subject,
                    resolver=resolver,
                    definition_ref=command.payload["definition_ref"],
                    action="SAVE",
                )
                require(current.identity == captured.identity and current.file_fence == captured.file_fence)
                fence = authority_fence(context, subject, current)
                old_version = context.initiative.version
                head, _ = load_head(context.initiative)
                head_before = None if head is None else (head.id, head.version, head.current_revision_id)
                identity = command_identity(command, context.actor_id)
                record, _, replay = _load_or_create_idempotency(workspace_id=context.workspace.id, identity=identity)
                with record_save_authorization(
                    request=request, context=context, command=command, captured=current, validation_receipt=validation
                ) as receipt:
                    if replay:
                        original = replay_revision(initiative=context.initiative, head=head, record=record)
                        require(request_digest_from_revision(original) == command.request_digest)
                        require(original.original_input_identity == current.identity)
                        actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
                        _append_audit_event(
                            workspace_id=context.workspace.id,
                            action=ACTION,
                            target_ref=resource_ref(original),
                            outcome="NO_EFFECT",
                            actor=actor,
                            effective_principal=actor,
                            correlation_id=receipt.correlation_id,
                            key_digest=record.key_digest,
                            policy_decision_ref=dict(
                                resource_type="POLICY_DECISION",
                                resource_id=str(receipt.decision_id),
                                resource_version=1,
                            ),
                        )
                        result = DraftResult(original.as_record(), old_version, True)
                    else:
                        result = publish_new_revision(
                            receipt=receipt,
                            initiative=context.initiative,
                            command=command,
                            identity=current.identity,
                            validation_receipt=validation,
                            idempotency_record=record,
                        )
                    fresh, fresh_subject = load_native(
                        request=request, workspace_slug=workspace_slug, initiative_id=command.initiative_id
                    )
                    final = capture_authorized(
                        context=fresh,
                        subject=fresh_subject,
                        resolver=resolver,
                        definition_ref=command.payload["definition_ref"],
                        action="SAVE",
                    )
                    require(
                        authority_fence(fresh, fresh_subject, final) == fence
                        and fresh.initiative.version == old_version + (0 if replay else 1)
                    )
                    current_head, _ = load_head(fresh.initiative)
                    expected_head = (
                        head_before
                        if replay
                        else (uuid.UUID(result.data["draft_id"]), result.data["revision"], uuid.UUID(result.data["id"]))
                    )
                    require(
                        current_head is not None
                        and (current_head.id, current_head.version, current_head.current_revision_id) == expected_head
                    )
                    resolver.recheck(final.file_fence)
                    require(
                        AuditEvent.objects.filter(
                            workspace_id=context.workspace.id, policy_decision_ref__resource_id=str(receipt.decision_id)
                        ).count()
                        == 1
                    )
                return result
    except (IdempotencyConflict, CommandAlreadyInProgress):
        raise ManualPlanError("COMMAND_CONFLICT") from None
    except ManualPlanError:
        raise
    except Exception:
        raise ManualPlanError("UNAVAILABLE") from None
