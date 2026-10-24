# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Database scope/session contract checks; metadata adapter remains synthetic."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
import uuid

import pytest
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from plane.curve import prd_read_views
from plane.curve.models import Initiative
from plane.curve.prd_read_context import PrdReadUnavailable
from plane.curve.tests.test_external_document_models import initiative_values
from plane.curve.tests.test_prd_read_context import context, uid, NOW  # noqa: F401
from plane.db.models import User, Workspace, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def revise_versions(value):
    if isinstance(value, dict):
        return {k: (1 if k == "initiative_version" else revise_versions(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [revise_versions(v) for v in value]
    return value


@pytest.fixture
def db_context(context, settings, monkeypatch):  # noqa: F811
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"synthetic-workspace", "foreign-workspace"})
    settings.CURVE_PRD_READ_ENABLED = True
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.MIDDLEWARE = [
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
    ]
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    context.snapshot = revise_versions(context.snapshot)
    context.runtime.snapshot = context.snapshot
    context.scope["initiative_version"] = 1
    settings.CURVE_PRD_READ_RUNTIME = context.runtime
    user = User.objects.create(id=uid(3), username="synthetic-scope-user", email="scope@example.invalid")
    workspace = Workspace.objects.create(id=uid(1), name="Synthetic scope", slug="synthetic-workspace", owner=user)
    membership = WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    initiative = Initiative.objects.create(id=uid(2), **initiative_values(workspace.id))
    foreign_workspace = Workspace.objects.create(name="Synthetic foreign", slug="foreign-workspace", owner=user)
    foreign_initiative = Initiative.objects.create(**initiative_values(foreign_workspace.id))
    client = APIClient()
    client.force_login(user)
    monkeypatch.setattr(
        prd_read_views.timezone, "now", lambda: timezone.datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    )
    return SimpleNamespace(
        context=context,
        user=user,
        workspace=workspace,
        membership=membership,
        initiative=initiative,
        foreign_workspace=foreign_workspace,
        foreign_initiative=foreign_initiative,
        client=client,
    )


def path(db_context, *, slug=None, initiative_id=None):
    return reverse(
        "curve-prd-review-context",
        kwargs={
            "slug": slug or db_context.workspace.slug,
            "initiative_id": initiative_id or db_context.initiative.id,
        },
    )


def hidden(response):
    assert response.status_code == 404, getattr(response, "data", None)
    assert response.json() == {
        "type": "urn:curve:problem:prd-context-unavailable",
        "title": "PRD context unavailable",
        "status": 404,
        "code": "PRD_CONTEXT_UNAVAILABLE",
    }
    assert response["Cache-Control"] == "no-store"


def test_real_session_route_and_scope_succeed_without_writes(db_context):
    before = deepcopy(db_context.context.snapshot)
    with CaptureQueriesContext(connection) as queries:
        response = db_context.client.get(path(db_context))
    assert response.status_code == 200, response.data
    assert response.json()["command_preconditions"]["commandETag"] == '"1"'
    assert response["Cache-Control"] == "no-store"
    assert db_context.context.runtime.calls == ["authorize", "read", "authorize", "fence"]
    assert db_context.context.snapshot == before
    sql = [item["sql"] for item in queries]
    assert sum("workspace_members" in item for item in sql) == 2
    assert sum("curve_initiative" in item for item in sql) == 2
    assert not [item for item in sql if item.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]


@pytest.mark.parametrize(
    "change", ["membership_inactive", "membership_deleted", "workspace_deleted", "user_inactive", "user_bot"]
)
def test_persisted_revocation_denies_real_route_before_metadata_read(db_context, change):
    if change == "membership_inactive":
        WorkspaceMember.objects.filter(id=db_context.membership.id).update(is_active=False)
    elif change == "membership_deleted":
        WorkspaceMember.objects.filter(id=db_context.membership.id).update(deleted_at=timezone.now())
    elif change == "workspace_deleted":
        Workspace.objects.filter(id=db_context.workspace.id).update(deleted_at=timezone.now())
    else:
        User.objects.filter(id=db_context.user.id).update(
            **{"is_active" if change == "user_inactive" else "is_bot": change != "user_inactive"}
        )
    hidden(db_context.client.get(path(db_context)))
    assert db_context.context.runtime.calls == []


@pytest.mark.parametrize(
    "scenario",
    ["foreign_workspace_without_membership", "foreign_initiative_same_slug", "missing_workspace", "missing_initiative"],
)
def test_cross_tenant_and_absent_scope_are_indistinguishable(db_context, scenario):
    kwargs = {
        "foreign_workspace_without_membership": dict(
            slug=db_context.foreign_workspace.slug, initiative_id=db_context.foreign_initiative.id
        ),
        "foreign_initiative_same_slug": dict(initiative_id=db_context.foreign_initiative.id),
        "missing_workspace": dict(slug="nonexistent-workspace"),
        "missing_initiative": dict(initiative_id=uuid.uuid4()),
    }[scenario]
    hidden(db_context.client.get(path(db_context, **kwargs)))
    assert db_context.context.runtime.calls == []


def test_membership_in_both_tenants_still_cannot_cross_initiative(db_context):
    WorkspaceMember.objects.create(workspace=db_context.foreign_workspace, member=db_context.user, role=20)
    hidden(db_context.client.get(path(db_context, initiative_id=db_context.foreign_initiative.id)))
    hidden(db_context.client.get(path(db_context, slug=db_context.foreign_workspace.slug)))
    assert db_context.context.runtime.calls == []


@pytest.mark.parametrize("field,value", [("is_active", False), ("is_bot", True)])
def test_database_user_flags_override_stale_authenticated_user_object(db_context, field, value):
    assert db_context.user.is_active and not db_context.user.is_bot
    User.objects.filter(id=db_context.user.id).update(**{field: value})
    with pytest.raises(PrdReadUnavailable):
        prd_read_views.resolve_prd_read_scope(
            request=SimpleNamespace(user=db_context.user),
            workspace_slug=db_context.workspace.slug,
            initiative_id=db_context.initiative.id,
        )


def test_anonymous_and_post_do_not_read_metadata(db_context):
    hidden(APIClient().get(path(db_context)))
    hidden(db_context.client.post(path(db_context), {"role": "ADMIN"}, format="json"))
    assert db_context.context.runtime.calls == []


@pytest.mark.parametrize("flag", ["CURVE_ENABLED", "CURVE_PRD_READ_ENABLED"])
def test_disabled_switches_prevent_database_scope_lookup(db_context, settings, flag):
    setattr(settings, flag, False)
    with CaptureQueriesContext(connection) as queries:
        hidden(db_context.client.get(path(db_context)))
    assert not [q["sql"] for q in queries if "workspace_members" in q["sql"] or "curve_initiative" in q["sql"]]
    assert db_context.context.runtime.calls == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "change", ["membership_inactive", "membership_deleted", "user_inactive", "user_bot", "initiative_version"]
)
def test_separate_connection_committed_change_is_rejected_at_final_scope_fence(db_context, change):
    # Commit a concurrent DB writer between initial scope and final scope reads.
    # No ORM managers or selector methods are mocked.
    main_pid = connection.connection.info.backend_pid
    writer_pid = []

    def mutate():
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                writer_pid.append(cursor.fetchone()[0])
            if change == "membership_inactive":
                WorkspaceMember.objects.filter(id=db_context.membership.id).update(is_active=False)
            elif change == "membership_deleted":
                WorkspaceMember.objects.filter(id=db_context.membership.id).update(deleted_at=timezone.now())
            elif change == "initiative_version":
                Initiative.objects.filter(id=db_context.initiative.id).update(version=2)
            else:
                User.objects.filter(id=db_context.user.id).update(
                    **{"is_active" if change == "user_inactive" else "is_bot": change != "user_inactive"}
                )
        finally:
            connections.close_all()

    original = db_context.context.runtime.read_metadata

    def read_metadata(**kwargs):
        result = original(**kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(mutate).result(timeout=15)
        return result

    db_context.context.runtime.read_metadata = read_metadata
    hidden(db_context.client.get(path(db_context)))
    assert writer_pid and writer_pid[0] != main_pid
    assert db_context.context.runtime.calls == ["authorize", "read"]
