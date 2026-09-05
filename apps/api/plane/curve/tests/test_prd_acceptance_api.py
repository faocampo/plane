# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
import hashlib
import json
import uuid

import pytest
from django.db import transaction
from django.middleware.csrf import _get_new_csrf_string
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from plane.curve.models import Operation, OutboxEvent, PrdAcceptedCommand, PolicyDecision
from plane.curve.prd_acceptance import PrdAcceptancePreparation, accept_prd_command
from plane.curve.tests.test_prd_accepted_commands import fixture  # noqa: F401
from plane.curve.tests.test_prd_policy_context import resolver
from plane.curve.tests.test_prd_lifecycle_repository import raw_update
from plane.db.models import WorkspaceMember


pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]


class SyntheticRuntime:
    resolve_acl = staticmethod(resolver)

    def __init__(self):
        self.calls = 0
        self.committed = []
        self.on_prepare = None
        self.on_revalidate = None

    @contextmanager
    def prepare(self, *, scope, command):
        assert not transaction.get_connection().in_atomic_block
        self.calls += 1
        now = timezone.now()
        prepared = PrdAcceptancePreparation(
            scope=scope,
            valid_from=now,
            valid_until=now + timedelta(minutes=1),
            checks={
                key: True
                for key in (
                    "provider_capability",
                    "storage_policy",
                    "source_access",
                    "evidence_access",
                    "readiness",
                    "worker_ready",
                )
            },
        )
        if command.rationale_bytes:
            prepared.rationale_ref = dict(
                object_id=str(uuid.uuid4()),
                digest="sha256:" + hashlib.sha256(command.rationale_bytes).hexdigest(),
                size_bytes=len(command.rationale_bytes),
                media_type="text/plain; charset=utf-8",
            )
            prepared.access_envelope_id = uuid.uuid4()
            prepared.retention_policy_version_id = uuid.uuid4()
        try:
            if self.on_prepare:
                self.on_prepare(prepared, command)
            yield prepared
        finally:
            self.committed.append(prepared.committed_operation_id)

    def revalidate(self, prepared):
        assert transaction.get_connection().in_atomic_block
        return self.on_revalidate(prepared) if self.on_revalidate else True


@pytest.fixture
def setup(fixture, settings):  # noqa: F811 - imported pytest fixture
    settings.ROOT_URLCONF = "plane.curve.tests.urls"
    runtime = SyntheticRuntime()
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = runtime
    client = APIClient()
    client.force_authenticate(user=fixture[4])
    return fixture, runtime, client


def post(setup, action="approve", *, body=None, key="synthetic-idempotency-key", version=None, client=None):
    records, _, default_client = setup
    binding, initiative, checkpoint, gate, _, workspace = records
    if body is None:
        if action == "submit":
            body = dict(
                external_document_binding_id=str(binding.id),
                evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
                completeness_check_id=str(uuid.uuid4()),
            )
        else:
            body = dict(
                gate_assignment_id=str(gate.id),
                checkpoint_id=str(checkpoint.id),
                artifact_version_id=str(checkpoint.artifact_version_id),
                content_digest=checkpoint.content_digest,
                provider_version=checkpoint.provider_version,
                evidence_snapshot_id=str(checkpoint.evidence_snapshot_id),
                confirmed_risk_tier=initiative.risk_tier,
                rationale="Synthetic sensitive rationale sentinel",
            )
            if action == "return-for-revision":
                body["decision"] = "CHANGES_REQUESTED"
    url = reverse(f"curve-prd-{action}", kwargs={"slug": workspace.slug, "initiative_id": initiative.id})
    return (client or default_client).post(
        url,
        data=json.dumps(body),
        content_type="application/json",
        HTTP_IF_MATCH=version or f'"{initiative.version}"',
        HTTP_IDEMPOTENCY_KEY=key,
    )


@pytest.mark.parametrize("action", ["submit", "approve", "return-for-revision"])
def test_authenticated_commands_accept_without_advancing_lifecycle(setup, action):
    response = post(setup, action)
    assert response.status_code == 202, response.data
    assert set(response.data) == {"schema_version", "id", "workspace_id", "operation_type", "status", "version"}
    assert response["ETag"] == f'"{setup[0][1].version}"' and response["Location"].endswith(f"/{response.data['id']}/")
    assert response["Cache-Control"] == "no-store"
    assert PrdAcceptedCommand.objects.count() == Operation.objects.count() == OutboxEvent.objects.count() == 1
    assert setup[1].calls == 1 and setup[1].committed == [uuid.UUID(response.data["id"])]
    setup[0][1].refresh_from_db()
    assert setup[0][1].state == "PRD_REVIEW" and setup[0][1].version == 2
    assert "sentinel" not in response.content.decode()


def test_replay_after_version_advance_never_prepares_again(setup):
    original = post(setup)
    initiative = setup[0][1]
    raw_update(initiative.id, version=3, state="PAUSED", paused_from_state="PRD_REVIEW")
    replay = post(setup)
    assert replay.status_code == 202 and replay.data["id"] == original.data["id"]
    assert replay["ETag"] == '"2"' and setup[1].calls == 1
    assert PrdAcceptedCommand.objects.count() == Operation.objects.count() == 1
    changed = post(setup, version='"3"')
    assert changed.status_code == 409 and setup[1].calls == 1


def test_replay_rechecks_current_membership(setup):
    assert post(setup).status_code == 202
    WorkspaceMember.objects.filter(workspace=setup[0][5], member=setup[0][4]).update(is_active=False)
    assert post(setup).status_code == 403
    assert setup[1].calls == 1 and Operation.objects.count() == 1


def test_membership_revocation_during_preparation_prevents_acceptance(setup):
    setup[1].on_prepare = lambda *_: WorkspaceMember.objects.filter(workspace=setup[0][5], member=setup[0][4]).update(
        is_active=False
    )
    assert post(setup).status_code == 403
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == OutboxEvent.objects.count() == 0
    assert setup[1].committed == [None]


def test_version_race_during_preparation_prevents_acceptance(setup):
    setup[1].on_prepare = lambda *_: raw_update(
        setup[0][1].id, version=3, state="PAUSED", paused_from_state="PRD_REVIEW"
    )
    assert post(setup).status_code == 412
    assert Operation.objects.count() == 0 and setup[1].committed == [None]


@pytest.mark.parametrize(
    "check", ["provider_capability", "storage_policy", "source_access", "evidence_access", "readiness", "worker_ready"]
)
def test_every_current_prerequisite_is_required(setup, check):
    setup[1].on_prepare = lambda prepared, _: prepared.checks.update({check: False})
    assert post(setup).status_code == 503
    assert Operation.objects.count() == 0 and setup[1].committed == [None]


def test_expired_preparation_and_revalidation_failure_do_not_enqueue(setup):
    setup[1].on_prepare = lambda prepared, _: setattr(prepared, "valid_until", timezone.now() - timedelta(seconds=1))
    assert post(setup).status_code == 503
    setup[1].on_prepare = None
    setup[1].on_revalidate = lambda _: False
    assert post(setup).status_code == 503
    assert Operation.objects.count() == 0


def test_competing_same_key_acceptance_reuses_one_operation_and_cleans_unused_preparation(setup):
    def competing(prepared, command):
        setup[1].on_prepare = None
        accept_prd_command(
            request=SimpleNamespace(user=setup[0][4]),
            workspace_slug=setup[0][5].slug,
            initiative_id=setup[0][1].id,
            command=command,
        )

    setup[1].on_prepare = competing
    response = post(setup)
    assert response.status_code == 202
    assert Operation.objects.count() == PrdAcceptedCommand.objects.count() == 1
    assert setup[1].calls == 2 and setup[1].committed.count(None) == 1


@pytest.mark.parametrize("enabled", [False, "true", 1, None])
def test_explicit_enablement_is_required(setup, settings, enabled):
    settings.CURVE_PRD_COMMANDS_ENABLED = enabled
    assert post(setup).status_code == 404 and setup[1].calls == 0


def test_missing_runtime_returns_safe_unavailable(setup, settings):
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = None
    assert post(setup).status_code == 503 and Operation.objects.count() == 0


def test_provider_exception_never_reaches_response(setup, caplog):
    def fail(*_):
        raise RuntimeError("Synthetic sensitive rationale sentinel")

    setup[1].on_prepare = fail
    response = post(setup)
    assert response.status_code == 503
    assert "sentinel" not in response.content.decode() and "sentinel" not in caplog.text
    assert Operation.objects.count() == 0


def test_anonymous_request_and_session_csrf_are_enforced(setup):
    assert post(setup, client=APIClient()).status_code == 401
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(setup[0][4])
    assert post(setup, client=client).status_code == 403
    token = _get_new_csrf_string()
    client.cookies["csrftoken"] = token
    client.credentials(HTTP_X_CSRFTOKEN=token)
    response = post(setup, client=client)
    assert response.status_code == 202, response.data


def test_validation_and_stale_precondition_do_not_reach_preparation(setup):
    assert post(setup, body={"actor": "Synthetic secret"}).status_code == 422
    assert post(setup, version='"1"').status_code == 412
    assert setup[1].calls == 0 and Operation.objects.count() == 0
    assert PolicyDecision.objects.filter(effect="ALLOW").exists()


def test_curve_token_logs_exclude_request_response_and_freeform_headers(setup, monkeypatch, caplog):
    captured = []
    monkeypatch.setattr(
        "plane.middleware.logger.process_logs.delay", lambda **kwargs: captured.append(kwargs["log_data"])
    )
    setup[2].credentials(
        HTTP_X_API_KEY="synthetic-api-token", HTTP_X_PRIVATE_NOTE="Synthetic sensitive rationale sentinel"
    )
    response = post(setup)
    assert response.status_code == 202
    assert len(captured) == 1
    assert captured[0]["body"] is None and captured[0]["response_body"] is None
    assert captured[0]["headers"] == "{}" and captured[0]["query_params"] == ""
    assert "sentinel" not in json.dumps(captured) and "sentinel" not in caplog.text


def test_real_session_preserves_duplicate_keys_and_limits_body_before_parsing(setup):
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(setup[0][4])
    token = _get_new_csrf_string()
    client.cookies["csrftoken"] = token
    client.credentials(HTTP_X_CSRFTOKEN=token)
    url = reverse("curve-prd-approve", kwargs={"slug": setup[0][5].slug, "initiative_id": setup[0][1].id})
    response = client.post(
        url,
        data=b'{"rationale":"first","rationale":"second"}',
        content_type="application/json",
        HTTP_IF_MATCH='"2"',
        HTTP_IDEMPOTENCY_KEY="synthetic-key",
    )
    assert response.status_code == 422
    malformed = client.post(url, data=b'{"rationale":', content_type="application/json")
    assert malformed.status_code == 422
    response = client.post(url, data=b" " * 65537, content_type="application/json")
    assert response.status_code == 413 and response["Cache-Control"] == "no-store"
    assert setup[1].calls == 0


def test_only_json_is_rendered_and_get_cannot_accept_command(setup):
    url = reverse("curve-prd-approve", kwargs={"slug": setup[0][5].slug, "initiative_id": setup[0][1].id})
    assert setup[2].get(url).status_code == 405
    response = setup[2].get(url, HTTP_ACCEPT="text/html")
    assert response.status_code == 406
    assert response["Content-Type"].startswith("application/problem+json")


def test_preparation_expiring_during_local_revalidation_is_rejected(setup):
    def expire(prepared):
        prepared.valid_until = timezone.now() - timedelta(seconds=1)
        return True

    setup[1].on_revalidate = expire
    assert post(setup).status_code == 503 and Operation.objects.count() == 0
