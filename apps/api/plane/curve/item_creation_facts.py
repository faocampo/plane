# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Native locked observations for joint creation; these are not policy receipts."""

from dataclasses import dataclass
from uuid import UUID

from django.db import connection, transaction

from plane.curve.config import is_curve_enabled_for_workspace
from plane.curve.models import Feature, Milestone, Product, Roadmap
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.product_format import (
    ProductFormatUnavailable,
    require_supported_product_format,
)
from plane.db.models import User, Workspace, WorkspaceMember

from plane.curve.item_creation_input import NormalizedItemCreation, normalize_item_creation


@dataclass(frozen=True, slots=True)
class HumanMembershipFact:
    user_id: UUID
    active_human: bool
    active_member: bool
    membership_id: UUID | None


@dataclass(frozen=True, slots=True)
class ItemCreationFacts:
    workspace_id: UUID
    product_id: UUID
    roadmap_id: UUID
    milestone_id: UUID
    feature_id: UUID
    roadmap_owner_id: UUID
    roadmap_version: int
    feature_enabled: bool
    product_active: bool
    formats_supported: bool
    records_active: bool
    actor: HumanMembershipFact
    actor_membership_generation: int | None
    reviewers: tuple[tuple[str, HumanMembershipFact], ...]


def resolve_item_creation_facts(*, workspace_slug, product_id, roadmap_id, actor_id, command):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("ITEM_AUTHORITY_TRANSACTION_REQUIRED")
    if not isinstance(command, NormalizedItemCreation):
        raise TypeError("NORMALIZED_ITEM_CREATION_REQUIRED")
    payload = normalize_item_creation(command.as_payload(), command.expected_version).as_payload()
    try:
        product_id, roadmap_id, actor_id = (UUID(str(value)) for value in (product_id, roadmap_id, actor_id))
    except (ValueError, TypeError, AttributeError):
        raise CurvePolicyResourceNotFound from None
    workspace = Workspace.objects.select_for_update(no_key=True).filter(slug=workspace_slug).first()
    if workspace is None:
        raise CurvePolicyResourceNotFound
    assignments = tuple(
        (entry["gate_type"], UUID(entry["approver_user_id"])) for entry in payload["initiative"]["gate_assignments"]
    )
    ids = {actor_id, *(value for _, value in assignments)}
    # One stable order across actors/reviewers prevents opposite reviewer order
    # from acquiring native identity locks in opposite directions.
    users = {row.id: row for row in User.objects.select_for_update(no_key=True).filter(id__in=ids).order_by("id")}
    members = {
        row.member_id: row
        for row in WorkspaceMember.objects.select_for_update(no_key=True)
        .filter(workspace_id=workspace.id, member_id__in=ids)
        .order_by("member_id")
    }

    def human_fact(user_id):
        user, member = users.get(user_id), members.get(user_id)
        active = member is not None and member.is_active and member.deleted_at is None
        return HumanMembershipFact(
            user_id,
            user is not None and user.is_active and not user.is_bot,
            active,
            member.id if active else None,
        )

    product = Product.objects.select_for_update(no_key=True).filter(workspace_id=workspace.id, id=product_id).first()
    roadmap = (
        Roadmap.objects.select_for_update(no_key=True)
        .filter(workspace_id=workspace.id, product_id=product_id, id=roadmap_id)
        .first()
    )
    milestone = (
        Milestone.objects.select_for_update(no_key=True)
        .filter(
            workspace_id=workspace.id,
            product_id=product_id,
            roadmap_id=roadmap_id,
            id=payload["milestone_id"],
        )
        .first()
    )
    feature = (
        Feature.objects.select_for_update(no_key=True)
        .filter(workspace_id=workspace.id, product_id=product_id, id=payload["feature_id"])
        .first()
    )
    if any(value is None for value in (product, roadmap, milestone, feature)):
        raise CurvePolicyResourceNotFound
    supported = all(row.schema_version == "1.0" for row in (roadmap, milestone, feature))
    try:
        require_supported_product_format(product)
    except ProductFormatUnavailable:
        supported = False
    actor = human_fact(actor_id)
    generation = None
    if actor.active_member:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT generation FROM curve_feature_membership_lifetime WHERE membership_id=%s FOR UPDATE",
                [actor.membership_id],
            )
            row = cursor.fetchone()
            if row is not None:
                generation = row[0]
    return ItemCreationFacts(
        workspace.id,
        product.id,
        roadmap.id,
        milestone.id,
        feature.id,
        roadmap.owner_user_id,
        roadmap.version,
        is_curve_enabled_for_workspace(workspace.slug),
        product.state == "ACTIVE",
        supported,
        all(row.tombstoned_at is None for row in (roadmap, milestone, feature)),
        actor,
        generation,
        tuple((gate, human_fact(user_id)) for gate, user_id in assignments),
    )
