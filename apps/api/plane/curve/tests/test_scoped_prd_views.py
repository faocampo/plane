# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Session transport and synthetic trusted-read fences, without a database.

Native authorization/persistence is mocked; these tests do not qualify providers
or prove PostgreSQL concurrency, and do not activate the candidate runtime.
"""

from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from django.test import RequestFactory
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory

from plane.curve import scoped_prd_read, scoped_prd_views
from plane.curve.prd_commands import PrdCommandError
from plane.curve.request_privacy import is_prd_command_request
from plane.curve.scoped_prd_contracts import POLICY_EDITION, SCHEMA_VERSION, metadata_digest
from plane.curve.tests.test_prd_read_context import context, uid, NOW  # noqa: F401
from plane.middleware.request_body_size import RequestBodySizeLimitMiddleware

pytestmark = pytest.mark.unit
SLUG = "synthetic-workspace"


def pins():
    return dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        proposal_id=uid(100),
        scope_revision_id=uid(101),
        scope_revision=1,
        membership_digest="sha256:" + "d" * 64,
    )


def signed(value):
    return {**value, "digest": metadata_digest(value)}


@pytest.fixture
def api(context, settings, monkeypatch):  # noqa: F811
    from plane.curve import scoped_prd_models, scoped_prd_policy

    for flag in (
        "CURVE_ENABLED",
        "CURVE_PRD_COMMANDS_ENABLED",
        "CURVE_SCOPED_PRD_COMMANDS_ENABLED",
        "CURVE_PRD_READ_ENABLED",
    ):
        setattr(settings, flag, True)
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({SLUG})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_PRD_READ_RUNTIME = context.runtime
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    state = SimpleNamespace(atomic=False)

    @contextmanager
    def atomic():
        assert not state.atomic
        state.atomic = True
        try:
            yield
        finally:
            state.atomic = False

    monkeypatch.setattr(scoped_prd_read.transaction, "atomic", atomic)
    monkeypatch.setattr(scoped_prd_read, "resolve_prd_read_scope", lambda **kwargs: deepcopy(context.scope))
    monkeypatch.setattr(
        scoped_prd_read.timezone,
        "now",
        lambda: scoped_prd_read.timezone.datetime.fromisoformat(NOW.replace("Z", "+00:00")),
    )
    for name in ("observe", "read_metadata"):
        original = getattr(context.runtime, name)

        def outside(*, call=original, **kwargs):
            assert not state.atomic, "Provider preparation ran under native locks"
            return call(**kwargs)

        monkeypatch.setattr(context.runtime, name, outside)
    member = dict(
        association_id=uid(102),
        association_version=1,
        provider_installation_id=uid(103),
        source_project_id=uid(104),
        source_issue_id=uid(105),
        purpose="PROPOSED_DELIVERY",
    )
    base = {
        **pins(),
        "workspace_id": uid(1),
        "product_id": uid(107),
        "initiative_id": uid(2),
        "created_by": uid(3),
        "recorded_at": NOW,
        "controlling": False,
    }
    observation = signed(
        {
            **base,
            "id": uid(106),
            "initiative_version": 7,
            "members": [{**member, "source_version": "1", "source_fingerprint": "sha256:" + "e" * 64}],
            "reviewers": [
                {"gate_assignment_id": uid(110 + i), "gate_type": gate, "approver_user_id": uid(120 + i)}
                for i, gate in enumerate(sorted(["PRD_APPROVAL", "PLAN_APPROVAL", "CODE_READINESS"]))
            ],
        }
    )
    checkpoint = context.snapshot["checkpoint"]["metadata"]
    subject = signed(
        {
            **base,
            "id": uid(108),
            "checkpoint_id": checkpoint["id"],
            **{
                key: checkpoint[key]
                for key in ("artifact_version_id", "content_digest", "provider_version", "evidence_snapshot_id")
            },
            "members": [member],
            "observation_set_id": observation["id"],
            "observation_digest": observation["digest"],
            "scoped_readiness_id": uid(109),
            "scoped_readiness_digest": "sha256:" + "f" * 64,
        }
    )

    def record(payload):
        return SimpleNamespace(as_record=lambda: deepcopy(payload))

    observations, subjects = MagicMock(), MagicMock()
    observations.find_by_id.return_value = record(observation)
    subjects.find_by_id.return_value = record(subject)
    subjects.for_workspace.return_value.select_for_update.return_value.filter.return_value.first.return_value = record(
        subject
    )
    monkeypatch.setattr(scoped_prd_models.ScopedPrdObservation, "objects", observations)
    monkeypatch.setattr(scoped_prd_models.ScopedPrdSubject, "objects", subjects)
    initiative = SimpleNamespace(
        id=uuid.UUID(uid(2)),
        workspace_id=uuid.UUID(uid(1)),
        version=7,
        current_prd_checkpoint_id=uuid.UUID(checkpoint["id"]),
    )
    native = SimpleNamespace(initiative=initiative, fence=("synthetic-current-fence",))

    def guard(**kwargs):
        assert state.atomic
        context.runtime.calls.append("native")
        return native

    guard = MagicMock(side_effect=guard)
    monkeypatch.setattr(scoped_prd_policy, "require_scoped_current", guard)
    user = SimpleNamespace(id=uuid.UUID(uid(3)), is_authenticated=True, is_active=True, is_bot=False)
    return SimpleNamespace(
        context=context,
        state=state,
        guard=guard,
        native=native,
        user=user,
        observation=observation,
        subject=subject,
        observations=observations,
        subjects=subjects,
    )


def read(api, kind="observation", *, user=None, method="get"):
    if kind == "observation":
        view, kwargs = scoped_prd_views.CurveScopedPrdObservationEndpoint, {"observation_id": uuid.UUID(uid(106))}
    else:
        view = scoped_prd_views.CurveScopedPrdSubjectEndpoint
        kwargs = {} if kind == "current" else {"scoped_subject_id": uuid.UUID(uid(108))}
    request = getattr(APIRequestFactory(), method)("/synthetic-protected-read")
    request.user = api.user if user is None else user
    response = view.as_view()(request, slug=SLUG, initiative_id=uuid.UUID(uid(2)), **kwargs)
    response.render()
    return response


def command(api, route="observe", *, payload=None, body=None, headers=None, csrf=False):
    if payload is None:
        payload = pins()
        if route == "submit":
            payload.update(
                external_document_binding_id=uid(21),
                evidence_snapshot_id=uid(23),
                completeness_check_id=uid(20),
                observation_set_id=api.observation["id"],
                observation_digest=api.observation["digest"],
            )
    request = APIRequestFactory(enforce_csrf_checks=csrf).post(
        "/synthetic-scoped-command",
        data=body if body is not None else json.dumps(payload),
        content_type="application/json",
        **(
            {"HTTP_IF_MATCH": '"7"', "HTTP_IDEMPOTENCY_KEY": "synthetic-scoped-command"} if headers is None else headers
        ),
    )
    request.user = api.user
    response = scoped_prd_views.CurveScopedPrdCommandEndpoint.as_view(route=route)(
        request, slug=SLUG, initiative_id=uuid.UUID(uid(2))
    )
    response.render()
    return response


def hidden(response):
    assert response.status_code == 404
    assert response.data == {
        "type": "urn:curve:problem:prd-context-unavailable",
        "title": "PRD context unavailable",
        "status": 404,
        "code": "PRD_CONTEXT_UNAVAILABLE",
    }
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize("kind", ["observation", "subject", "current"])
def test_closed_read_uses_ordinary_authority_then_native_and_final_fences(api, kind):
    response = read(api, kind)
    assert response.status_code == 200, response.data
    assert response.data == (api.observation if kind == "observation" else api.subject)
    assert response["Cache-Control"] == "no-store"
    assert api.context.runtime.calls == [
        "authorize",
        "read",
        "authorize",
        "fence",
        "native",
        "native",
        "fence",
        "native",
    ]
    args = dict(workspace_id=uid(1), initiative_id=uid(2), actor_id=uid(3))
    assert api.guard.call_args_list[0].kwargs == args
    assert api.guard.call_args_list[-1].kwargs.keys() == args.keys() | {
        "observation" if kind == "observation" else "subject"
    }
    if kind == "current":
        api.subjects.for_workspace.assert_called_once_with(uid(1))
        api.subjects.for_workspace.return_value.select_for_update.return_value.filter.assert_called_once_with(
            initiative_id=uid(2), checkpoint_id=uuid.UUID(uid(24))
        )
    assert not api.state.atomic


@pytest.mark.parametrize(
    "flag",
    ["CURVE_ENABLED", "CURVE_PRD_COMMANDS_ENABLED", "CURVE_SCOPED_PRD_COMMANDS_ENABLED", "CURVE_PRD_READ_ENABLED"],
)
def test_disabled_read_never_reaches_provider_or_native_rows(api, settings, flag):
    setattr(settings, flag, False)
    hidden(read(api))
    assert api.context.runtime.calls == []
    api.guard.assert_not_called()
    api.observations.find_by_id.assert_not_called()


@pytest.mark.parametrize("environment", ["", "local", "STAGING", "PRODUCTION"])
def test_scoped_reads_are_exactly_local_only(api, settings, environment):
    settings.CURVE_ENVIRONMENT = environment
    hidden(read(api))
    assert api.context.runtime.calls == []


@pytest.mark.parametrize("user", [AnonymousUser(), SimpleNamespace(is_authenticated=True, is_active=False)])
def test_invalid_sessions_are_non_disclosing(api, user):
    hidden(read(api, user=user))
    assert api.context.runtime.calls == []


def test_wrong_workspace_and_missing_trusted_runtime_never_read_rows(api, settings):
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"somewhere-else"})
    hidden(read(api))
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({SLUG})
    settings.CURVE_PRD_READ_RUNTIME = None
    hidden(read(api))
    api.guard.assert_not_called()


@pytest.mark.parametrize(
    "field", ["membership", "object_metadata", "source_metadata", "evidence_metadata", "classification_access"]
)
def test_ordinary_read_denial_precedes_scoped_access(api, field):
    api.context.runtime.on_observe = lambda result, _: {**result, field: "DENY"}
    hidden(read(api))
    api.guard.assert_not_called()
    api.observations.find_by_id.assert_not_called()


def test_native_diagnostic_and_missing_record_are_non_disclosing(api):
    api.observations.find_by_id.return_value = None
    missing = read(api)
    hidden(missing)
    api.guard.side_effect = RuntimeError("Synthetic protected sentinel")
    denied = read(api)
    hidden(denied)
    assert denied.data == missing.data
    assert b"sentinel" not in denied.content


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_final_local_runtime_fence_requires_strict_true(api, value):
    original = api.context.runtime.is_current

    def fence(**kwargs):
        result = original(**kwargs)
        return value if api.state.atomic else result

    api.context.runtime.is_current = fence
    hidden(read(api))


@pytest.mark.parametrize("change", ["scope", "initiative_version", "native_fence", "native_denial", "checkpoint"])
def test_changes_during_final_runtime_hook_are_hidden(api, change):
    original = api.context.runtime.is_current

    def fence(**kwargs):
        result = original(**kwargs)
        if api.state.atomic:
            if change == "scope":
                api.context.scope["actor_id"] = uid(99)
            elif change == "initiative_version":
                api.native.initiative.version += 1
            elif change == "native_fence":
                api.native.fence = ("changed-current-fence",)
            elif change == "checkpoint":
                api.native.initiative.current_prd_checkpoint_id = uuid.UUID(uid(999))
            else:
                api.guard.side_effect = PrdCommandError("SCOPED_PRD_UNAVAILABLE", 404)
        return result

    api.context.runtime.is_current = fence
    hidden(read(api))


def test_scope_change_while_waiting_for_native_locks_is_hidden(api):
    original = api.guard.side_effect

    def guard(**kwargs):
        api.context.scope["initiative_version"] += 1
        return original(**kwargs)

    api.guard.side_effect = guard
    hidden(read(api))
    api.observations.find_by_id.assert_not_called()


@pytest.mark.parametrize(
    "field", ["checkpoint_id", "artifact_version_id", "evidence_snapshot_id", "content_digest", "provider_version"]
)
def test_subject_cannot_borrow_access_to_other_current_evidence(api, field):
    api.subject[field] = (
        "sha256:" + "0" * 64 if field == "content_digest" else "changed" if field == "provider_version" else uid(999)
    )
    api.subject["digest"] = metadata_digest(api.subject)
    hidden(read(api, "subject"))


@pytest.mark.parametrize("field", ["id", "workspace_id", "initiative_id"])
def test_exact_record_substitution_is_hidden(api, field):
    api.observation[field] = uid(999)
    api.observation["digest"] = metadata_digest(api.observation)
    hidden(read(api))


@pytest.mark.parametrize(
    "damage",
    ["open_field", "bad_digest", "duplicate_member", "unordered_members", "duplicate_gate", "duplicate_assignment"],
)
def test_closed_record_integrity_is_required(api, damage):
    value = api.observation
    if damage == "open_field":
        value["task_body"] = "Synthetic protected sentinel"
    elif damage == "bad_digest":
        value["digest"] = "sha256:" + "0" * 64
    elif damage == "duplicate_member":
        value["members"].append(deepcopy(value["members"][0]))
    elif damage == "unordered_members":
        value["members"].append({**value["members"][0], "source_issue_id": uid(104)})
    elif damage == "duplicate_gate":
        value["reviewers"][1]["gate_type"] = value["reviewers"][0]["gate_type"]
    else:
        value["reviewers"][1]["gate_assignment_id"] = value["reviewers"][0]["gate_assignment_id"]
    if damage != "bad_digest":
        value["digest"] = metadata_digest(value)
    response = read(api)
    hidden(response)
    assert b"sentinel" not in response.content


def test_get_and_head_never_capture_or_accept_commands(api, monkeypatch):
    capture, accept = MagicMock(), MagicMock()
    monkeypatch.setattr(scoped_prd_views, "capture_scoped_prd_observation", capture)
    monkeypatch.setattr(scoped_prd_views, "accept_scoped_prd_command", accept)
    assert read(api, method="head").status_code == 200
    hidden(read(api, method="post"))
    capture.assert_not_called()
    accept.assert_not_called()


def test_observation_capture_returns_closed_original_201_on_replay(api, monkeypatch):
    capture = MagicMock(return_value=SimpleNamespace(data=api.observation, response_status=201, replayed=True))
    monkeypatch.setattr(scoped_prd_views, "capture_scoped_prd_observation", capture)
    response = command(api)
    assert response.status_code == 201, response.data
    assert response.data == api.observation
    assert response["ETag"] == '"7"'
    assert response["Cache-Control"] == "no-store"
    assert response["Location"].endswith("/scoped-prd/v1/observations/" + uid(106))
    assert capture.call_args.kwargs["command"].action == "CURVE.SCOPED_PRD.OBSERVE"


def test_submit_dispatches_new_parser_and_returns_async_operation(api, monkeypatch):
    operation = SimpleNamespace(
        id=uid(130), workspace_id=uid(1), operation_type="SCOPED_PRD_V1_SUBMIT", status="QUEUED", aggregate_version=1
    )
    accept = MagicMock(return_value=SimpleNamespace(operation=operation, replayed=False))
    monkeypatch.setattr(scoped_prd_views, "accept_scoped_prd_command", accept)
    response = command(api, "submit")
    assert response.status_code == 202, response.data
    assert response.data["operation_type"] == "SCOPED_PRD_V1_SUBMIT"
    assert response["ETag"] == '"7"' and response["Cache-Control"] == "no-store"
    assert response["Location"].endswith("/operations/" + uid(130) + "/")
    parsed = accept.call_args.kwargs["command"]
    assert parsed.subject_metadata()["schema_version"] == SCHEMA_VERSION
    assert parsed.subject_metadata()["policy_edition"] == POLICY_EDITION


@pytest.mark.parametrize("flag", ["CURVE_ENABLED", "CURVE_PRD_COMMANDS_ENABLED", "CURVE_SCOPED_PRD_COMMANDS_ENABLED"])
def test_disabled_command_stops_before_parser(api, settings, monkeypatch, flag):
    setattr(settings, flag, False)
    parse = MagicMock()
    monkeypatch.setattr(scoped_prd_views, "parse_scoped_prd_command", parse)
    response = command(api)
    assert response.status_code == 404 and response.data["code"] == "NOT_FOUND"
    assert response["Cache-Control"] == "no-store"
    parse.assert_not_called()


@pytest.mark.parametrize("environment", ["STAGING", "PRODUCTION"])
def test_command_cannot_run_outside_local(api, settings, environment):
    settings.CURVE_ENVIRONMENT = environment
    assert command(api).status_code == 404


@pytest.mark.parametrize(
    "headers,status",
    [({}, 428), ({"HTTP_IF_MATCH": 'W/"7"', "HTTP_IDEMPOTENCY_KEY": "k"}, 412), ({"HTTP_IF_MATCH": '"7"'}, 422)],
)
def test_observation_requires_strong_version_and_idempotency(api, monkeypatch, headers, status):
    capture = MagicMock()
    monkeypatch.setattr(scoped_prd_views, "capture_scoped_prd_observation", capture)
    response = command(api, headers=headers)
    assert response.status_code == status and response["Cache-Control"] == "no-store"
    capture.assert_not_called()


@pytest.mark.parametrize("damage", ["missing_edition", "wrong_edition", "extra_field", "duplicate_key", "oversize"])
def test_explicit_closed_command_is_required(api, monkeypatch, damage):
    capture = MagicMock()
    monkeypatch.setattr(scoped_prd_views, "capture_scoped_prd_observation", capture)
    payload, body = pins(), None
    if damage == "missing_edition":
        del payload["schema_version"]
    elif damage == "wrong_edition":
        payload["policy_edition"] = "LEGACY"
    elif damage == "extra_field":
        payload["reviewer_override"] = True
    elif damage == "duplicate_key":
        body = json.dumps(payload)[:-1] + ', "scope_revision": 2}'
    else:
        body = " " * 65537
    response = command(api, payload=payload, body=body)
    assert response.status_code == (413 if damage == "oversize" else 422)
    assert response["Cache-Control"] == "no-store"
    capture.assert_not_called()


def test_session_csrf_remains_required(api, monkeypatch):
    capture = MagicMock()
    monkeypatch.setattr(scoped_prd_views, "capture_scoped_prd_observation", capture)
    response = command(api, csrf=True)
    assert response.status_code == 403 and response.data["code"] == "FORBIDDEN"
    assert response["Cache-Control"] == "no-store"
    capture.assert_not_called()


def test_command_diagnostics_never_leave_boundary(api, monkeypatch):
    monkeypatch.setattr(
        scoped_prd_views,
        "capture_scoped_prd_observation",
        MagicMock(side_effect=ValueError("Synthetic protected sentinel")),
    )
    response = command(api)
    assert response.status_code == 503 and response.data["code"] == "PRD_RUNTIME_UNAVAILABLE"
    assert b"sentinel" not in response.content and response["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "name,suffix,extra",
    [
        ("observe", "observations", {}),
        ("observation", "observations/" + uid(106), {"observation_id": uid(106)}),
        ("subject", "subjects/" + uid(108), {"scoped_subject_id": uid(108)}),
        ("subject-current", "subjects/current", {}),
        ("submit", "submit", {}),
        ("approve", "approve", {}),
        ("return-for-revision", "return-for-revision", {}),
    ],
)
def test_explicit_scoped_routes(api, name, suffix, extra):
    path = reverse("curve-scoped-prd-" + name, kwargs={"slug": SLUG, "initiative_id": uid(2), **extra})
    assert path.endswith("/scoped-prd/v1/" + suffix)
    assert resolve(path).url_name == "curve-scoped-prd-" + name


@pytest.mark.parametrize("suffix", ["observations", "submit", "approve", "return-for-revision"])
def test_raw_body_is_bounded_before_session_parser(suffix):
    path = f"/api/v1/workspaces/{SLUG}/curve/initiatives/{uid(2)}/scoped-prd/v1/{suffix}"
    request = RequestFactory().post(path, data=b"x" * 65537, content_type="application/json")
    downstream = MagicMock(return_value=JsonResponse({}))
    response = RequestBodySizeLimitMiddleware(downstream)(request)
    assert response.status_code == 413 and response["Cache-Control"] == "no-store"
    downstream.assert_not_called()
    assert is_prd_command_request(SimpleNamespace(path_info=path))
    assert is_prd_command_request(SimpleNamespace(path_info=path + "/"))
    assert not is_prd_command_request(SimpleNamespace(path_info=path + "/" + uid(106)))


def test_final_trusted_fence_rejects_changed_access_revision(api):
    # The installed adapter owns a revision of all subject and ACL inputs, not
    # only Initiative.version. Native membership locks cannot replace this fence.
    api.context.runtime.current_access_revision = api.context.snapshot["snapshot_revision"]
    original_guard = api.guard.side_effect
    original_fence = api.context.runtime.is_current

    def guard(**kwargs):
        result = original_guard(**kwargs)
        if "observation" in kwargs:
            api.context.runtime.current_access_revision = "revoked-classification-access"
        return result

    def fence(**kwargs):
        original_fence(**kwargs)
        return kwargs["snapshot_revision"] == api.context.runtime.current_access_revision

    api.guard.side_effect = guard
    api.context.runtime.is_current = fence
    hidden(read(api))


def test_fresh_scope_is_type_exact_not_boolean_integer_equal():
    scope = dict(workspace_id=uid(1), initiative_id=uid(2), actor_id=uid(3), initiative_version=1)
    native = SimpleNamespace(initiative=SimpleNamespace(workspace_id=uid(1), id=uid(2), version=1))
    with pytest.raises(PermissionError):
        scoped_prd_read._require_scope(native, scope, lambda: {**scope, "initiative_version": True})


@pytest.mark.parametrize(
    "route,decision",
    [("approve", None), ("return-for-revision", "CHANGES_REQUESTED"), ("return-for-revision", "REJECTED")],
)
def test_review_routes_keep_exact_subject_and_transient_rationale(api, monkeypatch, route, decision):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "policy_edition": POLICY_EDITION,
        "gate_assignment_id": uid(111),
        **{
            key: api.subject[key]
            for key in (
                "checkpoint_id",
                "artifact_version_id",
                "content_digest",
                "provider_version",
                "evidence_snapshot_id",
            )
        },
        "confirmed_risk_tier": "STANDARD",
        "rationale": "Synthetic protected rationale sentinel",
        "scoped_subject_id": api.subject["id"],
        "scoped_subject_digest": api.subject["digest"],
    }
    if decision is not None:
        payload["decision"] = decision
    operation = SimpleNamespace(
        id=uid(130), workspace_id=uid(1), operation_type="SCOPED_PRD_V1_REVIEW", status="QUEUED", aggregate_version=1
    )
    accept = MagicMock(return_value=SimpleNamespace(operation=operation, replayed=False))
    monkeypatch.setattr(scoped_prd_views, "accept_scoped_prd_command", accept)
    response = command(api, route, payload=payload)
    assert response.status_code == 202, response.data
    parsed = accept.call_args.kwargs["command"]
    assert parsed.subject_metadata()["scoped_subject_id"] == api.subject["id"]
    assert "rationale" not in parsed.subject_metadata()
    assert parsed.rationale_bytes == b"Synthetic protected rationale sentinel"
    assert b"sentinel" not in response.content
