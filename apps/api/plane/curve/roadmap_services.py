# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Transactional Roadmap hierarchy candidate; transport and qualification follow separately."""

import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

from dataclasses import dataclass
from datetime import date
import re
import uuid

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from plane.curve.models import (
    AuditOutcome,
    DataClassification,
    DomainEvent,
    IdempotencyState,
    Milestone,
    OutboxEvent,
    Roadmap,
)
from plane.curve.roadmap_models import MilestoneType
from plane.curve.product_format import ProductFormatUnavailable
from plane.curve.product_services import _command_identity, _load_or_create_idempotency, ProductValidationError
from plane.curve.roadmap_policy import RoadmapFormatUnavailable, append_audit, assert_receipt, execute_mutation
from plane.curve.services import (
    CommandAlreadyInProgress,
    IdempotencyConflict,
    OptimisticConcurrencyError,
    ReplayResourceUnavailable,
    canonical_json_bytes,
    operation_response_digest,
)


_EVENT_BYTES = (Path(__file__).parent / "roadmap_domain/hierarchy-event-v1.schema.json").read_bytes()
if (
    "sha256:" + hashlib.sha256(_EVENT_BYTES).hexdigest()
    != "sha256:f00b291e494131182145599e63cc7bd40779d36fac395cb046c82d75244fc4fd"
):
    raise RuntimeError("ROADMAP_EVENT_CONTRACT_CHANGED")
_EVENT_VALIDATOR = Draft202012Validator(json.loads(_EVENT_BYTES), format_checker=FormatChecker())


class RoadmapCommandError(Exception):
    code = "ROADMAP_COMMAND_INVALID"


@dataclass(frozen=True, slots=True)
class RoadmapCommandResult:
    resource_ref: dict
    response_status: int
    response_digest: str
    replayed: bool


def _keys(value, allowed, required):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise RoadmapCommandError


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise RoadmapCommandError
    return value


def _dates(payload, start, end):
    values = {}
    for key in (start, end):
        value = payload.get(key)
        if value is not None:
            if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                raise RoadmapCommandError
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise RoadmapCommandError from error
        values[key] = value
    if values[start] is not None and values[end] is not None and values[start] > values[end]:
        raise RoadmapCommandError
    return values


def _version(value):
    if type(value) is not int or value < 1:
        raise RoadmapCommandError
    return value


def _normalize(action, payload):
    if action in {"CREATE_ROADMAP", "UPDATE_ROADMAP"}:
        _keys(payload, {"name", "horizon_start", "horizon_end"}, {"name"})
        return {"name": _name(payload["name"]), **_dates(payload, "horizon_start", "horizon_end")}
    if action in {"CREATE_MILESTONE", "UPDATE_MILESTONE"}:
        allowed = {"name", "type", "target_start", "target_end"}
        required = {"name", "type"}
        if action == "CREATE_MILESTONE":
            allowed.add("position")
            required.add("position")
        _keys(payload, allowed, required)
        if payload["type"] not in MilestoneType.values:
            raise RoadmapCommandError
        result = {
            "name": _name(payload["name"]),
            "type": payload["type"],
            **_dates(payload, "target_start", "target_end"),
        }
        if "position" in payload:
            if type(payload["position"]) is not int or not 0 <= payload["position"] <= 9223372036854775807:
                raise RoadmapCommandError
            result["position"] = payload["position"]
        return result
    if action == "REORDER_MILESTONES":
        _keys(payload, {"milestone_ids"}, {"milestone_ids"})
        ids = payload["milestone_ids"]
        if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
            raise RoadmapCommandError
        try:
            ids = [str(uuid.UUID(value)) for value in ids]
        except ValueError as error:
            raise RoadmapCommandError from error
        if len(set(ids)) != len(ids):
            raise RoadmapCommandError
        return {"milestone_ids": ids}
    raise RoadmapCommandError


def _ref(record):
    return {
        "resource_type": "MILESTONE" if isinstance(record, Milestone) else "ROADMAP",
        "resource_id": str(record.id),
        "resource_version": record.version,
    }


def _snapshot(record):
    fields = (
        ("name", "type", "position", "target_start", "target_end")
        if isinstance(record, Milestone)
        else ("name", "owner_user_id", "horizon_start", "horizon_end")
    )
    return {
        **_ref(record),
        **{
            key: str(value) if isinstance(value, (date, uuid.UUID)) else value
            for key in fields
            for value in [getattr(record, key)]
        },
    }


def _event(receipt, record, action, before, key_digest):
    assert_receipt(receipt)
    at = timezone.now()
    event = DomainEvent.objects.create(
        workspace_id=receipt.workspace_id,
        event_type=f"curve.roadmap.{action.lower()}",
        aggregate_type=_ref(record)["resource_type"],
        aggregate_id=record.id,
        aggregate_version=record.version,
        sequence=record.version,
        actor=dict(receipt.actor),
        effective_principal=dict(receipt.actor),
        correlation_id=receipt.correlation_id,
        idempotency_key_digest=key_digest,
        classification=DataClassification.INTERNAL,
        payload_schema="https://curve.example.invalid/contracts/candidates/roadmap-hierarchy-event-v1.schema.json",
        payload={
            "schema_version": "1.0",
            "workspace_id": str(receipt.workspace_id),
            "product_id": str(receipt.product_id),
            "action": action,
            "before": before,
            "after": _snapshot(record),
            "actor": dict(receipt.actor),
            "occurred_at": at.isoformat(),
        },
        occurred_at=at,
    )
    _EVENT_VALIDATOR.validate(event.payload)
    OutboxEvent.objects.create(
        workspace_id=receipt.workspace_id, event_id=event.id, destination="CURVE_ROADMAP_LOCAL_V1"
    )


def _update(record, values, actor):
    for key, value in values.items():
        setattr(record, key, value)
    record.version += 1
    record.updated_by = dict(actor)
    record.save(update_fields=[*values, "version", "updated_by", "updated_at"])


def execute_hierarchy_command(
    *,
    request,
    workspace_slug,
    product_id,
    action,
    payload,
    raw_idempotency_key,
    roadmap_id=None,
    milestone_id=None,
    expected_version=None,
):
    def callback(receipt, product, roadmap):
        values = _normalize(action, payload)
        if (action == "CREATE_ROADMAP" and expected_version is not None) or (
            action != "UPDATE_MILESTONE" and milestone_id is not None
        ):
            raise RoadmapCommandError
        if action != "CREATE_ROADMAP":
            _version(expected_version)
        milestone = None
        if action == "UPDATE_MILESTONE":
            try:
                target_id = uuid.UUID(str(milestone_id))
            except (ValueError, TypeError) as error:
                raise RoadmapCommandError from error
            milestone = (
                Milestone.objects.select_for_update()
                .filter(
                    workspace_id=receipt.workspace_id,
                    product_id=product.id,
                    roadmap_id=roadmap.id,
                    id=target_id,
                    tombstoned_at__isnull=True,
                )
                .first()
            )
            if milestone is None:
                raise RoadmapCommandError
            if milestone.schema_version != "1.0":
                raise RoadmapFormatUnavailable
        target = milestone or roadmap
        canonical = canonical_json_bytes(
            {
                "action": action,
                "product_id": str(product.id),
                "roadmap_id": str(roadmap.id) if roadmap else None,
                "milestone_id": str(milestone.id) if milestone else None,
                "expected_version": expected_version,
                "payload": values,
            }
        )
        identity = _command_identity(
            receipt,
            command_scope=f"CURVE.ROADMAP.{action}:{product.id}:{target.id if target else product.id}",
            raw_idempotency_key=raw_idempotency_key,
            canonical_request=canonical,
        )
        record, _, replay = _load_or_create_idempotency(workspace_id=receipt.workspace_id, identity=identity)
        if replay:
            ref = record.response_resource_ref
            model = {"ROADMAP": Roadmap, "MILESTONE": Milestone}.get(
                ref.get("resource_type") if isinstance(ref, dict) else None
            )
            if model is None:
                raise ReplayResourceUnavailable
            retained = (
                model.objects.select_for_update()
                .filter(
                    workspace_id=receipt.workspace_id,
                    product_id=product.id,
                    id=ref.get("resource_id"),
                    tombstoned_at__isnull=True,
                )
                .first()
            )
            if retained is None or (
                isinstance(retained, Roadmap) and retained.owner_user_id != uuid.UUID(receipt.actor["actor_id"])
            ):
                raise ReplayResourceUnavailable
            if retained.schema_version != "1.0":
                raise RoadmapFormatUnavailable
            append_audit(
                receipt, target_ref=ref, outcome=AuditOutcome.NO_EFFECT, key_digest=record.key_digest, replay=True
            )
            return RoadmapCommandResult(dict(ref), record.response_status, record.response_digest, True)
        if target is not None and target.version != expected_version:
            raise OptimisticConcurrencyError
        common = {
            "workspace_id": receipt.workspace_id,
            "product_id": product.id,
            "created_by": dict(receipt.actor),
            "updated_by": dict(receipt.actor),
        }
        if action == "CREATE_ROADMAP":
            result = Roadmap.objects.create(**common, **values, owner_user_id=uuid.UUID(receipt.actor["actor_id"]))
            _event(receipt, result, action, None, identity["key_digest"])
        elif action == "CREATE_MILESTONE":
            if Milestone.objects.filter(
                workspace_id=receipt.workspace_id, roadmap_id=roadmap.id, position=values["position"]
            ).exists():
                raise RoadmapCommandError
            before = _snapshot(roadmap)
            result = Milestone.objects.create(**common, **values, roadmap_id=roadmap.id)
            _update(roadmap, {}, receipt.actor)
            _event(receipt, result, action, None, identity["key_digest"])
            _event(receipt, roadmap, "MILESTONE_ADDED", before, identity["key_digest"])
        elif action == "REORDER_MILESTONES":
            rows = list(
                Milestone.objects.select_for_update()
                .filter(
                    workspace_id=receipt.workspace_id,
                    product_id=product.id,
                    roadmap_id=roadmap.id,
                    tombstoned_at__isnull=True,
                )
                .order_by("id")
            )
            if set(values["milestone_ids"]) != {str(row.id) for row in rows}:
                raise RoadmapCommandError
            by_id = {str(row.id): row for row in rows}
            before = _snapshot(roadmap)
            for position, item_id in enumerate(values["milestone_ids"]):
                row = by_id[item_id]
                if row.schema_version != "1.0":
                    raise RoadmapFormatUnavailable
                if row.position != position:
                    old = _snapshot(row)
                    _update(row, {"position": position}, receipt.actor)
                    _event(receipt, row, "MILESTONE_POSITION_CHANGED", old, identity["key_digest"])
            _update(roadmap, {}, receipt.actor)
            _event(receipt, roadmap, action, before, identity["key_digest"])
            result = roadmap
        else:
            before = _snapshot(target)
            _update(target, values, receipt.actor)
            _event(receipt, target, action, before, identity["key_digest"])
            result = target
        # Validate only this hierarchy, then roll back the validation savepoint
        # to restore the caller's constraint modes without undoing earlier writes.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET CONSTRAINTS curve_rmap_product_fk, curve_mstone_product_fk, "
                    "curve_mstone_roadmap_fk, curve_mstone_position_uq IMMEDIATE"
                )
            transaction.set_rollback(True)
        ref = _ref(result)
        status = 201 if action.startswith("CREATE_") else 200
        digest = operation_response_digest(response_status=status, resource_ref=ref)
        append_audit(
            receipt, target_ref=ref, outcome=AuditOutcome.SUCCEEDED, key_digest=record.key_digest, after_digest=digest
        )
        record.state = IdempotencyState.COMPLETED
        record.response_status, record.response_digest, record.response_resource_ref = status, digest, ref
        record.completed_at = timezone.now()
        record.save(
            update_fields=["state", "response_status", "response_digest", "response_resource_ref", "completed_at"]
        )
        return RoadmapCommandResult(ref, status, digest, False)

    return execute_mutation(
        request=request,
        workspace_slug=workspace_slug,
        product_id=product_id,
        roadmap_id=roadmap_id,
        action=action,
        callback=callback,
        no_effect_exceptions=(
            RoadmapCommandError,
            RoadmapFormatUnavailable,
            ProductFormatUnavailable,
            ProductValidationError,
            IdempotencyConflict,
            CommandAlreadyInProgress,
            OptimisticConcurrencyError,
            ReplayResourceUnavailable,
            IntegrityError,
        ),
    )
