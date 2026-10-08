# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Native PostgreSQL manual control, retained claims and protected command retries."""

# ruff: noqa: F401,F811
from copy import deepcopy
from types import SimpleNamespace
import traceback
import uuid
import pytest
from django.db import connection, transaction, DatabaseError
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.curve.tests.manual_plan_v2.native_fixture import (
    prepare_native_fixture,
    publish_catalog,
    write,
)
from plane.curve.tests.manual_plan_v2.test_manual_persistence import (
    command as draft_command,
    save as save_draft,
)
from plane.curve.manual_plan_v2.validation import canonical_json, digest
from plane.curve.manual_plan_v2.contracts import ManualPlanError
from plane.curve.manual_gate2_v2.domain import Gate2Denied
from plane.curve.policy_services import CurvePolicyResourceNotFound
from plane.curve.manual_gate2_v2 import services, contracts, reads
from plane.curve.manual_gate2_v2.models import (
    ManualGate2ControlV2,
    ManualGate2RecordV2,
    ManualTaskClaimV2,
    ManualTaskClaimHistoryV2,
)
from plane.curve.models import (
    PolicyDecision,
    AuditEvent,
    DomainEvent,
    OutboxEvent,
    IdempotencyRecord,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]
GRAPH = (
    ManualGate2ControlV2,
    ManualGate2RecordV2,
    ManualTaskClaimV2,
    ManualTaskClaimHistoryV2,
    PolicyDecision,
    AuditEvent,
    DomainEvent,
    OutboxEvent,
    IdempotencyRecord,
)


@pytest.fixture
def native(bridge, settings, tmp_path):
    n = prepare_native_fixture(bridge, settings, tmp_path)
    settings.CURVE_MANUAL_GATE2_V2_ENABLED = True
    return save_with_rationales(n)


def save_with_rationales(n):
    n.draft = save_draft(n, draft_command(n)).data
    n.initiative.refresh_from_db()
    catalog = deepcopy(n.manual_catalog)
    catalog["generation"] += 1
    n.rationales = {}
    grants = catalog["objects"][n.manual_identity["definition_ref"]["object_id"]]["grants"]
    for intent in ("APPROVE", "REQUEST_CHANGES", "RECONCILE"):
        identifier = str(uuid.uuid4())
        body = canonical_json(
            dict(
                schema_version="curve.manual-gate2.rationale/v2-candidate",
                workspace_id=str(n.workspace.id),
                initiative_id=str(n.initiative.id),
                draft_revision_id=n.draft["id"],
                intent=intent,
                text="Synthetic review evidence",
                no_unresolved_controlled_work=intent == "RECONCILE",
            )
        )
        ref = dict(
            object_id=identifier,
            digest=digest(body),
            size_bytes=len(body),
            media_type="application/json",
        )
        catalog["objects"][identifier] = dict(
            workspace_id=str(n.workspace.id),
            object_ref=ref,
            material_version_id=identifier,
            access_envelope_id=identifier,
            classification="INTERNAL",
            grants=deepcopy(grants),
        )
        write(n.manual_root, identifier, body)
        n.rationales[intent] = ref
    publish_catalog(n, catalog)
    return n


def counts():
    return tuple(m.objects.count() for m in GRAPH)


def command(n, action, *, subject=None, claims=None, reconciliation=None, key=None, version=None):
    n.initiative.refresh_from_db()
    payload = dict(
        schema_version="curve.manual-gate2.command/v2-candidate",
        action=action,
        draft_revision_id=n.draft["id"],
        subject_ref=None if subject is None else dict(entity_id=subject["id"], digest=subject["subject_digest"]),
        rationale_ref=None if action == "PREPARE" else n.rationales["RECONCILE" if action == "RELEASE" else action],
        claims=[]
        if claims is None
        else sorted(
            [dict(claim_id=c["claim_id"], generation=c["generation"]) for c in claims],
            key=lambda c: c["claim_id"],
        ),
        reconciliation_ref=None
        if reconciliation is None
        else dict(entity_id=reconciliation["id"], digest=reconciliation["digest"]),
    )
    return contracts.parse_command(
        initiative_id=n.initiative.id,
        raw=canonical_json(payload),
        if_match=f'"curve-initiative:{n.initiative.id}:v{version or n.initiative.version}"',
        key=key or str(uuid.uuid4()),
    )


def execute(n, value, actor=None):
    try:
        return services.execute(
            request=SimpleNamespace(user=actor or (n.user if value.action == "PREPARE" else n.reviewers[1])),
            slug=n.workspace.slug,
            command=value,
        )
    except contracts.Gate2Error as e:
        if e.__context__ is not None and not isinstance(
            e.__context__, (ManualPlanError, Gate2Denied, CurvePolicyResourceNotFound)
        ):
            pytest.fail("".join(traceback.format_exception(e.__context__)))
        raise


def approve(n):
    subject = execute(n, command(n, "PREPARE")).data
    value = command(n, "APPROVE", subject=subject)
    approved = execute(n, value).data
    return subject, value, approved


def test_prepare_approve_reconcile_release_and_original_retry(native):
    n = native
    prepared = reads.preparation(
        request=SimpleNamespace(user=n.user, query_params={}),
        slug=n.workspace.slug,
        initiative_id=n.initiative.id,
    )
    assert len(prepared.data["plans"]) == 1
    subject, value, approved = approve(n)
    assert len(approved["claims"]) == 1 and approved["claims"][0]["generation"] == 1
    n.initiative.refresh_from_db()
    assert n.initiative.state == "PLANNING"
    current = reads.status(
        request=SimpleNamespace(user=n.reviewers[1], query_params={}),
        slug=n.workspace.slug,
        initiative_id=n.initiative.id,
    )
    assert current.data["state"] == "MANUAL_APPROVED" and current.data["execution_authorized"] is False
    reconciled = execute(n, command(n, "RECONCILE", subject=subject, claims=approved["claims"])).data
    release = command(
        n,
        "RELEASE",
        subject=subject,
        claims=approved["claims"],
        reconciliation=reconciled,
    )
    released = execute(n, release)
    assert released.data["claims"][0]["state"] == "RELEASED"
    assert ManualGate2ControlV2.objects.get(initiative_id=n.initiative.id).state == "RELEASED"
    before = counts()
    retry = execute(n, value)
    assert retry.replayed and retry.data == approved
    assert tuple(a - b for a, b in zip(counts(), before)) == (0, 0, 0, 0, 1, 1, 0, 0, 0)
    assert ManualTaskClaimV2.objects.get().state == "RELEASED"
    assert execute(n, release).replayed


def test_wrong_approver_and_stale_version_roll_back_everything(native):
    n = native
    subject = execute(n, command(n, "PREPARE")).data
    value = command(n, "APPROVE", subject=subject)
    before = counts()
    with pytest.raises(contracts.Gate2Error):
        execute(n, value, n.user)
    assert counts() == before
    with pytest.raises(contracts.Gate2Error, match="PRECONDITION_FAILED"):
        execute(
            n,
            command(n, "APPROVE", subject=subject, version=value.expected_version - 1),
        )
    assert counts() == before


def test_reconciliation_change_denies_release_and_preserves_claim(native):
    from plane.db.models import Issue

    n = native
    subject, _, approved = approve(n)
    reconciled = execute(n, command(n, "RECONCILE", subject=subject, claims=approved["claims"])).data
    Issue.objects.filter(id=n.issue.id).update(name="Synthetic changed observation")
    # updated_at is the native version fence; emulate a native edit with ordinary save.
    n.issue.refresh_from_db()
    n.issue.save()
    before = counts()
    with pytest.raises(contracts.Gate2Error, match="RECONCILIATION_STALE"):
        execute(
            n,
            command(
                n,
                "RELEASE",
                subject=subject,
                claims=approved["claims"],
                reconciliation=reconciled,
            ),
        )
    assert counts() == before and ManualTaskClaimV2.objects.get().state == "ACTIVE"


def test_protected_rationale_revocation_denies_retry(native):
    n = native
    subject, value, _ = approve(n)
    catalog = deepcopy(n.manual_catalog)
    catalog["generation"] += 1
    g = catalog["objects"][n.rationales["APPROVE"]["object_id"]]["grants"][1]
    g["actions"] = []
    g["acl_generation"] += 1
    publish_catalog(n, catalog)
    before = counts()
    with pytest.raises(contracts.Gate2Error):
        execute(n, value)
    assert counts() == before and ManualTaskClaimV2.objects.get().state == "ACTIVE"
