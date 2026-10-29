# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Real Item creation through Product and Technical local approval commands."""

from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from django.db import transaction

from plane.curve.models import Initiative, GateAssignment
from plane.curve.tests import test_item_creation_commands as items
from plane.curve.tests import test_local_document_services as documents
from plane.curve.tests import test_local_prd_review_services as reviews
from plane.curve.tests import test_local_plan_services as plans
from plane.curve.tests import test_local_plan_review_services as plan_reviews
from plane.curve.tests.test_local_new_work import align
from plane.curve.tests.test_local_prd_reopening_commands import command as reopen
from plane.curve.local_plan_authority import require_local_plan_authority
from plane.curve.prd_commands import PrdCommandError

scope, prepared, material = items.scope, items.prepared, items.material
store = documents.store
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def roadmap_work(scope, prepared, material, settings):
    settings.CURVE_LOCAL_PRD_ENABLED = True
    settings.CURVE_PRD_ACCEPTANCE_RUNTIME = None
    settings.CURVE_PRD_COMPLETION_RUNTIME = None
    payload = deepcopy(prepared[3])
    payload["scope_body"] = material.reference
    payload["initiative"]["business_intent"] = "STRATEGIC"
    result = items.command(scope, prepared, material, payload=payload)
    initiative = Initiative.objects.get(id=result.resource_ref["initiative_ref"]["resource_id"])
    return SimpleNamespace(
        workspace=scope.workspace,
        product=scope.product,
        initiative=initiative,
        user=scope.owner,
        request=SimpleNamespace(user=scope.owner),
        reviewers=[scope.member, scope.admin],
    )


def test_created_item_completes_product_then_technical_approval(roadmap_work, store):
    work = roadmap_work
    source = documents.upload(work, store).data
    align(work)
    submitted = reviews.command(work, store, source).data
    assert submitted["schema_version"] == "curve.local-prd-submission/v3-roadmap-candidate"
    assert submitted["roadmap_item_id"] == str(work.initiative.roadmap_item_id)
    product = reviews.command(
        work, store, source, "APPROVE", submitted, request=SimpleNamespace(user=work.reviewers[0])
    ).data
    assert work.initiative.state == "PLANNING"
    approved = (source, submitted, product)
    plan = plans.upload_plan(work, store, approved).data
    plan_subject = plan_reviews.command(work, store, approved, plan).data
    technical = plan_reviews.command(work, store, approved, plan, "APPROVE", plan_subject).data
    assert product["state"] == technical["state"] == "APPROVED"
    assert plan["prd_submission_id"] == submitted["id"]
    assert plan["prd_decision_id"] == product["id"]
    assert set(GateAssignment.objects.filter(initiative_id=work.initiative.id).values_list("gate_type", flat=True)) == {
        "PRD_APPROVAL",
        "PLAN_APPROVAL",
    }
    reopen(work, approved)
    with pytest.raises(PrdCommandError, match="PRODUCT_APPROVAL_REQUIRED"), transaction.atomic():
        require_local_plan_authority(
            request=work.request, workspace_slug=work.workspace.slug, initiative_id=work.initiative.id, action="READ"
        )
    replacement = documents.upload(
        work,
        store,
        expected_source_version=1,
        raw_idempotency_key="replacement-prd",
        stream=BytesIO(b"# Revised requirements\nChanged acceptance criteria."),
    ).data
    revised = reviews.command(work, store, replacement, raw_idempotency_key="resubmit-prd").data
    reviews.command(
        work,
        store,
        replacement,
        "APPROVE",
        revised,
        request=SimpleNamespace(user=work.reviewers[0]),
        raw_idempotency_key="approve-revised-prd",
    )
    with transaction.atomic():
        current = require_local_plan_authority(
            request=work.request, workspace_slug=work.workspace.slug, initiative_id=work.initiative.id, action="READ"
        )
        assert current.revision_is_current is False
        assert current.decision.id is not None
