# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from copy import deepcopy
from types import SimpleNamespace

import pytest

from plane.curve.manual_plan_v2.contracts import ManualPlanError
from plane.curve.manual_plan_v2.synthetic import ACTIONS, SyntheticManualPlanResolverV2, advance_native_authority
from plane.curve.manual_plan_v2.validation import canonical_json
from plane.curve.manual_plan_v3.policy import bind_inputs
from plane.curve.manual_plan_v3.synthetic import SyntheticManualPlanResolverV3
from plane.curve.manual_plan_v3.validator_worker import validate_in_worker
from plane.curve.tests.test_manual_plan_v3_worker import captured_plan

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "protected"
    root.mkdir(mode=0o700)
    captured = captured_plan()
    identity = captured.identity
    principals = sorted({*identity["human_owner_ids"], *(g["approver_user_id"] for g in identity["gate_assignments"])})
    grants = [
        dict(principal_id=p, actions=sorted(ACTIONS), acl_generation=1, classification_generation=1) for p in principals
    ]
    entry = dict(
        workspace_id=identity["workspace_id"],
        technical_contributor_ids=identity["human_owner_ids"],
        grants=grants,
        native_authority=advance_native_authority(
            None,
            dict(
                memberships={p: "sha256:" + "0" * 64 for p in principals},
                sources={p: "sha256:" + "0" * 64 for p in principals},
            ),
        ),
    )
    objects = {}
    originals = [
        dict(
            object_ref=identity["definition_ref"],
            material_version_id=identity["definition_ref"]["object_id"],
            access_envelope_id=identity["definition_ref"]["object_id"],
            classification="INTERNAL",
        ),
        *identity["protected_inputs"],
    ]
    materials = {**captured.materials, identity["definition_ref"]["object_id"]: captured.definition}
    for item in originals:
        key = item["object_ref"]["object_id"]
        path = root / key
        path.write_bytes(materials[key])
        path.chmod(0o600)
        objects[key] = dict(
            workspace_id=identity["workspace_id"],
            grants=deepcopy(grants),
            **{
                field: item[field]
                for field in ("object_ref", "material_version_id", "access_envelope_id", "classification")
            },
        )
    catalog = dict(
        schema_version="curve.synthetic-manual-plan-catalog/v3-candidate",
        generation=1,
        initiatives={identity["initiative_id"]: entry},
        objects=objects,
        plans={
            identity["definition_ref"]["object_id"]: dict(
                identity=identity, facts=captured.facts, semantic_sources=captured.semantic_sources
            )
        },
    )
    path = root / "catalog.json"
    path.write_bytes(canonical_json(catalog))
    path.chmod(0o600)
    arguments = dict(
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        definition_ref=identity["definition_ref"],
        principals=principals,
        action="SAVE",
    )
    return root, captured, arguments


def test_protected_successor_capture_runs_through_linux_validator(store):
    root, original, arguments = store
    with SyntheticManualPlanResolverV3(str(root)) as resolver:
        captured = resolver.capture(**arguments)
        assert captured.definition == original.definition
        assert validate_in_worker(captured)["result"] == "VALID"


@pytest.mark.parametrize("tamper", ["grant", "workspace", "content", "permissions"])
def test_capture_rejects_wrong_authority_or_changed_material(store, tamper):
    root, captured, arguments = store
    if tamper == "grant":
        arguments["principals"] = ["90000000-0000-4000-8000-000000000001"]
    elif tamper == "workspace":
        arguments["workspace_id"] = "90000000-0000-4000-8000-000000000002"
    elif tamper == "content":
        (root / captured.identity["definition_ref"]["object_id"]).write_bytes(b"changed")
    else:
        (root / "catalog.json").chmod(0o644)
    with SyntheticManualPlanResolverV3(str(root)) as resolver, pytest.raises(ManualPlanError):
        resolver.capture(**arguments)


def test_historical_resolver_does_not_accept_successor_catalog(store):
    root, _, arguments = store
    with SyntheticManualPlanResolverV2(str(root)) as resolver, pytest.raises(ManualPlanError):
        resolver.capture(**arguments)


def native_context(captured):
    identity, facts = captured.identity, captured.facts
    context = SimpleNamespace(
        initiative=SimpleNamespace(
            id=identity["initiative_id"],
            workspace_id=identity["workspace_id"],
            schema_version="1.2",
            keyword=facts["initiative_key"],
            risk_tier=facts["risk_tier"],
            workflow_version_id=identity["workflow_ref"]["entity_id"],
        ),
        revision=SimpleNamespace(
            id=identity["scope_revision_ref"]["entity_id"], membership_digest=identity["scope_revision_ref"]["digest"]
        ),
        reviewers=tuple(deepcopy(identity["gate_assignments"])),
        members=[SimpleNamespace(purpose="PROPOSED_DELIVERY", **item) for item in facts["proposed_delivery_refs"]],
    )
    subject = SimpleNamespace(
        id=identity["approved_subject_ref"]["entity_id"],
        digest=identity["approved_subject_ref"]["digest"],
        as_record=lambda: dict(
            artifact_version_id=identity["prd_artifact_version_id"],
            content_digest=identity["prd_content_digest"],
            evidence_snapshot_id=identity["evidence_snapshot_id"],
        ),
    )
    return context, subject


def test_successor_inputs_bind_to_exact_current_native_context():
    captured = captured_plan()
    context, subject = native_context(captured)
    assert bind_inputs(context, subject, captured) == captured.identity


@pytest.mark.parametrize("tamper", ["legacy", "reviewer", "subject", "workflow", "risk", "workspace", "initiative"])
def test_native_binding_rejects_stale_or_mismatched_authority(tamper):
    captured = captured_plan()
    context, subject = native_context(captured)
    if tamper == "legacy":
        context.initiative.schema_version = "1.1"
    elif tamper == "reviewer":
        context.reviewers[0]["approver_user_id"] = "90000000-0000-4000-8000-000000000001"
    elif tamper == "subject":
        subject.digest = "sha256:" + "0" * 64
    elif tamper == "workflow":
        context.initiative.workflow_version_id = "90000000-0000-4000-8000-000000000002"
    elif tamper == "workspace":
        context.initiative.workspace_id = "90000000-0000-4000-8000-000000000003"
    elif tamper == "initiative":
        context.initiative.id = "90000000-0000-4000-8000-000000000004"
    else:
        context.initiative.risk_tier = "HIGH"
    with pytest.raises(ManualPlanError):
        bind_inputs(context, subject, captured)
