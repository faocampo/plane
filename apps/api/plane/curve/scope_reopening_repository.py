# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Exact successor-edition receipt and immutable reopening integrity dispatch."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from django.db import transaction

from .policy_services import assert_active_mutation_receipt
from .prd_commands import PrdCommandError
from .scope_reopening_contracts import ACTION, REVISION_EDITION, validate_reopening_contract

_WRITE = ContextVar("curve_scope_reopening_write", default=None)


def reopening_write_active():
    return _WRITE.get() is not None


def _values(record):
    return {field.attname: deepcopy(getattr(record, field.attname)) for field in record._meta.local_fields}


@contextmanager
def reopening_write(receipt, context, *, reopening, revision, items):
    from .scope_proposal_serialization import serialize_scope_item
    from .models import PolicyDecision

    reference = dict(
        resource_type="INITIATIVE", resource_id=str(context.initiative.id), resource_version=context.initiative.version
    )
    assert_active_mutation_receipt(receipt, action=ACTION, workspace_id=context.workspace.id, resource_ref=reference)
    policy = PolicyDecision.objects.get(id=receipt.decision_id, workspace_id=context.workspace.id)
    actor = dict(actor_type="HUMAN", actor_id=str(context.actor_id))
    if policy.subject != actor or policy.effective_principal != actor:
        raise PermissionError("Reopening policy actor mismatch")
    expected = [
        dict(item, source_observed_at=item["source_observed_at"].isoformat()) for item in context.observed_members
    ]
    actual = [serialize_scope_item(item) for item in items]
    if not (
        receipt.resource_ref["resource_id"] == str(context.initiative.id)
        and revision.policy_edition == REVISION_EDITION
        and revision.created_by == reopening.created_by == context.actor_id
        and revision.proposal_id == reopening.proposal_id == context.head.id
        and revision.id == reopening.scope_revision_id
        and revision.predecessor_id == reopening.predecessor_revision_id == context.revision.id
        and revision.initiative_id == reopening.initiative_id == context.initiative.id
        and revision.product_id == reopening.product_id == context.product.id
        and revision.workspace_id == reopening.workspace_id == context.workspace.id
        and revision.version == context.head.version + 1
        and revision.initiative_version == context.initiative.version + 1
        and reopening.previous_initiative_version == context.initiative.version
        and reopening.previous_checkpoint_id == context.initiative.current_prd_checkpoint_id
        and reopening.previous_decision_id == context.initiative.controlling_prd_decision_id
        and reopening.previous_pending_reopening_id == context.initiative.pending_scope_reopening_id
        and reopening.previous_state == context.initiative.state
        and reopening.policy_decision_id == receipt.decision_id
        and actual == expected
    ):
        raise PermissionError("Reopening receipt subject mismatch")
    records = {(type(record), record.id): _values(record) for record in (reopening, revision, *items)}
    token = _WRITE.set((receipt, context, records, revision.id, revision.version, reference))
    try:
        yield
    finally:
        _WRITE.reset(token)


def assert_reopening_write(record):
    from .scope_proposal_models import ScopeProposal

    active = _WRITE.get()
    if active is None or not transaction.get_connection().in_atomic_block:
        raise PermissionError("Exact active reopening receipt required")
    receipt, context, records, revision_id, revision_version, reference = active
    assert_active_mutation_receipt(receipt, action=ACTION, workspace_id=context.workspace.id, resource_ref=reference)
    if type(record) is ScopeProposal:
        valid = (
            record.id == context.head.id
            and record.workspace_id == context.workspace.id
            and record.initiative_id == context.initiative.id
            and record.product_id == context.product.id
            and record.current_revision_id == revision_id
            and record.version == revision_version
        )
    else:
        valid = records.get((type(record), record.id)) == _values(record)
    if not valid:
        raise PermissionError("Reopening receipt does not authorize this exact record")


def require_reopened_revision(revision, items):
    """Integrity only. This ledger is never retained access or current authority."""
    from .scope_proposal_serialization import serialize_scope_revision
    from .scope_reopening_models import ScopeReopening

    try:
        if revision.policy_edition != REVISION_EDITION:
            raise ValueError
        ledger = ScopeReopening.objects.select_for_update().filter(scope_revision_id=revision.id).first()
        if ledger is None:
            raise ValueError
        data = ledger.as_record()
        if not (
            ledger.workspace_id == revision.workspace_id
            and ledger.product_id == revision.product_id
            and ledger.initiative_id == revision.initiative_id
            and ledger.proposal_id == revision.proposal_id
            and ledger.predecessor_revision_id == revision.predecessor_id
            and ledger.previous_initiative_version + 1 == revision.initiative_version
            and ledger.created_by == revision.created_by
            and ledger.command_receipt_id == revision.command_receipt_id
            and data["revision"] == serialize_scope_revision(revision, items)
        ):
            raise ValueError
        return ledger
    except Exception:
        raise PrdCommandError("SCOPED_PRD_SCOPE_UNAVAILABLE", 503) from None


def validate_scope_revision_edition(revision, items):
    from .scope_proposal_models import POLICY_EDITION
    from .scope_proposal_serialization import serialize_scope_revision
    from .scope_proposal_contracts import validate_scope_contract

    data = serialize_scope_revision(revision, items)
    if revision.policy_edition == POLICY_EDITION:
        validate_scope_contract("scope-proposal-revision-v1", data)
    elif revision.policy_edition == REVISION_EDITION:
        validate_reopening_contract("scope-proposal-revision-v2", data)
        require_reopened_revision(revision, items)
    else:
        raise PrdCommandError("SCOPED_PRD_SCOPE_UNAVAILABLE", 503)
    return data
