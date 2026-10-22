# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
# ruff: noqa: F811 - imported pytest fixtures intentionally name test parameters.

import json
import uuid

import pytest
from django.db import connection, transaction, DatabaseError
from plane.db.models import ProjectMember, WorkspaceMember
from plane.curve.prd_commands import PrdCommandError
from plane.curve.scoped_prd_commands import parse_scoped_prd_command
from plane.curve.scoped_prd_editions import TWO_STAGE
from plane.curve.scoped_prd_models import ScopedPrdDecision, ScopedPrdAcceptedCommand
from plane.curve.tests import test_scoped_prd_bridge as legacy
from plane.curve.tests.test_scoped_prd_bridge import context, configuration, bridge  # noqa: F401

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def v2_command(bridge, route, payload, *, key=None, version=None):
    return parse_scoped_prd_command(
        route=route,
        body=json.dumps(
            dict(schema_version=TWO_STAGE.schema_version, policy_edition=TWO_STAGE.policy_edition, **payload)
        ).encode(),
        if_match=f'"{version or bridge.initiative.version}"',
        idempotency_key=key or str(uuid.uuid4()),
        edition=TWO_STAGE.schema_version,
    )


@pytest.fixture
def two_stage(bridge, monkeypatch):
    bridge.initiative.schema_version = "1.2"
    bridge.initiative.save(update_fields=["schema_version"])
    # Preserve the historical Code assignment but revoke its user's access.
    # Only the two current approvers should participate in this successor.
    WorkspaceMember.objects.filter(workspace=bridge.workspace, member=bridge.reviewers[2]).update(is_active=False)
    ProjectMember.objects.filter(project=bridge.project, member=bridge.reviewers[2]).update(is_active=False)
    monkeypatch.setattr(legacy, "cmd", v2_command)
    return bridge


def test_two_stage_submission_and_product_approval_persist(two_stage):
    subject, command, operation = legacy.submit(two_stage)
    assert subject.payload["schema_version"] == TWO_STAGE.schema_version
    assert operation.command_type == "SCOPED_PRD_V2_SUBMIT"
    assert ScopedPrdAcceptedCommand.objects.get(operation=operation).edition == TWO_STAGE.schema_version
    review = legacy.accept(two_stage, legacy.review_command(two_stage, subject)).operation
    assert legacy.complete(two_stage, review)["status"] == "SUCCEEDED"
    two_stage.initiative.refresh_from_db()
    assert two_stage.initiative.state == "PLANNING"
    assert ScopedPrdDecision.objects.get().payload["schema_version"] == TWO_STAGE.schema_version


def test_feedback_and_replacement_submission_keep_successor_edition(two_stage):
    subject, _, _ = legacy.submit(two_stage)
    operation = legacy.accept(two_stage, legacy.review_command(two_stage, subject, "return-for-revision")).operation
    assert legacy.complete(two_stage, operation)["status"] == "SUCCEEDED"
    two_stage.initiative.refresh_from_db()
    assert two_stage.initiative.state == "ALIGNING"
    replacement, _, _ = legacy.submit(two_stage)
    assert replacement.id != subject.id
    assert replacement.payload["schema_version"] == TWO_STAGE.schema_version


def test_both_approvers_still_need_current_source_access(two_stage):
    command = legacy.submission(two_stage)
    ProjectMember.objects.filter(project=two_stage.project, member=two_stage.reviewers[1]).update(is_active=False)
    with pytest.raises(PrdCommandError):
        legacy.accept(two_stage, command)
    assert not ScopedPrdAcceptedCommand.objects.exists()


def test_observation_replay_is_bound_to_two_stage_edition(two_stage):
    key = str(uuid.uuid4())
    first = legacy.observe(two_stage, key)
    replay = legacy.observe(two_stage, key)
    assert replay.replayed and replay.data == first.data
    assert [r["gate_type"] for r in first.data["reviewers"]] == ["PLAN_APPROVAL", "PRD_APPROVAL"]


def test_successor_database_seal_and_schema_dispatch():
    from importlib import import_module

    migration = import_module("plane.curve.migrations.0027_scoped_prd_two_stage")
    with connection.cursor() as cursor:
        cursor.execute("SELECT catalog_digest FROM curve_scoped_v2_coverage")
        assert cursor.fetchone()[0] == migration.CURRENT_CATALOG_DIGEST
        cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        cursor.execute(
            "SELECT curve_sprd_schema('observation',%s)->'properties'->'reviewers'->>'maxItems'",
            [TWO_STAGE.schema_version],
        )
        assert cursor.fetchone()[0] == "2"
        cursor.execute("SELECT curve_sprd_schema('observation')->'properties'->'reviewers'->>'maxItems'")
        assert cursor.fetchone()[0] == "3"
    for verb in (
        "UPDATE curve_scoped_v2_coverage SET catalog_digest='bad'",
        "DELETE FROM curve_scoped_v2_coverage",
        "TRUNCATE curve_scoped_v2_coverage",
    ):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(verb)


def test_successor_http_observation_uses_explicit_route_and_private_headers(two_stage):
    from rest_framework.test import APIRequestFactory, force_authenticate
    from plane.curve.scoped_prd_views import CurveScopedPrdCommandEndpoint
    from plane.curve.request_privacy import is_prd_command_request
    from django.urls import reverse, resolve

    payload = dict(
        schema_version=TWO_STAGE.schema_version, policy_edition=TWO_STAGE.policy_edition, **legacy.pins(two_stage)
    )
    url = reverse(
        "curve-scoped-prd-v2-observe", kwargs=dict(slug=two_stage.workspace.slug, initiative_id=two_stage.initiative.id)
    )
    assert resolve(url).func.view_initkwargs["edition"] == TWO_STAGE.schema_version
    request = APIRequestFactory().post(
        url,
        payload,
        format="json",
        HTTP_IF_MATCH=f'"{two_stage.initiative.version}"',
        HTTP_IDEMPOTENCY_KEY="synthetic-v2-http",
    )
    force_authenticate(request, user=two_stage.user)
    assert is_prd_command_request(request)
    response = CurveScopedPrdCommandEndpoint.as_view(route="observe", edition=TWO_STAGE.schema_version)(
        request, slug=two_stage.workspace.slug, initiative_id=two_stage.initiative.id
    )
    assert response.status_code == 201, response.data
    assert response.data["schema_version"] == TWO_STAGE.schema_version
    assert response["Cache-Control"] == "no-store"
    assert response["Location"] == reverse(
        "curve-scoped-prd-v2-observation",
        kwargs=dict(
            slug=two_stage.workspace.slug,
            initiative_id=two_stage.initiative.id,
            observation_id=response.data["id"],
        ),
    )
    assert resolve(response["Location"]).func.view_initkwargs["edition"] == TWO_STAGE.schema_version


def test_retained_successor_observation_prevents_reverse(two_stage):
    from importlib import import_module
    from types import SimpleNamespace

    migration = import_module("plane.curve.migrations.0027_scoped_prd_two_stage")
    legacy.observe(two_stage)
    with pytest.raises(RuntimeError, match="SCOPED_V2_RETAINED_EVIDENCE_PREVENTS_REVERSE"), transaction.atomic():
        migration.require_empty_reverse(None, SimpleNamespace(connection=connection))


def test_empty_successor_migration_roundtrip_restores_exact_predecessor_catalog():
    from importlib import import_module
    from django.db.migrations.executor import MigrationExecutor

    previous = import_module("plane.curve.migrations.0026_two_stage_approval_policy")
    current = import_module("plane.curve.migrations.0027_scoped_prd_two_stage")
    leaves = MigrationExecutor(connection).loader.graph.leaf_nodes("curve")
    try:
        MigrationExecutor(connection).migrate([("curve", "0026_two_stage_approval_policy")])
        with connection.cursor() as cursor:
            assert previous._catalog(cursor) == previous.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
        MigrationExecutor(connection).migrate([("curve", "0027_scoped_prd_two_stage")])
        with connection.cursor() as cursor:
            assert current._catalog(cursor) == current.CURRENT_CATALOG_DIGEST
            cursor.execute("SELECT curve_scope_reopening_verify_coverage()")
    finally:
        MigrationExecutor(connection).migrate(leaves)


def test_two_stage_relay_dispatches_versioned_command(two_stage, settings):
    from plane.curve.tests.test_scoped_prd_temporal import FakeClient, drain

    settings.CURVE_SCOPED_PRD_DELIVERY_ENABLED = True
    operation = legacy.accept(two_stage, legacy.submission(two_stage)).operation
    client = FakeClient()
    assert drain(two_stage, client) == 1
    assert len(client.calls) == 1
    operation.refresh_from_db()
    assert operation.command_type == "SCOPED_PRD_V2_SUBMIT"
    assert operation.workflow_id is not None
    assert legacy.complete(two_stage, operation)["status"] == "SUCCEEDED"


def test_current_two_stage_initiative_rejects_old_observation_command(two_stage):
    from plane.curve.scoped_prd_contracts import SCHEMA_VERSION, POLICY_EDITION
    from plane.curve.scoped_prd_observations import capture_scoped_prd_observation
    from plane.curve.scoped_prd_models import ScopedPrdObservation

    command = parse_scoped_prd_command(
        route="observe",
        body=json.dumps(
            dict(schema_version=SCHEMA_VERSION, policy_edition=POLICY_EDITION, **legacy.pins(two_stage))
        ).encode(),
        if_match=f'"{two_stage.initiative.version}"',
        idempotency_key="synthetic-incorrect-edition",
    )
    with pytest.raises(PrdCommandError, match="SCOPED_PRD_SUBJECT_CHANGED"):
        capture_scoped_prd_observation(
            request=two_stage.request,
            workspace_slug=two_stage.workspace.slug,
            initiative_id=two_stage.initiative.id,
            command=command,
        )
    assert not ScopedPrdObservation.objects.exists()
