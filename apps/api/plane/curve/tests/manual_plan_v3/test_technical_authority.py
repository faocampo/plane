# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Fresh native two-reviewer authority with real PRD and plan persistence."""

# ruff: noqa: F401,F811 -- pytest fixture dependencies.
from copy import deepcopy
from types import SimpleNamespace
import pytest
from django.db import transaction
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge
from plane.curve.tests.test_scoped_prd_two_stage_runtime import two_stage
from plane.curve.tests.manual_plan_v3.test_persistence import native, command, save
from plane.curve.tests.manual_plan_v3.native_fixture import publish_catalog
from plane.curve.manual_gate2_v3 import policy
from plane.curve.manual_gate2_v3.contracts import Gate2Error
from plane.curve.manual_plan_v3.synthetic import SyntheticManualPlanResolverV3
from plane.curve.manual_plan_v2.models import ManualPlanRevisionV2
from plane.curve.manual_plan_v3.contracts import ManualPlanError
from plane.curve.prd_commands import PrdCommandError

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def review(native, settings):
    settings.CURVE_MANUAL_GATE2_V3_ENABLED = True
    saved = save(native, command(native)).data
    native.revision = ManualPlanRevisionV2.objects.get(id=saved["id"])
    native.initiative.refresh_from_db()
    return native


def actor(n, gate):
    identifier = next(g["approver_user_id"] for g in n.manual_identity["gate_assignments"] if g["gate_type"] == gate)
    return next(u for u in n.reviewers if str(u.id) == identifier)


def load(n, action="APPROVE", user=None):
    with SyntheticManualPlanResolverV3(str(n.manual_root)) as resolver, transaction.atomic():
        return policy.load_authority(
            request=SimpleNamespace(user=user or actor(n, "PLAN_APPROVAL")),
            slug=n.workspace.slug,
            revision=n.revision,
            resolver=resolver,
            action=action,
        )


@pytest.mark.parametrize("action", ["APPROVE", "REQUEST_CHANGES", "RECONCILE", "RELEASE"])
def test_current_technical_reviewer_has_exact_two_stage_authority(review, action):
    authority = load(review, action)
    assert {g["gate_type"] for g in authority.context.reviewers} == {"PLAN_APPROVAL", "PRD_APPROVAL"}
    assert authority.captured.identity == review.revision.original_input_identity
    assert str(review.reviewers[2].id) not in authority.principals
    assert authority.context.actor_id == actor(review, "PLAN_APPROVAL").id


@pytest.mark.parametrize("action", ["APPROVE", "REQUEST_CHANGES", "RECONCILE", "RELEASE"])
def test_product_reviewer_cannot_make_technical_decisions(review, action):
    with pytest.raises((Gate2Error, ManualPlanError, PrdCommandError)):
        load(review, action, user=actor(review, "PRD_APPROVAL"))


def test_creator_can_prepare_but_cannot_approve(review):
    authority = load(review, "PREPARE", user=review.user)
    assert authority.context.actor_id == review.user.id
    with pytest.raises((Gate2Error, ManualPlanError, PrdCommandError)):
        load(review, user=review.user)


def test_revoked_former_code_reviewer_has_no_technical_authority(review):
    with pytest.raises((Gate2Error, ManualPlanError, PrdCommandError)):
        load(review, user=review.reviewers[2])


@pytest.mark.parametrize("action", ["APPROVE", "RELEASE"])
def test_current_product_material_access_is_still_required(review, action):
    catalog = deepcopy(review.manual_catalog)
    product_id = str(actor(review, "PRD_APPROVAL").id)
    identifier = review.manual_identity["definition_ref"]["object_id"]
    grants = catalog["objects"][identifier]["grants"]
    for grant in grants:
        if grant["principal_id"] == product_id:
            grant["actions"] = []
            grant["acl_generation"] += 1
    catalog["generation"] += 1
    publish_catalog(review, catalog)
    with pytest.raises((Gate2Error, ManualPlanError, PrdCommandError)):
        load(review, action)


def test_new_authority_requires_explicit_switch(review, settings):
    settings.CURVE_MANUAL_GATE2_V3_ENABLED = False
    with pytest.raises(Gate2Error):
        load(review)


def test_decision_writer_requires_complete_storage_qualification():
    with transaction.atomic():
        policy.require_edition()
