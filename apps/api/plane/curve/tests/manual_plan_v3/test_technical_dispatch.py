# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Native two-stage submission requires session, CSRF, and qualified storage."""

# ruff: noqa: F401,F811 -- pytest fixture dependencies.
import pytest
from rest_framework.test import APIClient
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage
from plane.curve.tests.manual_plan_v3.test_persistence import native
from plane.curve.tests.manual_plan_v3.test_technical_authority import review
from plane.curve.tests.manual_gate2_v2.test_gate2 import counts
from plane.curve.manual_plan_v3.validation import canonical_json
from plane.curve.manual_gate2_v2.models import ManualGate2ControlV2, Gate2WriteDenied

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_real_v3_routes_require_session_csrf_and_qualified_storage(review, settings):
    n = review
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(n.user)
    root = f"/api/v1/workspaces/{n.workspace.slug}/curve/initiatives/{n.initiative.id}/manual-gate2/v3/"
    value = dict(
        schema_version="curve.manual-gate2.command/v3-candidate",
        action="PREPARE",
        draft_revision_id=str(n.revision.id),
        subject_ref=None,
        rationale_ref=None,
        reconciliation_ref=None,
        claims=[],
    )
    headers = dict(
        HTTP_IF_MATCH=f'"curve-initiative:{n.initiative.id}:v{n.initiative.version}"',
        HTTP_IDEMPOTENCY_KEY="synthetic-dispatch",
    )
    before = counts()
    assert (
        client.post(root + "commands/", canonical_json(value), content_type="application/json", **headers).status_code
        == 404
    )
    token = "a" * 32
    client.cookies[settings.CSRF_COOKIE_NAME] = token
    headers["HTTP_X_CSRFTOKEN"] = token
    response = client.post(root + "commands/", canonical_json(value), content_type="application/json", **headers)
    assert response.status_code == 201, response.content
    assert response.json()["action"] == "PREPARE"
    after = counts()
    assert after != before
    for suffix in ["status/", "preparation/", "materials/" + n.manual_identity["definition_ref"]["object_id"] + "/"]:
        response = client.get(root + suffix)
        assert response.status_code == 200, response.content
        assert response["Cache-Control"] == "no-store"
    value["schema_version"] = "curve.manual-gate2.command/v2-candidate"
    assert (
        client.post(root + "commands/", canonical_json(value), content_type="application/json", **headers).status_code
        == 422
    )
    assert APIClient().get(root + "status/").status_code == 404
    settings.CURVE_MANUAL_GATE2_V3_ENABLED = False
    assert client.get(root + "status/").status_code == 404
    assert counts() == after


def test_shared_model_rejects_a_direct_write_without_either_exact_receipt(review):
    with pytest.raises(Gate2WriteDenied):
        ManualGate2ControlV2(
            workspace_id=review.workspace.id, product_id=review.product.id, initiative_id=review.initiative.id
        ).save()
