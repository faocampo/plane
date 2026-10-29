# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
from uuid import uuid4

import pytest
from rest_framework.test import APIClient
from plane.curve.models import DomainEvent, Roadmap
from plane.db.models import WorkspaceMember
from plane.curve.tests.test_roadmap_commands import scope as command_scope

scope = command_scope
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def api_settings(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ROADMAP_HIERARCHY_ENABLED = True


def client(user):
    value = APIClient()
    value.force_authenticate(user=user)
    return value


def base(scope):
    return f"/api/v1/workspaces/alpha/curve/products/{scope.product.id}/roadmaps/"


def create(scope, api=None, key="synthetic-roadmap-key-0001", name="Synthetic Roadmap"):
    return (api or client(scope.owner)).post(base(scope), {"name": name}, format="json", HTTP_IDEMPOTENCY_KEY=key)


def test_create_read_and_replay_have_exact_receipt_and_no_store(scope):
    api = client(scope.owner)
    created, replay = create(scope, api), create(scope, api)
    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    assert created["ETag"] == replay["ETag"]
    assert replay["Idempotent-Replay"] == "true"
    detail = api.get(created["Location"])
    assert detail.status_code == 200
    assert detail.json()["owner_user_id"] == str(scope.owner.id)
    assert detail["ETag"] == created["ETag"]
    assert set(detail.json()) == {
        "id",
        "schema_version",
        "workspace_id",
        "product_id",
        "version",
        "name",
        "created_at",
        "updated_at",
        "owner_user_id",
        "horizon_start",
        "horizon_end",
    }
    for response in (created, replay, detail):
        assert response["Cache-Control"] == "no-store"


def test_feature_gate_is_off_unless_explicitly_enabled(scope, settings):
    settings.CURVE_ROADMAP_HIERARCHY_ENABLED = False
    response = create(scope)
    assert response.status_code == 404
    assert not Roadmap.objects.exists()


def test_anonymous_request_denied(scope):
    response = APIClient().get(base(scope))
    assert response.status_code in (401, 403)
    assert response["Cache-Control"] == "no-store"


def test_member_can_read_safe_metadata_but_cannot_create(scope):
    create(scope)
    api = client(scope.member)
    response = api.get(base(scope))
    assert response.status_code == 200 and len(response.json()["results"]) == 1
    assert create(scope, api).status_code == 403
    assert Roadmap.objects.count() == 1


def test_revocation_blocks_read_and_successful_retry(scope):
    api = client(scope.owner)
    created = create(scope, api)
    WorkspaceMember.objects.filter(workspace=scope.workspace, member=scope.owner).update(is_active=False)
    assert api.get(created["Location"]).status_code == 404
    assert create(scope, api).status_code == 403
    assert Roadmap.objects.count() == 1


@pytest.mark.parametrize("key", [None, "short", "x" * 256])
def test_idempotency_header_required(scope, key):
    headers = {} if key is None else {"HTTP_IDEMPOTENCY_KEY": key}
    response = client(scope.owner).post(base(scope), {"name": "Synthetic"}, format="json", **headers)
    assert response.status_code == 422 and not Roadmap.objects.exists()


@pytest.mark.parametrize("etag,status", [(None, 428), ('"wrong"', 412), ("*", 412)])
def test_update_requires_exact_target_etag(scope, etag, status):
    created = create(scope)
    headers = {"HTTP_IDEMPOTENCY_KEY": "synthetic-update-key-001"}
    if etag is not None:
        headers["HTTP_IF_MATCH"] = etag
    response = client(scope.owner).patch(created["Location"], {"name": "Changed"}, format="json", **headers)
    assert response.status_code == status
    assert Roadmap.objects.get().version == 1


def test_update_replay_returns_original_version_even_after_later_update(scope):
    api = client(scope.owner)
    created = create(scope, api)
    args = {"format": "json", "HTTP_IDEMPOTENCY_KEY": "synthetic-update-key-001", "HTTP_IF_MATCH": created["ETag"]}
    first = api.patch(created["Location"], {"name": "Changed"}, **args)
    assert first.status_code == 200
    later = api.patch(
        created["Location"],
        {"name": "Later"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-update-key-002",
        HTTP_IF_MATCH=first["ETag"],
    )
    assert later.status_code == 200
    replay = api.patch(created["Location"], {"name": "Changed"}, **args)
    assert replay.status_code == 200 and replay.json() == first.json() and replay["ETag"] == first["ETag"]
    assert api.get(created["Location"]).json()["name"] == "Later"


def test_roadmap_and_milestone_version_fences_are_distinct(scope):
    api = client(scope.owner)
    parent = create(scope, api)
    children = parent["Location"] + "milestones/"
    milestone = api.post(
        children,
        {"name": "First", "type": "PRODUCT_OUTCOME", "position": 0},
        format="json",
        HTTP_IF_MATCH=parent["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-milestone-key-001",
    )
    assert milestone.status_code == 201
    detail = api.get(milestone["Location"])
    listing = api.get(children)
    assert detail.status_code == listing.status_code == 200
    assert detail["ETag"] == milestone["ETag"]
    assert listing.json()["roadmap_version"] == 2
    invalid = api.patch(
        milestone["Location"],
        {"name": "Updated", "type": "PRODUCT_OUTCOME"},
        format="json",
        HTTP_IF_MATCH=listing["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-milestone-update-001",
    )
    assert invalid.status_code == 412
    updated = api.patch(
        milestone["Location"],
        {"name": "Updated", "type": "PRODUCT_OUTCOME"},
        format="json",
        HTTP_IF_MATCH=milestone["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-milestone-update-001",
    )
    assert updated.status_code == 200
    reordered = api.post(
        children + "reorder/",
        {"milestone_ids": [detail.json()["id"]]},
        format="json",
        HTTP_IF_MATCH=listing["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-reorder-key-001",
    )
    assert reordered.status_code == 200


def test_bounded_keyset_list_has_no_duplicates(scope):
    api = client(scope.owner)
    expected = {
        create(scope, api, key=f"synthetic-roadmap-key-{index:04d}").json()["resource_ref"]["resource_id"]
        for index in range(3)
    }
    first = api.get(base(scope), {"page_size": "2"})
    second = api.get(base(scope), {"page_size": "2", "cursor": first.json()["next_cursor"]})
    actual = [row["id"] for response in [first, second] for row in response.json()["results"]]
    assert len(actual) == len(set(actual)) == 3 and set(actual) == expected
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize(
    "query", ["page_size=0", "page_size=101", "page_size=2&page_size=3", "cursor=no", "owner=someone"]
)
def test_query_shape_is_closed(scope, query):
    response = client(scope.owner).get(base(scope) + "?" + query)
    assert response.status_code == 422


def test_cross_scope_and_missing_target_have_same_safe_problem(scope):
    api = client(scope.owner)
    created = create(scope, api)
    absent = api.get(base(scope) + str(uuid4()) + "/")
    foreign = api.get(created["Location"].replace(str(scope.product.id), str(uuid4())))
    assert absent.status_code == foreign.status_code == 404
    assert absent.json()["type"] == foreign.json()["type"]
    assert "Synthetic" not in str(absent.json()) + str(foreign.json())


def test_api_cannot_override_owner_or_add_code_approver(scope):
    response = client(scope.owner).post(
        base(scope),
        {"name": "Synthetic", "owner_user_id": str(scope.member.id), "code_approver": str(scope.admin.id)},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-forged-key-001",
    )
    assert response.status_code == 422
    assert not Roadmap.objects.exists() and not DomainEvent.objects.exists()


def test_real_session_mutation_requires_csrf(scope):
    api = APIClient(enforce_csrf_checks=True)
    api.force_login(scope.owner)
    response = api.post(
        base(scope), {"name": "Synthetic"}, format="json", HTTP_IDEMPOTENCY_KEY="synthetic-csrf-key-0001"
    )
    assert response.status_code == 403
    assert not Roadmap.objects.exists()


def test_session_only_entry_and_no_delete(scope):
    from rest_framework.authentication import SessionAuthentication
    from plane.curve.roadmap_views import RoadmapAPIView

    assert RoadmapAPIView.authentication_classes == [SessionAuthentication]
    created = create(scope)
    assert client(scope.owner).delete(created["Location"]).status_code == 405
    assert Roadmap.objects.count() == 1


def test_milestone_pagination_preserves_order_and_rejects_stale_cursor(scope):
    api = client(scope.owner)
    parent = create(scope, api)
    children = parent["Location"] + "milestones/"
    created = []
    for index, position in enumerate([10, 0]):
        current = api.get(parent["Location"])
        response = api.post(
            children,
            {"name": f"Milestone {position}", "type": "PRODUCT_OUTCOME", "position": position},
            format="json",
            HTTP_IF_MATCH=current["ETag"],
            HTTP_IDEMPOTENCY_KEY=f"synthetic-milestone-key-{index:04d}",
        )
        assert response.status_code == 201
        created.append(response.json()["resource_ref"]["resource_id"])
    first = api.get(children, {"page_size": "1"})
    assert first.status_code == 200 and first.json()["results"][0]["position"] == 0
    cursor = first.json()["next_cursor"]
    second = api.get(children, {"page_size": "1", "cursor": cursor})
    assert second.status_code == 200 and second.json()["results"][0]["position"] == 10
    reordered = api.post(
        children + "reorder/",
        {"milestone_ids": created},
        format="json",
        HTTP_IF_MATCH=first["ETag"],
        HTTP_IDEMPOTENCY_KEY="synthetic-milestone-reorder-0001",
    )
    assert reordered.status_code == 200
    stale = api.get(children, {"page_size": "1", "cursor": cursor})
    assert stale.status_code == 412 and stale["Cache-Control"] == "no-store"


def test_missing_hierarchy_qualification_has_safe_unavailable_response(scope, monkeypatch):
    from plane.curve import scope_reopening_qualification as qualification

    monkeypatch.setattr(qualification, "ROADMAP_HIERARCHY_SUCCESSOR_DIGEST", None)
    response = create(scope)
    assert response.status_code == 503
    assert response.json()["type"].endswith("/roadmap-integrity-unavailable")
    assert response["Cache-Control"] == "no-store"
    assert not Roadmap.objects.exists()


def test_browser_gzip_read_retains_usable_strong_write_precondition(scope):
    api = client(scope.owner)
    created = create(scope, api)
    detail = api.get(created["Location"], HTTP_ACCEPT_ENCODING="gzip, deflate, br")
    assert detail.status_code == 200
    assert len(detail.content) > 200
    assert detail["ETag"] == created["ETag"]
    assert "Content-Encoding" not in detail
    changed = api.patch(
        created["Location"],
        {"name": "Updated from browser version"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-browser-version-update",
        HTTP_IF_MATCH=detail["ETag"],
        HTTP_ACCEPT_ENCODING="gzip, deflate, br",
    )
    assert changed.status_code == 200
    assert changed["ETag"] == f'"curve-roadmap:{Roadmap.objects.get().id}:v2"'
    assert "Content-Encoding" not in changed
    stale = api.patch(
        created["Location"],
        {"name": "Stale write must fail"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="synthetic-browser-stale-update",
        HTTP_IF_MATCH=detail["ETag"],
    )
    assert stale.status_code == 412
    assert Roadmap.objects.get().name == "Updated from browser version"
