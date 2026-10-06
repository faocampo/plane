"""Independent connections, real sessions, raw SQL graphs and retained-evidence gates."""

# ruff: noqa: F401,F811
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from importlib import import_module
import re
import uuid
import pytest
from django.db import connection, transaction, DatabaseError, close_old_connections, connections
from django.db.migrations.executor import MigrationExecutor
from rest_framework.test import APIClient
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.curve.manual_gate2_v2 import contracts, services, reads
from plane.curve.manual_gate2_v2.models import (
    ManualGate2ControlV2,
    ManualGate2RecordV2,
    ManualTaskClaimV2,
    ManualTaskClaimHistoryV2,
)
from plane.curve.tests.manual_plan_v2.test_manual_persistence import save as save_draft, command as draft_command
from plane.curve.tests.manual_plan_v2.native_fixture import publish_catalog
from plane.curve.manual_plan_v2.validation import canonical_json
from .test_gate2 import native, command, execute, approve, counts

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_real_csrf_sessions_strict_json_material_access_and_default_off(native, settings):
    n = native
    c = APIClient(enforce_csrf_checks=True)
    c.force_login(n.user)
    root = f"/api/v1/workspaces/{n.workspace.slug}/curve/initiatives/{n.initiative.id}/manual-gate2/v2/"
    value = command(n, "PREPARE")
    headers = dict(
        HTTP_IF_MATCH=f'"curve-initiative:{n.initiative.id}:v{value.expected_version}"', HTTP_IDEMPOTENCY_KEY=value.key
    )
    before = counts()
    assert (
        c.post(
            root + "commands/", canonical_json(value.payload), content_type="application/json", **headers
        ).status_code
        == 404
    )
    assert counts() == before
    token = "a" * 32
    c.cookies[settings.CSRF_COOKIE_NAME] = token
    headers["HTTP_X_CSRFTOKEN"] = token
    assert (
        c.post(root + "commands/", b'{"action":1,"action":2}', content_type="application/json", **headers).status_code
        == 422
    )
    assert c.post(root + "commands/", b"x" * 65537, content_type="application/json", **headers).status_code == 413
    created = c.post(root + "commands/", canonical_json(value.payload), content_type="application/json", **headers)
    assert created.status_code == 201, created.content
    assert (
        c.post(
            root + "commands/", canonical_json(value.payload), content_type="application/json", **headers
        ).status_code
        == 200
    )
    status = c.get(root + "status/")
    assert status.status_code == 200, status.content
    assert status["Cache-Control"] == "no-store" and "subject_metadata" not in status.json()["current_record"]
    body = c.get(root + "materials/" + n.manual_identity["definition_ref"]["object_id"] + "/")
    assert body.status_code == 200 and body.json()["content"].encode() == n.manual_definition
    assert c.get(root + "materials/" + str(uuid.uuid4()) + "/").status_code == 404
    anonymous = APIClient(enforce_csrf_checks=True)
    assert anonymous.get(root + "status/").status_code == 404
    settings.CURVE_MANUAL_GATE2_V2_ENABLED = False
    assert c.get(root + "status/").status_code == 404
    assert c.get(root + "preparation/").status_code == 404
    assert (
        c.post(
            root + "commands/", canonical_json(value.payload), content_type="application/json", **headers
        ).status_code
        == 404
    )


@pytest.mark.parametrize("same_key", [False, True])
def test_two_connections_approve_once_and_retry_without_second_claim(native, monkeypatch, same_key):
    n = native
    subject = execute(n, command(n, "PREPARE")).data
    barrier = Barrier(2, timeout=45)
    original = services.validate_in_worker

    def validated(captured):
        result = original(captured)
        barrier.wait()
        return result

    monkeypatch.setattr(services, "validate_in_worker", validated)
    commands = [command(n, "APPROVE", subject=subject, key="same" if same_key else "race-" + str(i)) for i in range(2)]

    def run(value):
        close_old_connections()
        try:
            r = services.execute(request=SimpleNamespace(user=n.reviewers[1]), slug=n.workspace.slug, command=value)
            return r.status_code, r.data["id"]
        except contracts.Gate2Error as e:
            return e.status, e.code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, commands))
    assert sorted(x[0] for x in results) == ([200, 201] if same_key else [201, 412]), results
    assert ManualTaskClaimV2.objects.count() == ManualTaskClaimHistoryV2.objects.count() == 1
    assert ManualTaskClaimV2.objects.get().generation == 1
    if same_key:
        assert results[0][1] == results[1][1]


def test_complete_sql_graph_positive_and_component_omission_substitution(native, monkeypatch):
    n = native
    subject = execute(n, command(n, "PREPARE")).data
    value = command(n, "APPROVE", subject=subject)
    writes = []
    before = counts()

    def observe(run, sql, params, many, context):
        if sql.lstrip().upper().startswith(("INSERT ", "UPDATE ")):
            writes.append((sql, deepcopy(params)))
        return run(sql, params, many, context)

    def rollback():
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        raise DatabaseError("Deliberate rollback of valid Gate2 graph")

    with monkeypatch.context() as patch, connection.execute_wrapper(observe):
        patch.setattr(connection, "commit", rollback)
        with pytest.raises(contracts.Gate2Error) as error:
            services.execute(request=SimpleNamespace(user=n.reviewers[1]), slug=n.workspace.slug, command=value)
        assert "Deliberate rollback" in str(error.value.__context__)
    assert counts() == before

    class Rollback(Exception):
        pass

    with pytest.raises(Rollback), transaction.atomic(), connection.cursor() as c:
        for sql, params in writes:
            c.execute(sql, params)
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        raise Rollback
    mutations = {
        "curve_manual_gate2_record_v2": ("subject_digest", "sha256:" + "0" * 64),
        "curve_manual_gate2_control_v2": ("product_id", uuid.uuid4()),
        "curve_manual_task_claim_v2": ("generation", 2),
        "curve_manual_task_claim_history_v2": ("generation", 2),
        "curve_initiative": ("version", value.expected_version),
        "curve_policy_decision": ("resource_version", value.expected_version + 1),
        "curve_audit_event": ("outcome", "FAILED"),
        "curve_domain_event": ("aggregate_id", uuid.uuid4()),
        "curve_outbox_event": ("destination", "OTHER"),
        "curve_idempotency_record": ("request_digest", "sha256:" + "0" * 64),
    }
    assert {s.split('"')[1] for s, _ in writes} == mutations.keys()
    for target, (field, replacement) in mutations.items():
        for mode in ("omit", "substitute"):
            changed = False
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as c:
                for sql, params in writes:
                    if sql.split('"')[1] == target:
                        if mode == "omit":
                            continue
                        columns = (
                            [x.strip().strip('"') for x in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
                            if sql.startswith("INSERT ")
                            else re.findall(r'"([^\"]+)" = %s', sql.split(" WHERE ", 1)[0])
                        )
                        if field in columns:
                            params = list(params)
                            params[columns.index(field)] = replacement
                            changed = True
                    c.execute(sql, params)
                c.execute("SET CONSTRAINTS ALL IMMEDIATE")
            assert mode == "omit" or changed, (target, mode)
            assert counts() == before, (target, mode)


def test_retained_history_and_claim_identity_reject_raw_writes(native):
    n = native
    approve(n)
    before = counts()
    attacks = [
        "UPDATE curve_manual_task_claim_v2 SET state='RELEASED'",
        "UPDATE curve_manual_task_claim_v2 SET issue_id='" + str(uuid.uuid4()) + "'",
        "UPDATE curve_manual_gate2_record_v2 SET version=version",
        "UPDATE curve_manual_task_claim_history_v2 SET generation=generation",
        "DELETE FROM curve_manual_gate2_control_v2",
        "DELETE FROM curve_manual_task_claim_v2",
        "TRUNCATE curve_manual_gate2_record_v2 CASCADE",
        "TRUNCATE curve_manual_task_claim_history_v2 CASCADE",
    ]
    for sql in attacks:
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as c:
            c.execute(sql)
        assert counts() == before


@pytest.mark.parametrize("state", ["PAUSED", "CANCELLED"])
def test_pause_cancel_retain_claim_until_reconciled_release(native, state):
    n = native
    subject, _, approved = approve(n)
    n.initiative.refresh_from_db()
    n.initiative.state = state
    n.initiative.paused_from_state = "PLANNING" if state == "PAUSED" else None
    n.initiative.version += 1
    n.initiative.save(update_fields=["state", "paused_from_state", "version", "updated_at"])
    assert ManualTaskClaimV2.objects.get().state == "ACTIVE"
    status = reads.status(
        request=SimpleNamespace(user=n.reviewers[1], query_params={}),
        slug=n.workspace.slug,
        initiative_id=n.initiative.id,
    )
    assert status.data["effective_hold"] == state
    reconciled = execute(n, command(n, "RECONCILE", subject=subject, claims=approved["claims"])).data
    execute(n, command(n, "RELEASE", subject=subject, claims=approved["claims"], reconciliation=reconciled))
    assert ManualTaskClaimV2.objects.get().state == "RELEASED"
    n.initiative.refresh_from_db()
    assert n.initiative.state == state


def test_started_work_and_wrong_generation_cannot_release(native):
    from plane.db.models import State

    n = native
    subject, _, approved = approve(n)
    wrong = deepcopy(approved["claims"])
    wrong[0]["generation"] += 1
    before = counts()
    with pytest.raises(contracts.Gate2Error):
        execute(n, command(n, "RECONCILE", subject=subject, claims=wrong))
    assert counts() == before
    started = State.objects.create(
        workspace=n.workspace, project=n.project, name="In progress", color="#000000", group="started"
    )
    n.issue.state = started
    n.issue.save()
    with pytest.raises(contracts.Gate2Error, match="UNRESOLVED_WORK"):
        execute(n, command(n, "RECONCILE", subject=subject, claims=approved["claims"]))
    assert counts() == before and ManualTaskClaimV2.objects.get().state == "ACTIVE"


def test_postapproval_draft_and_preplan_context_cannot_be_reopened(native):
    from plane.curve.manual_plan_v2.contracts import ManualPlanError

    n = native
    approve(n)
    n.initiative.refresh_from_db()
    before = counts()
    with pytest.raises(ManualPlanError):
        from plane.curve.manual_plan_v2.services import save_manual_plan

        save_manual_plan(
            request=n.request,
            workspace_slug=n.workspace.slug,
            command=draft_command(n, revision=1, key="after-approval"),
        )
    assert counts() == before
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as c:
        c.execute("UPDATE curve_initiative SET risk_tier='HIGH' WHERE id=%s", [n.initiative.id])
    assert counts() == before


def test_complete_migration_empty_reverse_forward_and_retained_refusal():
    from plane.curve.scope_reopening_qualification import require_manual_gate2_v2_qualification

    m = import_module("plane.curve.migrations.0025_manual_gate2_reconstruction")
    with transaction.atomic(), connection.cursor() as c:
        assert m._catalog(c) == m.CURRENT_CATALOG_DIGEST
    try:
        MigrationExecutor(connection).migrate([("curve", "0024_manual_draft_reconstruction")])
        with transaction.atomic(), connection.cursor() as c:
            assert m._catalog(c) == m.BASELINE_CATALOG_DIGEST
    finally:
        MigrationExecutor(connection).migrate([("curve", "0025_manual_gate2_reconstruction")])
    with transaction.atomic():
        require_manual_gate2_v2_qualification()


def test_complete_reverse_refuses_retained_manual_approval(native):
    n = native
    approve(n)
    before = counts()
    with pytest.raises(RuntimeError, match="RETAINED_EVIDENCE_PREVENTS_REVERSE"):
        MigrationExecutor(connection).migrate([("curve", "0024_manual_draft_reconstruction")])
    assert counts() == before and ManualTaskClaimV2.objects.get().state == "ACTIVE"
