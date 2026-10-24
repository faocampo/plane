# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Exact current C1 integrity reader for the independently versioned C2a path.

This check grants no source access or approval of context references. Only the
current complete proposal matters; superseded delivery members are history. C1
feature enablement cannot disable this fence or turn damaged metadata into an
unscoped Initiative. All callers hold the Initiative lock through their commit.
"""

from datetime import datetime
import re
import uuid

from django.db import transaction

from .models import Initiative
from .prd_commands import PrdCommandError


_ACTIONS = frozenset({"CURVE.PRD.SUBMIT", "CURVE.PRD.APPROVE"})
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _require(value):
    if not value:
        raise PrdCommandError("SCOPED_PRD_SCOPE_UNAVAILABLE", 503)


def _instant(value):
    return isinstance(value, datetime) and value.utcoffset() is not None


def load_locked_scope(*, workspace_id, initiative_id):
    """Resolve intact current scope without granting approval or source access.

    Acquire the same Initiative row fence used by scope replacement, including
    before returning an accepted-command or successful completion replay. Failure
    details and source identities never escape this fixed error boundary.
    """
    try:
        _require(transaction.get_connection().in_atomic_block)
        initiative = Initiative.objects.find_by_id(workspace_id=workspace_id, record_id=initiative_id, for_update=True)
        _require(initiative is not None)
        # Lazy imports avoid a models/repository cycle during app initialization.
        from .scope_proposal_models import POLICY_EDITION, ScopeProposal, ScopeProposalItem, ScopeProposalRevision
        from .scope_proposal_serialization import scope_membership_digest, serialize_scope_item
        from .scope_reopening_contracts import REVISION_EDITION

        # Do not workspace-filter damaged metadata into apparent absence.
        heads = list(ScopeProposal.objects.select_for_update().filter(initiative_id=initiative.id)[:2])
        if not heads:
            _require(not ScopeProposalRevision.objects.filter(initiative_id=initiative.id).exists())
            return initiative, None, None, []
        _require(len(heads) == 1)
        head = heads[0]
        _require(
            head.workspace_id == initiative.workspace_id
            and head.product_id == initiative.product_id
            and type(head.version) is int
            and head.version >= 1
            and isinstance(head.current_revision_id, uuid.UUID)
        )
        revision = ScopeProposalRevision.objects.select_for_update().filter(id=head.current_revision_id).first()
        _require(revision is not None)
        _require(
            revision.workspace_id == head.workspace_id
            and revision.initiative_id == initiative.id
            and revision.product_id == head.product_id
            and revision.proposal_id == head.id
            and revision.version == head.version
            and type(revision.initiative_version) is int
            and head.version + 1 <= revision.initiative_version <= initiative.version
            and revision.policy_edition in {POLICY_EDITION, REVISION_EDITION}
            and isinstance(revision.created_by, uuid.UUID)
            and isinstance(revision.command_receipt_id, uuid.UUID)
            and _instant(revision.recorded_at)
            and type(revision.item_count) is int
            and 0 <= revision.item_count <= 100
            and type(revision.delivery_count) is int
            and 0 <= revision.delivery_count <= revision.item_count
            and isinstance(revision.membership_digest, str)
            and _DIGEST.fullmatch(revision.membership_digest) is not None
        )
        history = ScopeProposalRevision.objects.filter(proposal_id=head.id)
        _require(history.count() == head.version and not history.filter(version__gt=head.version).exists())
        if head.version == 1:
            _require(revision.predecessor_id is None)
        else:
            predecessor = history.filter(id=revision.predecessor_id).first()
            _require(
                predecessor is not None
                and predecessor.workspace_id == head.workspace_id
                and predecessor.initiative_id == initiative.id
                and predecessor.product_id == head.product_id
                and predecessor.version == head.version - 1
                and predecessor.initiative_version < revision.initiative_version
                and predecessor.recorded_at <= revision.recorded_at
            )
        members = list(
            ScopeProposalItem.objects.select_for_update().filter(revision_id=revision.id).order_by("id")[:101]
        )
        _require(len(members) == revision.item_count)
        seen = set()
        delivery_count = 0
        for member in members:
            _require(
                member.workspace_id == head.workspace_id
                and member.purpose in {"CONTEXT_EVIDENCE", "PROPOSED_DELIVERY"}
                and all(
                    isinstance(getattr(member, key), uuid.UUID)
                    for key in ("association_id", "provider_installation_id", "source_project_id", "source_issue_id")
                )
                and type(member.association_version) is int
                and member.association_version >= 1
                and _instant(member.source_observed_at)
                and member.source_observed_at <= revision.recorded_at
                and isinstance(member.source_version, str)
                and 0 < len(member.source_version) <= 64
                and isinstance(member.source_fingerprint, str)
                and _DIGEST.fullmatch(member.source_fingerprint) is not None
                and member.source_issue_id not in seen
            )
            seen.add(member.source_issue_id)
            delivery_count += member.purpose == "PROPOSED_DELIVERY"
        _require(delivery_count == revision.delivery_count)
        _require(
            scope_membership_digest([serialize_scope_item(member) for member in members]) == revision.membership_digest
        )
        if revision.policy_edition == REVISION_EDITION:
            from .scope_reopening_repository import require_reopened_revision

            require_reopened_revision(revision, members)
        return initiative, head, revision, members
    except Exception:
        raise PrdCommandError("SCOPED_PRD_SCOPE_UNAVAILABLE", 503) from None
