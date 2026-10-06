"""Real migrated save/read/replay/API graphs; no qualification or worker doubles."""

# ruff: noqa: F401,F811 -- imported pytest fixtures are collected here.
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import traceback
import re
import uuid

import pytest
from django.db import DatabaseError, close_old_connections, connections, connection, transaction
from rest_framework.test import APIClient

from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision
from plane.curve.manual_plan_v2 import contracts, reads, services
from plane.curve.manual_plan_v2.models import ManualPlanDraftV2, ManualPlanRevisionV2
from plane.curve.manual_plan_v2.validation import canonical_json
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.db.models import WorkspaceMember
from native_fixture import prepare_native_fixture, publish_catalog

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
GRAPH = (
    ManualPlanRevisionV2,
    ManualPlanDraftV2,
    PolicyDecision,
    AuditEvent,
    DomainEvent,
    OutboxEvent,
    IdempotencyRecord,
)


@pytest.fixture
def native(bridge, settings, tmp_path):
    return prepare_native_fixture(bridge, settings, tmp_path)


def counts():
    return tuple(model.objects.count() for model in GRAPH)


def command(native, *, revision=0, key="manual-save-1", version=None):
    payload = dict(
        schema_version="curve.manual-plan-draft.save/v2-candidate",
        policy_edition=contracts.POLICY_EDITION,
        expected_draft_revision=revision,
        **{
            name: native.manual_identity[name]
            for name in ("approved_subject_ref", "definition_ref", "manual_profile_ref")
        },
    )
    return contracts.parse_save(
        initiative_id=native.initiative.id,
        raw=canonical_json(payload),
        if_match=f'"curve-initiative:{native.initiative.id}:v{version or native.initiative.version}"',
        idempotency_key=key,
    )


def save(native, value):
    try:
        return services.save_manual_plan(request=native.request, workspace_slug=native.workspace.slug, command=value)
    except contracts.ManualPlanError as error:
        if error.__context__ is not None:
            pytest.fail("".join(traceback.format_exception(error.__context__)))
        raise


def read(native, action, revision_id=None):
    return reads.read_manual_plan(
        request=SimpleNamespace(user=native.user, query_params={}),
        workspace_slug=native.workspace.slug,
        initiative_id=native.initiative.id,
        action=action,
        revision_id=revision_id,
    )


def test_save_append_original_replay_and_history_commit_exact_graph(native):
    before = counts()
    original = command(native)
    assert read(native, "READ_STATUS").data["draft_status"] == "ABSENT"
    first = save(native, original)
    assert first.status_code == 201 and first.data["controlling"] is False
    assert tuple(after - old for after, old in zip(counts(), before)) == (1, 1, 1, 1, 1, 1, 1)
    native.initiative.refresh_from_db()
    assert native.initiative.version == original.expected_version + 1 == first.initiative_version
    assert read(native, "READ_CURRENT").data == first.data
    assert read(native, "READ_STATUS").data["draft_status"] == "CURRENT"
    second = save(native, command(native, revision=1, key="manual-save-2"))
    assert second.data["predecessor_id"] == first.data["id"]
    assert second.data["revision"] == 2
    before_replay = counts()
    replay = save(native, original)
    assert replay.replayed and replay.status_code == 200 and replay.data == first.data
    assert replay.initiative_version == second.initiative_version
    assert tuple(after - old for after, old in zip(counts(), before_replay)) == (0, 0, 1, 1, 0, 0, 0)
    assert read(native, "READ_CURRENT").data == second.data
    assert read(native, "READ_REVISION", first.data["id"]).data == first.data
    assert AuditEvent.objects.filter(action=contracts.ACTION, outcome="NO_EFFECT").count() == 1
    for decision in PolicyDecision.objects.filter(policy_key=contracts.POLICY_KEY):
        assert AuditEvent.objects.filter(policy_decision_ref__resource_id=str(decision.id)).count() == 1


def test_stale_new_command_rolls_back_every_record(native):
    original = command(native)
    save(native, original)
    before = counts()
    with pytest.raises(contracts.ManualPlanError, match="PRECONDITION_FAILED"):
        save(native, command(native, key="stale-new-key"))
    assert counts() == before


def test_revoked_original_object_denies_read_and_replay_but_not_minimal_status(native):
    original = command(native)
    saved = save(native, original)
    replacement = deepcopy(native.manual_catalog)
    replacement["generation"] += 1
    ref = native.manual_identity["definition_ref"]
    grant = replacement["objects"][ref["object_id"]]["grants"][1]
    grant["actions"], grant["acl_generation"] = [], grant["acl_generation"] + 1
    publish_catalog(native, replacement)
    before = counts()
    for action, revision_id in (("READ_CURRENT", None), ("READ_REVISION", saved.data["id"])):
        with pytest.raises(contracts.ManualPlanError):
            read(native, action, revision_id)
    with pytest.raises(contracts.ManualPlanError):
        save(native, original)
    assert counts() == before
    status = read(native, "READ_STATUS").data
    assert status["current_revision_id"] == saved.data["id"]
    assert "definition_ref" not in status and "original_input_identity" not in status


def test_authenticated_csrf_api_save_read_replay_and_strict_json(native, settings):
    value = command(native)
    endpoint = (
        f"/api/v1/workspaces/{native.workspace.slug}/curve/initiatives/{native.initiative.id}/manual-plan-drafts/v2/"
    )
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(native.user)
    headers = dict(
        HTTP_IF_MATCH=f'"curve-initiative:{native.initiative.id}:v{value.expected_version}"',
        HTTP_IDEMPOTENCY_KEY=value.key,
    )
    before = counts()
    denied = client.post(endpoint, value.canonical_payload, content_type="application/json", **headers)
    assert denied.status_code == 404 and denied["Cache-Control"] == "no-store"
    assert counts() == before
    token = "a" * 32
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    headers["HTTP_X_CSRFTOKEN"] = token
    invalid = client.post(
        endpoint, b'{"schema_version":1,"schema_version":2}', content_type="application/json", **headers
    )
    assert invalid.status_code == 422 and counts() == before
    created = client.post(endpoint, value.canonical_payload, content_type="application/json", **headers)
    assert created.status_code == 201, created.content
    assert created["Cache-Control"] == "no-store"
    assert "original_input_identity" not in created.json() and "validation_receipt" not in created.json()
    replay = client.post(endpoint, value.canonical_payload, content_type="application/json", **headers)
    assert replay.status_code == 200 and replay.json() == created.json()
    for path in (endpoint + "current/", created["Location"]):
        response = client.get(path)
        assert response.status_code == 200 and response.json() == created.json()
        assert response["ETag"] == created["ETag"] and response["Cache-Control"] == "no-store"
    assert client.get(endpoint + "status/").json()["draft_status"] == "CURRENT"
    current_counts = counts()
    assert client.post(endpoint, b" " * 65537, content_type="application/json", **headers).status_code == 413
    assert (
        client.post(
            endpoint + "?untrusted=1", value.canonical_payload, content_type="application/json", **headers
        ).status_code
        == 422
    )
    assert client.get(endpoint + "current/?untrusted=1").status_code == 404
    anonymous = APIClient(enforce_csrf_checks=True)
    assert anonymous.get(endpoint + "current/").status_code == 404
    assert (
        anonymous.post(endpoint, value.canonical_payload, content_type="application/json", **headers).status_code == 404
    )
    assert counts() == current_counts
    settings.CURVE_MANUAL_PLAN_DRAFT_V2_ENABLED = False
    assert client.get(endpoint + "current/").status_code == 404
    assert client.post(endpoint, value.canonical_payload, content_type="application/json", **headers).status_code == 404


@pytest.mark.parametrize(
    "table,operation",
    [
        ("curve_manual_plan_revision_v2", "UPDATE {table} SET version=version"),
        ("curve_manual_plan_revision_v2", "DELETE FROM {table}"),
        ("curve_manual_plan_revision_v2", "TRUNCATE {table} CASCADE"),
        ("curve_manual_plan_draft_v2", "DELETE FROM {table}"),
        ("curve_manual_plan_draft_v2", "TRUNCATE {table} CASCADE"),
        ("curve_manual_plan_draft_v2", "UPDATE {table} SET version=version+1"),
    ],
)
def test_retained_records_reject_direct_sql_mutations(native, table, operation):
    save(native, command(native))
    before = counts()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(operation.format(table=table))
    assert counts() == before


def capture_complete_sql_then_rollback(native, monkeypatch):
    """Observe a real valid graph, check all constraints, then deliberately roll it back."""
    writes = []
    before = counts()

    def observe(execute, sql, params, many, context):
        if sql.lstrip().upper().startswith(("INSERT ", "UPDATE ")):
            writes.append((sql, deepcopy(params)))
        return execute(sql, params, many, context)

    def probe_commit():
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        raise DatabaseError("Deliberate rollback of verified test graph")

    with monkeypatch.context() as patch, connection.execute_wrapper(observe):
        patch.setattr(connection, "commit", probe_commit)
        with pytest.raises(contracts.ManualPlanError) as error:
            services.save_manual_plan(
                request=native.request, workspace_slug=native.workspace.slug, command=command(native)
            )
        assert "Deliberate rollback" in str(error.value.__context__)
    assert counts() == before
    assert {sql.split('"')[1] for sql, _ in writes} == {
        "curve_manual_plan_revision_v2",
        "curve_manual_plan_draft_v2",
        "curve_initiative",
        "curve_policy_decision",
        "curve_audit_event",
        "curve_domain_event",
        "curve_outbox_event",
        "curve_idempotency_record",
    }
    return writes


def test_raw_sql_omission_and_substitution_of_every_graph_component_rolls_back(native, monkeypatch):
    writes = capture_complete_sql_then_rollback(native, monkeypatch)
    before = counts()
    old_version = native.initiative.version

    class TestRollback(Exception):
        pass

    # Positive control: captured SQL is a complete graph when executed directly.
    with pytest.raises(TestRollback), transaction.atomic(), connection.cursor() as cursor:
        for sql, params in writes:
            cursor.execute(sql, params)
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        raise TestRollback
    tables = {sql.split('"')[1] for sql, _ in writes}
    mutations = {
        "curve_manual_plan_revision_v2": ("input_identity_digest", "sha256:" + "0" * 64),
        "curve_manual_plan_draft_v2": ("product_id", uuid.uuid4()),
        "curve_initiative": ("version", old_version),
        "curve_policy_decision": ("resource_version", old_version + 1),
        "curve_audit_event": ("outcome", "FAILED"),
        "curve_domain_event": ("aggregate_id", uuid.uuid4()),
        "curve_outbox_event": ("destination", "OTHER"),
        "curve_idempotency_record": ("request_digest", "sha256:" + "0" * 64),
    }
    assert tables == mutations.keys()
    for target in sorted(tables):
        for mode in ("omit", "substitute"):
            changed = False
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                for sql, params in writes:
                    if sql.split('"')[1] == target:
                        if mode == "omit":
                            continue
                        field, value = mutations[target]
                        if sql.startswith("INSERT "):
                            columns = [
                                name.strip().strip('"') for name in sql.split("(", 1)[1].split(")", 1)[0].split(",")
                            ]
                        else:
                            columns = re.findall(r'"([^\"]+)" = %s', sql.split(" WHERE ", 1)[0])
                        if field in columns:
                            params = list(params)
                            params[columns.index(field)] = value
                            changed = True
                    cursor.execute(sql, params)
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            assert mode == "omit" or changed, (target, mode)
            assert counts() == before, (target, mode)
            native.initiative.refresh_from_db()
            assert native.initiative.version == old_version, (target, mode)


@pytest.mark.parametrize("same_key", [False, True])
def test_independent_connections_race_first_head_without_partial_graph(native, monkeypatch, same_key):
    barrier = Barrier(2, timeout=45)
    original = services.validate_in_worker

    def validate(captured):
        result = original(captured)
        barrier.wait()
        return result

    monkeypatch.setattr(services, "validate_in_worker", validate)
    commands = [command(native, key="same" if same_key else f"race-{index}") for index in range(2)]
    before = counts()

    def run(value):
        close_old_connections()
        try:
            result = services.save_manual_plan(
                request=native.request, workspace_slug=native.workspace.slug, command=value
            )
            return result.status_code, result.data["id"]
        except contracts.ManualPlanError as error:
            return error.status_code, error.code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, commands))
    assert sorted(status for status, _ in results) == ([200, 201] if same_key else [201, 412]), results
    if same_key:
        assert results[0][1] == results[1][1]
    assert tuple(after - old for after, old in zip(counts(), before)) == (
        1,
        1,
        2 if same_key else 1,
        2 if same_key else 1,
        1,
        1,
        1,
    )
    native.initiative.refresh_from_db()
    assert native.initiative.version == commands[0].expected_version + 1


@pytest.mark.parametrize("change", ["native", "file"])
def test_final_fence_change_rolls_back_entire_graph(native, monkeypatch, change):
    original = services.publish_new_revision
    before = counts()
    old_version = native.initiative.version

    def change_after_write(**kwargs):
        result = original(**kwargs)
        if change == "native":
            WorkspaceMember.objects.filter(workspace=native.workspace, member=native.reviewers[1]).update(
                is_active=False
            )
        else:
            path = native.manual_root / native.manual_identity["definition_ref"]["object_id"]
            path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(services, "publish_new_revision", change_after_write)
    with pytest.raises(contracts.ManualPlanError):
        services.save_manual_plan(request=native.request, workspace_slug=native.workspace.slug, command=command(native))
    assert counts() == before
    native.initiative.refresh_from_db()
    assert native.initiative.version == old_version
    assert WorkspaceMember.objects.get(workspace=native.workspace, member=native.reviewers[1]).is_active
