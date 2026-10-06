"""Real approved PRD, memberships, catalog CAS and protected-body integration."""

# ruff: noqa: F401,F811 -- imported pytest fixtures are collected here.
from copy import deepcopy

import pytest
from django.db import transaction
from django.utils import timezone
from plane.db.models import ProjectMember, WorkspaceMember, Issue
from plane.curve.models import AuditEvent, DomainEvent, PolicyDecision
from plane.curve.prd_commands import PrdCommandError
from plane.curve.tests.test_scoped_prd_bridge import configuration, context, bridge

from plane.curve.manual_plan_v2 import policy, synthetic
from plane.curve.manual_plan_v2.contracts import ManualPlanError
from plane.curve.manual_plan_v2.validator_worker import validate_in_worker
from native_fixture import capture_native, current_contexts, prepare_native_fixture, publish_catalog

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def native(bridge, settings, tmp_path):
    return prepare_native_fixture(bridge, settings, tmp_path)


def test_actual_approved_prd_bytes_produce_current_authority_and_valid_linux_receipt(native):
    before = [model.objects.count() for model in (AuditEvent, DomainEvent, PolicyDecision)]
    captured = capture_native(native)
    assert len(captured.authority["principal_checks"]) == 3
    assert captured.authority["source_access_generation"] == 1
    assert captured.identity["prd_content_digest"] == native.manual_subject.payload["content_digest"]
    assert validate_in_worker(captured)["result"] == "VALID"
    assert before == [model.objects.count() for model in (AuditEvent, DomainEvent, PolicyDecision)]


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("kind", ["workspace", "project"])
def test_each_actor_owner_or_reviewer_requires_current_native_access(native, kind, index):
    model = WorkspaceMember if kind == "workspace" else ProjectMember
    model.objects.filter(workspace=native.workspace, member=native.reviewers[index]).update(is_active=False)
    with pytest.raises((PrdCommandError, ManualPlanError)):
        capture_native(native)


def test_native_role_change_requires_monotonic_producer_refresh(native):
    old = capture_native(native)
    WorkspaceMember.objects.filter(workspace=native.workspace, member=native.reviewers[1]).update(role=20)
    with pytest.raises(ManualPlanError):
        capture_native(native)
    replacement = deepcopy(native.manual_catalog)
    replacement["generation"] += 1
    entry = replacement["initiatives"][str(native.initiative.id)]
    with transaction.atomic():
        entry["native_authority"] = policy.prepare_native_catalog_authority(
            current_contexts(native, native.manual_subject),
            entry["native_authority"],
        )
        publish_catalog(native, replacement)
    current = capture_native(native)
    assert current.authority["source_access_generation"] == 2
    principal = str(native.reviewers[1].id)
    assert entry["native_authority"]["memberships"][principal]["generation"] == 2
    assert current.authority["fence_digest"] != old.authority["fence_digest"]


def test_native_membership_cannot_replace_protected_object_grant(native):
    replacement = deepcopy(native.manual_catalog)
    replacement["generation"] += 1
    source = replacement["plans"][native.manual_identity["definition_ref"]["object_id"]]["semantic_sources"]["prd"]
    grant = replacement["objects"][source["object_id"]]["grants"][1]
    grant["actions"], grant["acl_generation"] = [], grant["acl_generation"] + 1
    publish_catalog(native, replacement)
    with pytest.raises(ManualPlanError):
        capture_native(native)


def test_actual_source_edit_invalidates_old_approved_subject(native):
    Issue.objects.filter(id=native.issue.id).update(name="Changed synthetic requirement", updated_at=timezone.now())
    with pytest.raises((PrdCommandError, ManualPlanError)):
        capture_native(native)


def test_missing_retained_prd_body_fails_closed(native):
    source = native.manual_catalog["plans"][native.manual_identity["definition_ref"]["object_id"]]["semantic_sources"][
        "prd"
    ]
    (native.manual_root / source["object_id"]).unlink()
    with pytest.raises((ManualPlanError, FileNotFoundError)):
        capture_native(native)


@pytest.mark.parametrize("index", [0, 1])
def test_selected_evidence_body_and_excerpt_each_require_current_object_access(native, index):
    reference, _ = native.manual_evidence_materials[index]
    captured = capture_native(native)
    assert reference in [item["object_ref"] for item in captured.identity["protected_inputs"]]
    replacement = deepcopy(native.manual_catalog)
    replacement["generation"] += 1
    grant = replacement["objects"][reference["object_id"]]["grants"][2]
    grant["actions"], grant["acl_generation"] = [], grant["acl_generation"] + 1
    publish_catalog(native, replacement)
    with pytest.raises(ManualPlanError):
        capture_native(native)
