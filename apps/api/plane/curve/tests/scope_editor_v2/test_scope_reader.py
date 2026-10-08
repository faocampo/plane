# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real qualified metadata reads, session authentication and native row fences."""

# ruff: noqa: F401,F811 -- imported pytest fixtures are intentional.
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import hashlib
import json
import re
import time
import uuid

import pytest
from django.apps import apps
from django.utils import timezone
from django.db import DatabaseError, close_old_connections, connection, transaction
from rest_framework.test import APIClient

from plane.curve import scope_editor_read_v2 as reader
from plane.curve import scope_reopening_qualification as qualification
from plane.curve.models import Initiative, Product
from plane.curve.scope_proposal_models import ScopeProposalRevision
from plane.curve.tests.test_scope_proposal_api import (
    configuration,
    context,
    scope_configuration,
    scope,
    replace,
    read as read_members,
)
from plane.db.models import ProjectMember, User, Workspace, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
DENIED = {"error": "SCOPE_EDITOR_PRECONDITION_UNAVAILABLE"}
FIELDS = {
    "schema_version",
    "policy_edition",
    "workspace_id",
    "product_id",
    "initiative_id",
    "initiative_version",
    "scope_status",
    "expected_scope_revision",
}


@pytest.fixture(autouse=True)
def enabled(scope_configuration, settings):
    settings.CURVE_SCOPE_EDITOR_READ_V2_ENABLED = True


def endpoint(scope):
    return f"/api/v1/workspaces/alpha/curve/initiatives/{scope.initiative.id}/scope-editor/v2/preconditions/"


def session(scope, user=None):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(user or scope.user)
    return client


def counts():
    return {model._meta.label: model.objects.count() for model in apps.get_app_config("curve").get_models()}


def call(scope):
    return reader.read_scope_editor_preconditions(
        request=SimpleNamespace(user=scope.user, query_params={}),
        workspace_slug="alpha",
        initiative_id=scope.initiative.id,
    )


def assert_denied(response):
    assert response.status_code == 404 and response.json() == DENIED
    assert response["Cache-Control"] == "no-store" and "ETag" not in response


def test_absent_saved_empty_and_complete_lineage_have_no_writes(scope):
    client = session(scope)
    for revision in range(4):
        if revision:
            saved = replace(scope, items=[], expected=revision - 1, version=revision, key=f"empty-{revision}")
            assert saved.status_code == 201, saved.content
        before = counts()
        writes = []

        def record(execute, sql, params, many, context):
            if re.match(r"\s*(INSERT|UPDATE|DELETE|TRUNCATE|CREATE|ALTER|DROP)\b", sql, re.I):
                writes.append(sql.split()[0])
            return execute(sql, params, many, context)

        with connection.execute_wrapper(record):
            response = client.get(endpoint(scope))
            head = client.head(endpoint(scope))
        assert response.status_code == head.status_code == 200, response.content
        assert set(response.json()) == FIELDS
        assert response.json()["scope_status"] == ("PRESENT" if revision else "ABSENT")
        assert response.json()["expected_scope_revision"] == revision
        assert response.json()["initiative_version"] == revision + 1
        assert response["ETag"] == head["ETag"] == f'"curve-initiative:{scope.initiative.id}:v{revision + 1}"'
        assert response["Cache-Control"] == head["Cache-Control"] == "no-store"
        assert head.content == b"" and writes == [] and counts() == before
        assert "Private" not in response.content.decode() and "source_issue_id" not in response.content.decode()


def test_session_required_query_and_unsupported_methods_are_uniform(scope):
    authenticated = session(scope)
    anonymous = APIClient(enforce_csrf_checks=True)
    token_only = APIClient(enforce_csrf_checks=True)
    token_only.credentials(HTTP_AUTHORIZATION="Bearer synthetic-not-a-session", HTTP_X_API_KEY="synthetic")
    before = counts()
    for client in (anonymous, token_only):
        assert_denied(client.get(endpoint(scope)))
    assert_denied(authenticated.get(endpoint(scope) + "?details=1"))
    for method in ("post", "put", "patch", "delete", "options"):
        assert_denied(getattr(authenticated, method)(endpoint(scope)))
    assert counts() == before


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_SCOPE_EDITOR_READ_V2_ENABLED", False),
        ("CURVE_SCOPE_EDITOR_READ_V2_ENABLED", "true"),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
        ("CURVE_ENABLED", False),
        ("CURVE_ENABLED_WORKSPACE_SLUGS", frozenset()),
        ("CURVE_LOCAL_PLANE_INSTALLATION_ID", None),
    ],
)
def test_default_local_workspace_gates(scope, settings, setting, value):
    client = session(scope)
    setattr(settings, setting, value)
    assert_denied(client.get(endpoint(scope)))


def test_creator_admin_and_native_membership_are_distinct(scope):
    creator = session(scope)
    WorkspaceMember.objects.filter(id=scope.membership.id).update(role=15)
    assert creator.get(endpoint(scope)).status_code == 200
    other = User.objects.create(email="scope-reader@example.invalid", username="scope-reader")
    membership = WorkspaceMember.objects.create(workspace=scope.workspace, member=other, role=15, is_active=True)
    other_client = session(scope, other)
    assert_denied(other_client.get(endpoint(scope)))
    WorkspaceMember.objects.filter(id=membership.id).update(role=20)
    assert other_client.get(endpoint(scope)).status_code == 200
    WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
    assert_denied(other_client.get(endpoint(scope)))
    WorkspaceMember.objects.filter(id=scope.membership.id).update(role=10)
    assert_denied(creator.get(endpoint(scope)))


@pytest.mark.parametrize("condition", ["inactive_user", "bot", "inactive_product", "non_draft", "non_standalone"])
def test_current_native_lifecycle_denies(scope, condition):
    client = session(scope)
    if condition == "inactive_user":
        User.objects.filter(id=scope.user.id).update(is_active=False)
    elif condition == "bot":
        User.objects.filter(id=scope.user.id).update(is_bot=True)
    elif condition == "inactive_product":
        scope.product.state = "ARCHIVED"
        scope.product.archived_at = timezone.now()
        scope.product.archived_by = {"actor_type": "HUMAN", "actor_id": str(scope.user.id)}
        scope.product.save()
    elif condition == "non_draft":
        scope.initiative.state = "ALIGNING"
        scope.initiative.workflow_version_id = uuid.uuid4()
        scope.initiative.save()
    else:
        actor = {"actor_type": "HUMAN", "actor_id": str(scope.user.id)}
        scope.initiative = Initiative.objects.create(
            workspace_id=scope.workspace.id,
            product_id=scope.product.id,
            mode="ROADMAP",
            roadmap_item_id=uuid.uuid4(),
            keyword="roadmap-reader",
            title="Synthetic roadmap scope",
            description={},
            risk_tier="STANDARD",
            creator_user_id=scope.user.id,
            created_by=actor,
            updated_by=actor,
        )
    assert_denied(client.get(endpoint(scope)))


def test_minimal_metadata_does_not_restore_lost_source_visibility(scope):
    assert replace(scope).status_code == 201
    ProjectMember.objects.filter(id=scope.project_membership.id).update(is_active=False)
    client = session(scope)
    before = counts()
    response = client.get(endpoint(scope))
    assert response.status_code == 200 and set(response.json()) == FIELDS
    assert counts() == before
    assert read_members(scope).status_code != 200


def test_native_final_fence_rejects_and_rolls_back_change(scope, monkeypatch):
    original = reader._verify_current_scope

    def revoke(initiative):
        original(initiative)
        WorkspaceMember.objects.filter(id=scope.membership.id).update(is_active=False)

    monkeypatch.setattr(reader, "_verify_current_scope", revoke)
    client = session(scope)
    before = counts()
    assert_denied(client.get(endpoint(scope)))
    scope.membership.refresh_from_db()
    assert scope.membership.is_active and counts() == before


def test_complete_history_bound_denies_before_broad_integrity(scope, monkeypatch):
    for revision in range(1, 4):
        assert (
            replace(scope, items=[], expected=revision - 1, version=revision, key=f"bound-{revision}").status_code
            == 201
        )
    monkeypatch.setattr(reader, "MAX_REVISIONS", 2)

    def unexpected(_):
        pytest.fail("Broad integrity must not run after the bounded lineage query rejects")

    monkeypatch.setattr(reader, "_verify_current_scope", unexpected)
    assert_denied(session(scope).get(endpoint(scope)))


def test_old_revision_sql_corruption_is_denied_and_read_remains_intact(scope):
    first = replace(scope, items=[])
    assert first.status_code == 201
    assert replace(scope, items=[], expected=1, version=2, key="second").status_code == 201
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE curve_scope_proposal_revision SET membership_digest=%s WHERE id=%s",
            ["sha256:" + "0" * 64, first.json()["id"]],
        )
    result = call(scope)
    assert result["expected_scope_revision"] == 2


def test_separate_closed_successor_preserves_predecessor_and_storage(scope):
    with transaction.atomic():
        qualification.require_scope_editor_read_v2_qualification()
    manual_raw = qualification.MANUAL_SUCCESSOR_PATH.read_bytes()
    assert "sha256:" + hashlib.sha256(manual_raw).hexdigest() == qualification.MANUAL_SUCCESSOR_DIGEST
    old = json.loads(manual_raw)["qualification"]
    successor = json.loads(qualification.SCOPE_EDITOR_SUCCESSOR_PATH.read_bytes())
    new = qualification.validate_scope_editor_successor(old, successor, qualification.MANUAL_SUCCESSOR_DIGEST)
    assert all(old[key] == new[key] for key in old if key != "runtime_sources")
    assert set(new["runtime_sources"]) - set(old["runtime_sources"]) == {
        "scope_editor_read_v2.py",
        "scope_editor_read_views_v2.py",
    }
    assert {key for key in old["runtime_sources"] if old["runtime_sources"][key] != new["runtime_sources"][key]} == {
        "urls.py"
    }
    # The reader proof remains immutable when a separately qualified writer follows it.
    # Validate that exact successor before comparing against the installed inventory.
    gate2_raw = qualification.GATE2_SUCCESSOR_PATH.read_bytes()
    assert "sha256:" + hashlib.sha256(gate2_raw).hexdigest() == qualification.GATE2_SUCCESSOR_DIGEST
    installed = qualification.validate_gate2_successor(new, json.loads(gate2_raw))
    installed = qualification.validate_source_header_successor(
        installed,
        qualification._read_pinned_successor(
            qualification.HEADER_SUCCESSOR_PATH, qualification.HEADER_SUCCESSOR_DIGEST
        ),
    )
    assert qualification.current_runtime_sources() == installed["runtime_sources"]


@pytest.mark.parametrize("missing", [False, True])
def test_changed_or_missing_reader_proof_fails_closed(scope, monkeypatch, missing):
    client = session(scope)
    if missing:
        monkeypatch.setattr(qualification, "SCOPE_EDITOR_SUCCESSOR_DIGEST", None)
    else:
        original = Path.read_bytes
        path = qualification.SCOPE_EDITOR_SUCCESSOR_PATH
        monkeypatch.setattr(Path, "read_bytes", lambda p: original(p) + b" " if p == path else original(p))
    assert_denied(client.get(endpoint(scope)))


def worker(callable):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout='8s'")
        return callable()
    finally:
        close_old_connections()


def test_writer_commits_first_then_reader_sees_current_precondition(scope):
    attempted = Event()
    reader_pid = []

    def read_after():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            reader_pid.append(cursor.fetchone()[0])
        attempted.set()
        return call(scope)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Workspace.objects.select_for_update().get(id=scope.workspace.id)
            result = replace(scope, items=[])
            assert result.status_code == 201
            future = pool.submit(worker, read_after)
            assert attempted.wait(5)
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [reader_pid[0]])
                    blocked = cursor.fetchone()[0] > 0
                if blocked:
                    break
                Event().wait(0.01)
            assert blocked and not future.done()
        result = future.result(20)
    assert result["expected_scope_revision"] == 1 and result["initiative_version"] == 2


def test_reader_lock_serializes_concurrent_writer_and_stale_save_rejects(scope, monkeypatch):
    held, release, writer_started = Event(), Event(), Event()
    original = reader._metadata_snapshot
    calls = 0
    writer_pid = []

    def pause_first(initiative):
        nonlocal calls
        result = original(initiative)
        calls += 1
        if calls == 1:
            held.set()
            assert release.wait(15)
        return result

    monkeypatch.setattr(reader, "_metadata_snapshot", pause_first)

    def write_after():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            writer_pid.append(cursor.fetchone()[0])
        writer_started.set()
        return replace(scope, items=[])

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(worker, lambda: call(scope))
        assert held.wait(10)
        writing = pool.submit(worker, write_after)
        try:
            assert writer_started.wait(5)
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [writer_pid[0]])
                    blocked = cursor.fetchone()[0] > 0
                if blocked:
                    break
                Event().wait(0.01)
            assert blocked and not writing.done()
        finally:
            release.set()
        before = reading.result(20)
        saved = writing.result(20)
    assert before["scope_status"] == "ABSENT" and before["initiative_version"] == 1
    assert saved.status_code == 201, saved.content
    assert call(scope)["initiative_version"] == 2
    assert replace(scope, items=[], version=1, expected=0, key="stale-after-read").status_code == 412
