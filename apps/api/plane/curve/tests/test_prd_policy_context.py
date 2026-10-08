# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from plane.curve.models import GateAssignment, Initiative, Operation, PolicyDecision, AuditEvent
from plane.curve.policy_services import CurvePolicyDenied, execute_authorized_mutation, assert_active_mutation_receipt
from plane.curve.services import _create_operation_authorized, canonical_json_bytes
from plane.curve.policy_evaluator import evaluate_core_policy
from plane.curve.policy_types import PolicyEffect
from plane.curve.prd_policy_context import PrdAuthorityUnavailable, build_prd_policy_context
from plane.curve.tests.test_external_document_models import initiative_values
from plane.db.models import User, Workspace, WorkspaceMember


pytestmark = [pytest.mark.unit, pytest.mark.django_db]


@pytest.fixture
def graph(settings):
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = {"policy-fixture"}
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "synthetic-prd-policy-recorder"
    settings.CURVE_PRD_COMMANDS_ENABLED = True
    humans = [User.objects.create(email=f"human-{n}@example.invalid", username=f"human-{n}") for n in range(4)]
    workspace = Workspace.objects.create(name="Synthetic workspace", slug="policy-fixture", owner=humans[0])
    for user in humans:
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=20 if user == humans[0] else 15)
    values = initiative_values(workspace.id)
    values["creator_user_id"] = humans[0].id
    initiative = Initiative.objects.create(**values)
    gates = [
        GateAssignment.objects.create(
            workspace_id=workspace.id,
            initiative=initiative,
            gate_type=kind,
            approver_user_id=user.id,
            valid_from=timezone.now() - timedelta(days=1),
        )
        for kind, user in zip(["PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"], humans[1:])
    ]
    return workspace, initiative, humans, gates


def resolver(**context):
    return dict(
        classification="INTERNAL",
        object_acl=dict(
            workspace_id=str(context["workspace_id"]),
            resource_ref=deepcopy(context["resource_ref"]),
            acl_version=1,
            allow_principals=[deepcopy(context["actor"])],
            deny_principals=[],
            allow_roles=[],
            deny_roles=[],
        ),
    )


def evaluate(graph, *, user_index=1, action="APPROVE", acl_resolver=resolver, **overrides):
    workspace, initiative, humans, _ = graph
    params = dict(
        request=SimpleNamespace(user=humans[user_index]),
        workspace_slug=workspace.slug,
        initiative_id=initiative.id,
        action=f"CURVE.PRD.{action}",
        acl_resolver=acl_resolver,
    )
    params.update(overrides)
    context = build_prd_policy_context(**params)
    return context, evaluate_core_policy(context)


@pytest.mark.parametrize("action", ["SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"])
def test_current_context_is_derived_from_database_identity_and_assignments(graph, action):
    context, result = evaluate(graph, action=action, for_update=True)
    assert result.effect is PolicyEffect.ALLOW
    assert context["resource"]["ref"]["resource_version"] == graph[1].version
    assert len(context["assignment_context"]["gate_assignments"]) == 3


def test_creator_has_submission_authority_but_administrator_role_does_not_approve(graph):
    assert evaluate(graph, user_index=0, action="SUBMIT")[1].effect is PolicyEffect.ALLOW
    assert evaluate(graph, user_index=0, action="APPROVE")[1].effect is PolicyEffect.DENY


@pytest.mark.parametrize("change", ["membership", "account", "bot"])
def test_current_database_actor_revocation_overrides_stale_request_user(graph, change):
    workspace, _, humans, _ = graph
    user = humans[1]
    if change == "membership":
        WorkspaceMember.objects.filter(workspace=workspace, member=user).update(is_active=False)
    elif change == "account":
        User.objects.filter(id=user.id).update(is_active=False)
    else:
        User.objects.filter(id=user.id).update(is_bot=True)
    acl = Mock(side_effect=AssertionError("Must not resolve object ACL"))
    assert evaluate(graph, acl_resolver=acl)[1].effect is PolicyEffect.DENY
    acl.assert_not_called()


@pytest.mark.parametrize("change", ["membership", "account", "bot", "expired", "future"])
def test_inactive_other_gate_member_blocks_submission_and_approval(graph, change):
    workspace, _, humans, gates = graph
    if change == "membership":
        WorkspaceMember.objects.filter(workspace=workspace, member=humans[3]).update(is_active=False)
    elif change in {"account", "bot"}:
        User.objects.filter(id=humans[3].id).update(
            **({"is_active": False} if change == "account" else {"is_bot": True})
        )
    else:
        gate = gates[2]
        if change == "expired":
            gate.valid_until = timezone.now() - timedelta(seconds=1)
        else:
            gate.valid_from = timezone.now() + timedelta(days=1)
        gate.save_base(force_update=True)
    for action in ["SUBMIT", "APPROVE"]:
        assert evaluate(graph, action=action)[1].effect is PolicyEffect.DENY


def test_future_expiration_remains_valid_until_current_time(graph):
    gate = graph[3][1]
    gate.valid_until = timezone.now() + timedelta(hours=1)
    gate.save_base(force_update=True)
    assert evaluate(graph)[1].effect is PolicyEffect.ALLOW


@pytest.mark.parametrize("state", [False, "true", 1, None])
def test_enablement_requires_explicit_boolean_and_skips_acl_reads(graph, settings, state):
    settings.CURVE_PRD_COMMANDS_ENABLED = state
    acl = Mock(side_effect=AssertionError("Must not resolve object ACL"))
    assert evaluate(graph, acl_resolver=acl)[1].effect is PolicyEffect.DENY
    acl.assert_not_called()


@pytest.mark.parametrize("lookup", [None, lambda **_: None, lambda **_: {"classification": "INTERNAL"}])
def test_unavailable_acl_authority_does_not_fall_back_to_creator_allow(graph, lookup):
    with pytest.raises(PrdAuthorityUnavailable):
        evaluate(graph, user_index=0, action="SUBMIT", acl_resolver=lookup)


def test_authority_failure_suppresses_backend_exception_details(graph):
    def unavailable(**_):
        raise RuntimeError("Synthetic protected sentinel")

    with pytest.raises(PrdAuthorityUnavailable) as error:
        evaluate(graph, acl_resolver=unavailable)
    assert error.value.__suppress_context__ and "sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "bad",
    [
        {"classification": {}, "object_acl": None},
        {"classification": "UNKNOWN_TYPE", "object_acl": None},
        {"classification": "INTERNAL", "object_acl": {"allow_principals": None}},
    ],
)
def test_malformed_authority_observations_are_rejected_safely(graph, bad):
    with pytest.raises(PrdAuthorityUnavailable) as error:
        evaluate(graph, acl_resolver=lambda **_: bad)
    assert error.value.__suppress_context__


def test_resolver_receives_exact_action_scope_and_cannot_mutate_context(graph):
    seen = []

    def resolve(**arguments):
        seen.append(deepcopy(arguments))
        result = resolver(**arguments)
        arguments["resource_ref"]["resource_version"] = 999
        arguments["actor"]["actor_id"] = "changed"
        return result

    context, result = evaluate(graph, action="REQUEST_CHANGES", acl_resolver=resolve)
    assert result.effect is PolicyEffect.ALLOW
    assert seen[0]["action"] == "CURVE.PRD.REQUEST_CHANGES"
    assert seen[0]["workspace_id"] == graph[0].id
    assert context["resource"]["ref"]["resource_version"] == graph[1].version
    assert context["subject"]["actor_id"] == str(graph[2][1].id)


def test_foreign_initiative_does_not_reach_object_authority(graph):
    acl = Mock()
    assert evaluate(graph, initiative_id=uuid.uuid4(), acl_resolver=acl)[1].effect is PolicyEffect.DENY
    acl.assert_not_called()


def test_request_role_and_acl_claims_are_ignored(graph):
    request = SimpleNamespace(user=graph[2][0], data={"role": "PRODUCT_APPROVER", "object_acl": "allow"})
    assert evaluate(graph, request=request)[1].effect is PolicyEffect.DENY


@pytest.mark.django_db(transaction=True)
def test_commit_context_requires_transaction(graph):
    with pytest.raises(PermissionError, match="PRD_AUTHORIZATION_TRANSACTION_REQUIRED"):
        evaluate(graph, for_update=True)
    with transaction.atomic():
        assert evaluate(graph, for_update=True)[1].effect is PolicyEffect.ALLOW


def accept_operation(graph, action, key, *, capture_receipt=None):
    workspace, initiative, humans, _ = graph
    request = SimpleNamespace(user=humans[1])
    action_name = f"CURVE.PRD.{action}"

    def context_builder():
        return build_prd_policy_context(
            request=request,
            workspace_slug=workspace.slug,
            initiative_id=initiative.id,
            action=action_name,
            acl_resolver=resolver,
            for_update=True,
        )

    def callback(receipt, _observation):
        if capture_receipt is not None:
            capture_receipt.append(receipt)
        return _create_operation_authorized(
            authorization_receipt=receipt,
            authorization_action=action_name,
            workspace_id=workspace.id,
            principal_scope=f"HUMAN:{humans[1].id}",
            command_scope=f"PRD_{action}:{initiative.id}",
            raw_idempotency_key=key,
            canonical_request=canonical_json_bytes({"action": action, "expected_version": initiative.version}),
            operation_type="WORKFLOW_COMMAND",
            command_type=f"PRD_{action}",
            target=dict(receipt.resource_ref),
            actor={"actor_type": "HUMAN", "actor_id": str(humans[1].id)},
            correlation_id="synthetic-prd-command",
            destination="CURVE_PRD_CANDIDATE_V1",
        )

    return execute_authorized_mutation(context_builder=context_builder, mutation_callback=callback)


@pytest.mark.parametrize("action", ["SUBMIT", "APPROVE", "REQUEST_CHANGES", "REJECT"])
def test_prd_policy_receipt_can_accept_exact_operation_once_and_cannot_escape_scope(graph, action):
    receipts = []
    first = accept_operation(graph, action, "synthetic-command-key", capture_receipt=receipts)
    replay = accept_operation(graph, action, "synthetic-command-key")
    assert not first.replayed and replay.replayed
    assert first.operation.id == replay.operation.id and Operation.objects.count() == 1
    assert PolicyDecision.objects.filter(policy_key="CURVE_PRD_POLICY").count() == 2
    assert AuditEvent.objects.count() == 2
    with pytest.raises(PermissionError):
        assert_active_mutation_receipt(
            receipts[0],
            action=f"CURVE.PRD.{action}",
            workspace_id=graph[0].id,
            resource_ref=dict(receipts[0].resource_ref),
        )


def test_replay_reauthorizes_current_membership_before_returning_existing_operation(graph):
    original = accept_operation(graph, "APPROVE", "synthetic-replay-key")
    WorkspaceMember.objects.filter(workspace=graph[0], member=graph[2][1]).update(is_active=False)
    with pytest.raises(CurvePolicyDenied):
        accept_operation(graph, "APPROVE", "synthetic-replay-key")
    assert Operation.objects.count() == 1 and Operation.objects.get().id == original.operation.id
    assert PolicyDecision.objects.filter(effect="DENY").count() == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_version": 2},
        {"policy_manifest_digest": "sha256:" + "0" * 64},
        {"policy_key": "CURVE_UNKNOWN_POLICY"},
    ],
)
def test_database_pins_prd_policy_identity_to_exact_candidate(graph, changes):
    accept_operation(graph, "APPROVE", "synthetic-policy-identity")
    candidate = PolicyDecision.objects.get()
    candidate.id = uuid.uuid4()
    candidate.sequence += 1
    for field, value in changes.items():
        setattr(candidate, field, value)
    with pytest.raises(DatabaseError), transaction.atomic():
        candidate.save_base(force_insert=True)
    assert PolicyDecision.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_prd_policy_migration_reverses_empty_and_preserves_retained_decisions(graph):
    latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
    previous = [("curve", "0013_initiative_prd_lifecycle")]
    try:
        MigrationExecutor(connection).migrate(previous)
        assert Initiative.objects.filter(id=graph[1].id).exists()
    finally:
        MigrationExecutor(connection).migrate(latest)
    accept_operation(graph, "APPROVE", "synthetic-policy-retention")
    try:
        with pytest.raises(DatabaseError, match="preservation migration"):
            MigrationExecutor(connection).migrate(previous)
    finally:
        MigrationExecutor(connection).migrate(latest)
    assert PolicyDecision.objects.filter(policy_key="CURVE_PRD_POLICY").count() == 1
