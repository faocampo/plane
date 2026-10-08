# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIClient

from plane.curve.models import AuditEvent, DomainEvent, IdempotencyRecord, OutboxEvent, PolicyDecision, Product
from plane.curve.models import ProjectAssociation
from plane.curve.project_association_guards import AssociationHasActiveBindings
from plane.curve.project_association_policy import POLICY_KEY
from plane.curve.project_association_services import associate_project
from plane.curve.project_association_views import CurveProjectAssociationAPIView
from plane.db.models import Project, ProjectMember, User, Workspace, WorkspaceMember
import plane.curve.project_association_services as services


pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
INSTALLATION = uuid.UUID("669f219d-87b8-48b8-aeb4-55eb0dca46be")


def client(user):
    value = APIClient()
    value.force_authenticate(user=user)
    return value


@pytest.fixture(autouse=True)
def configuration(settings):
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    settings.CURVE_ENABLED = True
    settings.CURVE_ENABLED_WORKSPACE_SLUGS = frozenset({"alpha", "beta"})
    settings.CURVE_ENVIRONMENT = "LOCAL"
    settings.CURVE_POLICY_RECORDER_ACTOR_ID = "association-contract-tests"
    settings.CURVE_PROJECT_ASSOCIATIONS_ENABLED = True
    settings.CURVE_LOCAL_PLANE_INSTALLATION_ID = str(INSTALLATION)


@pytest.fixture
def context():
    user = User.objects.create(email="association-admin@example.invalid", username="association-admin")
    workspace = Workspace.objects.create(name="Alpha", slug="alpha", owner=user)
    membership = WorkspaceMember.objects.create(workspace=workspace, member=user, is_active=True, role=20)
    project = Project.objects.create(workspace=workspace, name="Private source name", identifier="PRIV", network=0)
    project_membership = ProjectMember.objects.create(workspace=workspace, project=project, member=user, is_active=True)
    actor = {"actor_type": "HUMAN", "actor_id": str(user.id)}
    product = Product.objects.create(
        workspace_id=workspace.id,
        key="product",
        name="Product",
        timezone="UTC",
        owner_user_id=user.id,
        created_by=actor,
        updated_by=actor,
    )
    return SimpleNamespace(
        user=user,
        workspace=workspace,
        membership=membership,
        project=project,
        project_membership=project_membership,
        product=product,
    )


def create(context, *, key="associate-1", payload=None, version=1, user=None, product=None, headers=None):
    product = product or context.product
    values = {"HTTP_IDEMPOTENCY_KEY": key}
    if version is not None:
        values["HTTP_IF_MATCH"] = f'"curve-product:{product.id}:v{version}"'
    values.update(headers or {})
    return client(user or context.user).post(
        f"/api/v1/workspaces/alpha/curve/products/{product.id}/project-associations/",
        payload
        if payload is not None
        else {"provider_installation_id": str(INSTALLATION), "source_project_id": str(context.project.id)},
        format="json",
        **values,
    )


def end(context, association_id, *, version=1, payload=None, key="end-1"):
    values = {"HTTP_IDEMPOTENCY_KEY": key}
    if version is not None:
        values["HTTP_IF_MATCH"] = f'"curve-project-association:{association_id}:v{version}"'
    return client(context.user).post(
        f"/api/v1/workspaces/alpha/curve/project-associations/{association_id}/end/",
        payload if payload is not None else {"expected_product_version": 1, "reason": "Reconciled scope"},
        format="json",
        **values,
    )


def detail(context, association_id):
    return client(context.user).get(f"/api/v1/workspaces/alpha/curve/project-associations/{association_id}/")


def assert_one_audit_per_decision():
    for decision in PolicyDecision.objects.filter(policy_key=POLICY_KEY):
        assert AuditEvent.objects.filter(policy_decision_ref__resource_id=str(decision.id)).count() == 1


def test_create_replay_atomicity_safe_projection_and_receipts(context):
    source_before = Project.objects.filter(id=context.project.id).values().get()
    created, replay = create(context), create(context)
    assert created.status_code == replay.status_code == 201
    assert created.json() == replay.json()
    data = created.json()
    assert created["ETag"] == f'"curve-project-association:{data["id"]}:v1"'
    assert created["Cache-Control"] == "no-store"
    assert "Private source name" not in created.content.decode()
    assert "association-admin" not in created.content.decode()
    assert Project.objects.filter(id=context.project.id).values().get() == source_before
    context.product.refresh_from_db()
    assert context.product.version == 1
    assert ProjectAssociation.objects.count() == DomainEvent.objects.count() == OutboxEvent.objects.count() == 1
    assert IdempotencyRecord.objects.count() == 1
    event = DomainEvent.objects.get(id=data["command_receipt_id"])
    assert event.payload["association"] == data
    assert OutboxEvent.objects.get().event_id == event.id
    assert_one_audit_per_decision()
    assert detail(context, data["id"]).json() == data
    directory = Path(__file__).parents[1] / "project_association_candidate"
    schemas = [json.loads(path.read_text()) for path in directory.glob("*.schema.json")]
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    for name, value in [
        ("project-association-v1.schema.json", data),
        ("project-association-event-v1.schema.json", event.payload),
    ]:
        schema = json.loads((directory / name).read_text())
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)


@pytest.mark.parametrize(
    "setting,value",
    [
        ("CURVE_PROJECT_ASSOCIATIONS_ENABLED", False),
        ("CURVE_PROJECT_ASSOCIATIONS_ENABLED", "true"),
        ("CURVE_ENVIRONMENT", "PRODUCTION"),
        ("CURVE_ENABLED", False),
        ("CURVE_LOCAL_PLANE_INSTALLATION_ID", None),
        ("CURVE_LOCAL_PLANE_INSTALLATION_ID", str(uuid.uuid4())),
    ],
)
def test_candidate_gate_fails_closed(context, settings, setting, value):
    setattr(settings, setting, value)
    assert create(context).status_code == 404
    assert ProjectAssociation.objects.count() == 0


@pytest.mark.parametrize(
    "table,changes",
    [
        ("membership", {"role": 15}),
        ("membership", {"is_active": False}),
        ("membership", {"deleted_at": timezone.now()}),
        ("project_membership", {"is_active": False}),
        ("project_membership", {"deleted_at": timezone.now()}),
        ("project", {"deleted_at": timezone.now()}),
        ("user", {"is_active": False}),
        ("user", {"is_bot": True}),
    ],
)
def test_fresh_database_authority_overrides_stale_authenticated_object(context, table, changes):
    record = getattr(context, table)
    type(record).objects.filter(id=record.id).update(**changes)
    response = create(context, headers={"HTTP_X_ROLE": "ADMIN", "HTTP_X_PROJECT_ACCESS": "ALLOW"})
    assert response.status_code == 404
    assert ProjectAssociation.objects.count() == 0
    assert "Private source name" not in response.content.decode()


def test_admin_needs_exact_project_membership_even_public(context):
    Project.objects.filter(id=context.project.id).update(network=2)
    ProjectMember.objects.filter(id=context.project_membership.id).update(is_active=False)
    assert create(context).status_code == 404


@pytest.mark.parametrize("changed_field", ["provider_installation_id", "source_project_id"])
def test_cross_installation_or_unknown_source_is_redacted(context, changed_field):
    payload = {"provider_installation_id": str(INSTALLATION), "source_project_id": str(context.project.id)}
    payload[changed_field] = str(uuid.uuid4())
    response = create(context, payload=payload)
    assert response.status_code == 404
    assert response.json()["title"] == "The Curve resource is unavailable"


def test_cross_workspace_project_and_product_rejected(context):
    beta = Workspace.objects.create(name="Beta", slug="beta", owner=context.user)
    project = Project.objects.create(workspace=beta, name="Beta source", identifier="BETA")
    ProjectMember.objects.create(workspace=beta, project=project, member=context.user)
    assert (
        create(
            context, payload={"provider_installation_id": str(INSTALLATION), "source_project_id": str(project.id)}
        ).status_code
        == 404
    )
    context.product.workspace_id = beta.id
    # Product identity itself is guarded; create a different Product instead.
    product = Product.objects.create(
        workspace_id=beta.id,
        key="beta",
        name="Beta",
        timezone="UTC",
        owner_user_id=context.user.id,
        created_by={},
        updated_by={},
    )
    assert create(context, product=product).status_code == 404


def test_missing_and_stale_versions(context):
    assert create(context, version=None).status_code == 428
    assert create(context, version=2).status_code == 412
    assert create(context, headers={"HTTP_IF_MATCH": f'"curve-product:{uuid.uuid4()}:v1"'}).status_code == 412
    result = create(context)
    association_id = result.json()["id"]
    assert end(context, association_id, version=None).status_code == 428
    assert end(context, association_id, payload={"reason": "Done"}).status_code == 428
    assert end(context, association_id, version=2).status_code == 412
    assert end(context, association_id, payload={"expected_product_version": 2, "reason": "Done"}).status_code == 412
    assert end(context, association_id, payload={"expected_product_version": True, "reason": "Done"}).status_code == 422


@pytest.mark.parametrize(
    "extra",
    ["role", "actor", "policy_decision", "effective_at", "provider_capability", "created_by", "state", "version"],
)
def test_caller_authority_and_state_fields_are_closed(context, extra):
    payload = {
        "provider_installation_id": str(INSTALLATION),
        "source_project_id": str(context.project.id),
        extra: "ALLOW",
    }
    assert create(context, payload=payload).status_code == 422
    assert ProjectAssociation.objects.count() == 0


def test_idempotency_conflict_and_missing_key(context):
    assert create(context, key="").status_code == 422
    assert create(context).status_code == 201
    assert create(context, version=2).status_code == 409
    assert ProjectAssociation.objects.count() == 1
    assert_one_audit_per_decision()


def test_conflict_product_many_and_archival_preconditions(context):
    assert create(context).status_code == 201
    assert create(context, key="other").status_code == 409
    product = Product.objects.create(
        workspace_id=context.workspace.id,
        key="other",
        name="Other",
        timezone="UTC",
        owner_user_id=context.user.id,
        created_by={},
        updated_by={},
    )
    assert create(context, product=product, key="other-product").status_code == 409
    second = Project.objects.create(workspace=context.workspace, name="Second", identifier="SECOND")
    ProjectMember.objects.create(workspace=context.workspace, project=second, member=context.user)
    context.project = second
    assert create(context, key="second").status_code == 201
    assert ProjectAssociation.objects.filter(product_id=context.product.id).count() == 2


@pytest.mark.parametrize("archived", ["project", "product"])
def test_archived_source_or_product_blocks_new_association(context, archived):
    if archived == "project":
        Project.objects.filter(id=context.project.id).update(archived_at=timezone.now())
    else:
        context.product.state = "ARCHIVED"
        context.product.archived_at = timezone.now()
        context.product.archived_by = {"actor_type": "HUMAN", "actor_id": str(context.user.id)}
        context.product.save()
    assert create(context).status_code == 409
    assert ProjectAssociation.objects.count() == 0


def test_end_guard_unavailable_preserves_all_state(context):
    created = create(context).json()
    response = end(context, created["id"])
    assert response.status_code == 503
    assert detail(context, created["id"]).json() == created
    assert DomainEvent.objects.count() == OutboxEvent.objects.count() == IdempotencyRecord.objects.count() == 1
    assert_one_audit_per_decision()


def test_end_guard_active_dependencies_blocks(context, monkeypatch):
    created = create(context).json()

    def blocked(**kwargs):
        raise AssociationHasActiveBindings

    monkeypatch.setattr(services, "assert_association_can_end", blocked)
    assert end(context, created["id"]).status_code == 409
    assert ProjectAssociation.objects.get().state == "ACTIVE"


def test_qualified_synthetic_guard_end_replay_and_reassociate(context, monkeypatch):
    # This is an explicit test double, never a configurable production bypass.
    monkeypatch.setattr(services, "assert_association_can_end", lambda **kwargs: None)
    original = create(context).json()
    ended = end(context, original["id"])
    replay = end(context, original["id"])
    assert ended.status_code == replay.status_code == 200
    assert ended.json() == replay.json()
    assert ended.json()["state"] == "ENDED" and ended.json()["version"] == 2
    assert create(context).json() == original  # Exact original version, not the ended aggregate.
    reassociated = create(context, key="associate-2")
    assert reassociated.status_code == 201
    assert reassociated.json()["id"] != original["id"]
    assert ProjectAssociation.objects.filter(state="ACTIVE").count() == 1
    assert DomainEvent.objects.count() == OutboxEvent.objects.count() == 3
    assert_one_audit_per_decision()


def test_archived_product_still_allows_reconciliation_with_qualified_guard(context, monkeypatch):
    created = create(context).json()
    context.product.state = "ARCHIVED"
    context.product.archived_at = timezone.now()
    context.product.archived_by = {}
    context.product.version = 2
    context.product.save()
    monkeypatch.setattr(services, "assert_association_can_end", lambda **kwargs: None)
    assert (
        end(context, created["id"], payload={"expected_product_version": 2, "reason": "Reconciled"}).status_code == 200
    )


@pytest.mark.parametrize("revocation", ["project_membership", "membership", "user", "installation"])
def test_replay_requires_current_visibility(context, settings, revocation):
    created = create(context).json()
    if revocation == "installation":
        settings.CURVE_LOCAL_PLANE_INSTALLATION_ID = str(uuid.uuid4())
    else:
        record = getattr(context, revocation)
        type(record).objects.filter(id=record.id).update(is_active=False)
    assert create(context).status_code == 404
    assert detail(context, created["id"]).status_code == 404
    assert DomainEvent.objects.count() == 1


def test_revocation_between_policy_read_and_commit_rolls_back(context, monkeypatch):
    original = services._complete

    def revoke_after_write(**kwargs):
        result = original(**kwargs)
        ProjectMember.objects.filter(id=context.project_membership.id).update(is_active=False)
        return result

    monkeypatch.setattr(services, "_complete", revoke_after_write)
    assert create(context).status_code == 404
    assert ProjectAssociation.objects.count() == DomainEvent.objects.count() == OutboxEvent.objects.count() == 0
    assert IdempotencyRecord.objects.count() == 0
    assert_one_audit_per_decision()
    assert AuditEvent.objects.get().outcome == "NO_EFFECT"


def test_outbox_failure_rolls_back_aggregate_event_and_idempotency(context, monkeypatch):
    def unavailable(**kwargs):
        raise IntegrityError("synthetic private source failure")

    monkeypatch.setattr(OutboxEvent.objects, "create", unavailable)
    response = create(context)
    assert response.status_code == 409
    assert "synthetic" not in response.content.decode()
    assert ProjectAssociation.objects.count() == DomainEvent.objects.count() == OutboxEvent.objects.count() == 0
    assert IdempotencyRecord.objects.count() == 0
    assert_one_audit_per_decision()


def test_audit_failure_rolls_back_everything(context, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(services, "append_association_audit", unavailable)
    response = create(context)
    assert response.status_code == 500
    assert "audit unavailable" not in response.content.decode()
    assert ProjectAssociation.objects.count() == DomainEvent.objects.count() == OutboxEvent.objects.count() == 0
    assert PolicyDecision.objects.count() == IdempotencyRecord.objects.count() == 0


def test_direct_model_creation_and_changes_need_live_exact_receipt(context):
    with pytest.raises(PermissionError):
        ProjectAssociation.objects.create(
            workspace_id=context.workspace.id,
            product_id=context.product.id,
            provider_installation_id=INSTALLATION,
            source_project_id=context.project.id,
            initiated_by=context.user.id,
            command_receipt_id=uuid.uuid4(),
            source_version="v1",
        )
    create(context)
    association = ProjectAssociation.objects.get()
    association.state = "ENDED"
    with pytest.raises(PermissionError):
        association.save()


def test_concurrent_association_commands_commit_only_one(context):
    def run(key):
        close_old_connections()
        try:
            return create(context, key=key).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(run, ["race-1", "race-2"]))
    assert sorted(statuses) == [201, 409]
    assert ProjectAssociation.objects.count() == DomainEvent.objects.count() == OutboxEvent.objects.count() == 1
    assert_one_audit_per_decision()


def test_database_identity_uniqueness_and_deletion_guards(context):
    created = create(context).json()
    statements = [
        (
            "UPDATE curve_project_association SET product_id = %s, version = version + 1 WHERE id = %s",
            [uuid.uuid4(), created["id"]],
        ),
        ("UPDATE curve_project_association SET version = 99 WHERE id = %s", [created["id"]]),
        ("DELETE FROM curve_project_association WHERE id = %s", [created["id"]]),
        (
            "INSERT INTO curve_project_association SELECT %s, workspace_id, provider_installation_id, "
            "source_project_id, product_id, state, version, effective_at, initiated_by, policy_edition, "
            "command_receipt_id, source_observed_at, source_version, ended_at, ended_by, end_reason, "
            "end_receipt_id FROM curve_project_association WHERE id = %s",
            [uuid.uuid4(), created["id"]],
        ),
    ]
    for query, parameters in statements:
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(query, parameters)
    assert ProjectAssociation.objects.count() == 1


def test_session_only_and_regular_member_read_visibility(context):
    assert CurveProjectAssociationAPIView.authentication_classes == [SessionAuthentication]
    created = create(context).json()
    WorkspaceMember.objects.filter(id=context.membership.id).update(role=15)
    assert detail(context, created["id"]).status_code == 200
    assert end(context, created["id"]).status_code == 404


def test_service_expected_versions_cannot_be_bool(context):
    with pytest.raises(services.AssociationValidationError):
        associate_project(
            request=SimpleNamespace(user=context.user),
            workspace_slug="alpha",
            product_id=context.product.id,
            payload={"provider_installation_id": str(INSTALLATION), "source_project_id": str(context.project.id)},
            expected_version=True,
            raw_idempotency_key="key",
        )


@pytest.mark.parametrize("version", [9007199254740992, 10**100])
def test_excessive_etag_and_product_versions_fail_closed(context, version):
    assert create(context, version=version).status_code == 412
    created = create(context).json()
    assert (
        end(context, created["id"], payload={"expected_product_version": version, "reason": "Done"}).status_code == 422
    )


def test_uuid_wire_spelling_matches_closed_schema(context):
    payload = {"provider_installation_id": str(INSTALLATION).upper(), "source_project_id": str(context.project.id)}
    assert create(context, payload=payload).status_code == 422
    payload["provider_installation_id"] = INSTALLATION.hex
    assert create(context, payload=payload).status_code == 422


def test_reverse_migration_refuses_retained_association_evidence(context):
    from importlib import import_module

    migration = import_module("plane.curve.migrations.0020_project_association")
    created = create(context).json()
    with (
        pytest.raises(IntegrityError, match="preservation migration"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(migration.REVERSE_GUARDS)
    assert ProjectAssociation.objects.get().id == uuid.UUID(created["id"])
    assert DomainEvent.objects.count() == AuditEvent.objects.count() == PolicyDecision.objects.count() == 1


def test_database_tenant_source_and_terminal_state_guards(context, monkeypatch):
    created = create(context).json()
    beta = Workspace.objects.create(name="Beta", slug="beta", owner=context.user)
    association = ProjectAssociation.objects.get()
    # Direct SQL bypasses the Python receipt guard but cannot bypass tenant/source identity.
    for changes in ({"workspace_id": beta.id}, {"source_project_id": uuid.uuid4()}, {"version": 2}):
        values = {field.column: getattr(association, field.attname) for field in association._meta.fields}
        values["id"] = uuid.uuid4()
        values.update(changes)
        columns = ", ".join(values)
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO curve_project_association ({columns}) VALUES ({', '.join(['%s'] * len(values))})",
                list(values.values()),
            )
    monkeypatch.setattr(services, "assert_association_can_end", lambda **kwargs: None)
    assert end(context, created["id"]).status_code == 200
    for query in [
        "UPDATE curve_project_association SET state='ACTIVE', version=3, ended_at=NULL, ended_by=NULL, "
        "end_reason=NULL, end_receipt_id=NULL WHERE id=%s",
        "UPDATE curve_project_association SET end_reason='rewritten', version=3 WHERE id=%s",
    ]:
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(query, [created["id"]])


def test_current_membership_row_is_locked_until_command_commit(context, monkeypatch):
    import threading
    import time

    locked = threading.Event()
    updater_ready = threading.Event()
    backend = {}
    original = services._complete

    def observed_completion(**kwargs):
        result = original(**kwargs)
        locked.set()
        assert updater_ready.wait(10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [backend["pid"]])
                if cursor.fetchone()[0]:
                    return result
            time.sleep(0.01)
        pytest.fail("Current project membership update was not blocked by the command's transaction fence")

    def revoke():
        close_old_connections()
        try:
            assert locked.wait(10)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend["pid"] = cursor.fetchone()[0]
            updater_ready.set()
            ProjectMember.objects.filter(id=context.project_membership.id).update(is_active=False)
        finally:
            close_old_connections()

    monkeypatch.setattr(services, "_complete", observed_completion)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(revoke)
        assert create(context).status_code == 201
        future.result(timeout=15)
    assert create(context).status_code == 404
    assert ProjectAssociation.objects.count() == 1


def test_actual_session_read_and_csrf_protected_command(context):
    created = create(context).json()
    session_client = APIClient(enforce_csrf_checks=True)
    session_client.force_login(context.user)
    assert (
        session_client.get(f"/api/v1/workspaces/alpha/curve/project-associations/{created['id']}/").status_code == 200
    )
    rejected = session_client.post(
        f"/api/v1/workspaces/alpha/curve/project-associations/{created['id']}/end/",
        {"expected_product_version": 1, "reason": "Done"},
        format="json",
        HTTP_IF_MATCH=f'"curve-project-association:{created["id"]}:v1"',
        HTTP_IDEMPOTENCY_KEY="csrf-1",
    )
    assert rejected.status_code == 403
    assert ProjectAssociation.objects.get().state == "ACTIVE"


def test_reverse_migration_also_preserves_denied_policy_evidence(context):
    from importlib import import_module

    migration = import_module("plane.curve.migrations.0020_project_association")
    WorkspaceMember.objects.filter(id=context.membership.id).update(role=15)
    assert create(context).status_code == 404
    assert ProjectAssociation.objects.count() == 0
    with (
        pytest.raises(IntegrityError, match="preservation migration"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(migration.REVERSE_GUARDS)
    assert AuditEvent.objects.count() == PolicyDecision.objects.count() == 1


def test_creation_attribution_is_bound_to_current_human(context, monkeypatch):
    original = ProjectAssociation.save

    def spoof_actor(self, *args, **kwargs):
        self.initiated_by = uuid.uuid4()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ProjectAssociation, "save", spoof_actor)
    assert create(context).status_code == 500
    assert ProjectAssociation.objects.count() == DomainEvent.objects.count() == IdempotencyRecord.objects.count() == 0
    assert PolicyDecision.objects.count() == 0
