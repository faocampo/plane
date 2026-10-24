# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Bounded validation before locks, followed by a single exact command transaction."""

from django.db import transaction

from plane.curve.manual_plan_v2.models import ManualPlanRevisionV2
from plane.curve.manual_plan_v2.repository import load_head, load_revision
from plane.curve.manual_plan_v2.synthetic import SyntheticManualPlanResolverV2
from plane.curve.manual_plan_v2.validator_worker import validate_in_worker
from plane.curve.manual_plan_v2.validation import canonical_json, digest
from . import domain as g, policy, repository as repo
from .contracts import Gate2Error, RESOURCE, project_record, record_ref, require


def _subject(revision, authority, validation):
    require(validation == revision.validation_receipt)
    return g.subject_from_verified_receipt(
        revision=revision.as_record(),
        identity=authority.captured.identity,
        receipt=validation,
        facts=authority.captured.facts,
        controlling_prd_decision_id=str(authority.context.initiative.controlling_prd_decision_id),
    )


def _original_subject(initiative, command):
    ref = command.payload["subject_ref"]
    original = repo.load_record(initiative, ref["entity_id"])
    require(original.action == "PREPARE" and original.subject_id == original.id)
    require(
        original.subject_digest == ref["digest"]
        and str(original.draft_revision_id) == command.payload["draft_revision_id"]
    )
    subject = g.Subject(canonical_json(original.payload["subject_metadata"]))
    require(subject.digest == original.subject_digest)
    require(subject.data["controlling_prd_decision_id"] == str(initiative.controlling_prd_decision_id))
    return original, subject


def _kernel_authority(authority, subject, state, fence):
    context = authority.context
    return g.CurrentAuthority(
        actor_id=str(context.actor_id),
        workspace_id=str(context.workspace.id),
        initiative_id=str(context.initiative.id),
        current_technical_approver_id=next(
            x["approver_user_id"] for x in context.reviewers if x["gate_type"] == "PLAN_APPROVAL"
        ),
        current_subject_digest=subject.digest,
        material_readers=authority.principals,
        accessible_tasks=subject.tasks,
        native_fence_digest=fence,
        lifecycle=context.initiative.state if context.initiative.state in {"PAUSED", "CANCELLED"} else state,
    )


def _observations(command, authority, claim_rows, subject):
    selected = {v["claim_id"]: v["generation"] for v in command.payload["claims"]}
    rows = {str(v.id): (task, v) for task, v in claim_rows.items()}
    require(set(selected) <= set(rows), "CLAIM_CONFLICT", 409)
    observations, pairs = [], []
    native = {v["source_issue_id"]: v for v in authority.task_observations}
    for identifier, generation in selected.items():
        task, row = rows[identifier]
        require(
            row.generation == generation
            and row.state == "ACTIVE"
            and str(row.initiative_id) == subject.data["initiative_id"]
            and str(row.subject_id) == command.payload["subject_ref"]["entity_id"],
            "CLAIM_CONFLICT",
            409,
        )
        group = authority.task_groups[task.issue_id]
        require(
            group in {"backlog", "unstarted", "completed", "cancelled"},
            "UNRESOLVED_WORK",
            409,
        )
        observations.append(
            dict(
                claim_id=identifier,
                installation_id=task.installation_id,
                issue_id=task.issue_id,
                generation=generation,
                source_fingerprint=native[task.issue_id]["source_fingerprint"],
                state_group=group,
            )
        )
        pairs.append((task, generation))
    return observations, tuple(sorted(pairs))


def _replay(initiative, command, idem, receipt):
    from plane.curve.models import DomainEvent
    from plane.curve.services import _append_audit_event, operation_response_digest

    ref = idem.response_resource_ref
    require(
        type(ref) is dict
        and ref.get("resource_type") == RESOURCE
        and idem.state == "COMPLETED"
        and idem.response_status == 201
    )
    original = repo.load_record(initiative, ref["resource_id"])
    require(
        ref == record_ref(original)
        and original.request_digest == command.request_digest
        and original.request_payload == command.payload
    )
    require(idem.response_digest == operation_response_digest(response_status=201, resource_ref=ref))
    event = DomainEvent.objects.filter(id=original.command_receipt_id, workspace_id=initiative.workspace_id).first()
    require(
        event is not None
        and event.idempotency_key_digest == idem.key_digest
        and event.payload["record_digest"] == original.digest
    )
    actor = dict(actor_type="HUMAN", actor_id=str(receipt.actor_id))
    _append_audit_event(
        workspace_id=initiative.workspace_id,
        action=receipt.action,
        target_ref=ref,
        outcome="NO_EFFECT",
        actor=actor,
        effective_principal=actor,
        correlation_id=receipt.correlation_id,
        key_digest=idem.key_digest,
        policy_decision_ref=dict(
            resource_type="POLICY_DECISION",
            resource_id=str(receipt.decision_id),
            resource_version=1,
        ),
    )
    return repo.Result(project_record(original), initiative.version, True)


def execute(*, request, slug, command):
    from plane.db.models import Workspace
    from plane.curve.models import Initiative
    from plane.curve.product_services import _load_or_create_idempotency
    from plane.curve.services import CommandAlreadyInProgress, IdempotencyConflict

    try:
        policy.require_enabled(request, slug)
        revision = ManualPlanRevisionV2.objects.filter(
            id=command.payload["draft_revision_id"], initiative_id=command.initiative_id
        ).first()
        require(revision is not None)
        with SyntheticManualPlanResolverV2.from_settings() as resolver:
            captured = policy.preflight(request=request, slug=slug, revision=revision, resolver=resolver)
            validation = validate_in_worker(captured)
            with transaction.atomic():
                policy.require_edition()
                workspace = Workspace.objects.select_for_update().filter(slug=slug, id=revision.workspace_id).first()
                require(workspace is not None)
                initiative = Initiative.objects.find_by_id(
                    workspace_id=workspace.id,
                    record_id=command.initiative_id,
                    for_update=True,
                )
                require(initiative is not None)
                head, current = load_head(initiative)
                require(head is not None)
                revision = load_revision(initiative, head, revision.id)
                control = repo.load_control(initiative)
                identity = repo.command_identity(command, request.user.id)
                idem, _, replay = _load_or_create_idempotency(workspace_id=workspace.id, identity=identity)
                authority_action = command.action
                if replay and control is not None and control.approved_record_id is not None:
                    authority_action = "REPLAY_PREPARE" if command.action == "PREPARE" else "REPLAY_DECISION"
                authority = policy.load_authority(
                    request=request,
                    slug=slug,
                    revision=revision,
                    resolver=resolver,
                    action=authority_action,
                )
                require(
                    authority.captured.identity == captured.identity and authority.file_fence == captured.file_fence
                )
                rationale_fence, grants = policy.read_rationale(authority, resolver, command)
                fence = digest(canonical_json(dict(native=authority.fence, rationale_grants=grants)))
                original = None
                if command.action == "PREPARE":
                    subject = _subject(revision, authority, validation)
                else:
                    original, subject = _original_subject(initiative, command)
                    require(validation == revision.validation_receipt)
                with policy.record_authorization(
                    request=request, authority=authority, command=command, fence=fence
                ) as receipt:
                    if replay:
                        result = _replay(initiative, command, idem, receipt)
                    else:
                        require(
                            initiative.version == command.expected_version,
                            "PRECONDITION_FAILED",
                            412,
                        )
                        claims, selected, observations, reconciliation_id = (
                            {},
                            (),
                            [],
                            None,
                        )
                        if command.action == "PREPARE":
                            require(
                                current.id == revision.id
                                and (
                                    control is None
                                    or (
                                        control.approved_record_id is None
                                        and control.state in {"PLAN_REVIEW", "CHANGES_REQUESTED"}
                                    )
                                ),
                                "STATE_CONFLICT",
                                409,
                            )
                            if control is not None:
                                previous = repo.load_record(initiative, control.subject_id)
                                require(
                                    previous.draft_revision_id != revision.id,
                                    "STATE_CONFLICT",
                                    409,
                                )
                            state = "PLAN_REVIEW"
                        else:
                            require(
                                control is not None and control.subject_id == original.id,
                                "STATE_CONFLICT",
                                409,
                            )
                            claims = repo.lock_claims(initiative, subject)
                            ledger = repo.ledger_from_claims(claims)
                            state = control.state
                            kernel = _kernel_authority(authority, subject, state, fence)
                            if command.action in {"APPROVE", "REQUEST_CHANGES"}:
                                require(
                                    state == "PLAN_REVIEW"
                                    and control.approved_record_id is None
                                    and current.id == revision.id,
                                    "STATE_CONFLICT",
                                    409,
                                )
                                require(
                                    _subject(revision, authority, validation).metadata == subject.metadata,
                                    "STATE_CONFLICT",
                                    409,
                                )
                                _, decision, _ = g.transition(
                                    ledger=ledger,
                                    subject=subject,
                                    authority=kernel,
                                    action=command.action,
                                    idempotency_key=command.key,
                                    rationale_digest=command.payload["rationale_ref"]["digest"],
                                )
                                selected = decision.claims
                                state = "MANUAL_APPROVED" if command.action == "APPROVE" else "CHANGES_REQUESTED"
                            else:
                                require(
                                    control.approved_record_id is not None and state == "MANUAL_APPROVED",
                                    "STATE_CONFLICT",
                                    409,
                                )
                                observations, pairs = _observations(command, authority, claims, subject)
                                reconciliation = g.reconcile(
                                    ledger=ledger,
                                    subject=subject,
                                    authority=kernel,
                                    exact_claims=pairs,
                                    unresolved_work=(),
                                    rationale_digest=command.payload["rationale_ref"]["digest"],
                                )
                                if command.action == "RELEASE":
                                    ref = command.payload["reconciliation_ref"]
                                    reconciled = repo.load_record(initiative, ref["entity_id"])
                                    require(
                                        reconciled.action == "RECONCILE"
                                        and reconciled.digest == ref["digest"]
                                        and reconciled.subject_id == original.id
                                        and reconciled.created_by == authority.context.actor_id
                                        and reconciled.payload["native_fence_digest"] == fence
                                        and reconciled.payload["rationale_ref"] == command.payload["rationale_ref"]
                                        and reconciled.request_payload["claims"] == command.payload["claims"]
                                        and reconciled.payload["observations"] == observations,
                                        "RECONCILIATION_STALE",
                                        409,
                                    )
                                    _, decision, _ = g.transition(
                                        ledger=ledger,
                                        subject=subject,
                                        authority=kernel,
                                        action="RELEASE",
                                        idempotency_key=command.key,
                                        rationale_digest=command.payload["rationale_ref"]["digest"],
                                        reconciliation=reconciliation,
                                    )
                                    selected, reconciliation_id = (
                                        decision.claims,
                                        reconciled.id,
                                    )
                                    remaining = [
                                        r
                                        for r in claims.values()
                                        if r.state == "ACTIVE"
                                        and r.subject_id == original.id
                                        and str(r.id) not in {c["claim_id"] for c in command.payload["claims"]}
                                    ]
                                    state = "MANUAL_APPROVED" if remaining else "RELEASED"
                        result, control = repo.append_graph(
                            receipt=receipt,
                            authority=authority,
                            command=command,
                            control=control,
                            subject_row=original,
                            subject=subject,
                            state=state,
                            claim_rows=claims,
                            selected_claims=selected,
                            observations=observations,
                            reconciliation_id=reconciliation_id,
                            idem=idem,
                            fence=fence,
                        )
                    final = policy.load_authority(
                        request=request,
                        slug=slug,
                        revision=revision,
                        resolver=resolver,
                        action=authority_action,
                    )
                    final_rationale, final_grants = policy.read_rationale(final, resolver, command)
                    require(
                        final.fence == authority.fence
                        and final.file_fence == authority.file_fence
                        and final_rationale == rationale_fence
                        and final_grants == grants
                        and final.context.initiative.version == result.initiative_version
                    )
                    resolver.recheck((*final.file_fence, *final_rationale))
                return result
    except (IdempotencyConflict, CommandAlreadyInProgress):
        raise Gate2Error("COMMAND_CONFLICT", 409) from None
    except g.Gate2Denied:
        raise Gate2Error("CLAIM_CONFLICT", 409) from None
    except Gate2Error:
        raise
    except Exception:
        raise Gate2Error() from None
