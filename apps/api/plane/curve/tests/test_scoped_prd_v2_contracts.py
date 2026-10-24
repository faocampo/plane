# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Successor wire contracts and replay separation, without database activation."""

from copy import deepcopy
import json
import shutil
import uuid

import pytest
from jsonschema import Draft202012Validator

from plane.curve.prd_commands import PrdCommandError
from plane.curve.scoped_prd_commands import parse_scoped_prd_command, validate_scoped_command
from plane.curve.scoped_prd_contracts import (
    SCHEMA_VERSION as V1_VERSION,
    POLICY_EDITION as V1_POLICY,
    canonical,
    digest,
    require_contract_integrity as require_v1_integrity,
    validate_versioned_scoped_contract,
)
from plane.curve import scoped_prd_v2_contracts as successor

pytestmark = pytest.mark.unit


def uid(number):
    return str(uuid.UUID(int=number))


def observation():
    return dict(
        schema_version=successor.SCHEMA_VERSION,
        policy_edition=successor.POLICY_EDITION,
        id=uid(1),
        workspace_id=uid(2),
        product_id=uid(3),
        initiative_id=uid(4),
        initiative_version=1,
        proposal_id=uid(5),
        scope_revision_id=uid(6),
        scope_revision=1,
        membership_digest="sha256:" + "a" * 64,
        members=[
            dict(
                association_id=uid(7),
                association_version=1,
                provider_installation_id=uid(8),
                source_project_id=uid(9),
                source_issue_id=uid(10),
                purpose="CONTEXT_EVIDENCE",
                source_version="1",
                source_fingerprint="sha256:" + "b" * 64,
            )
        ],
        reviewers=[
            dict(gate_assignment_id=uid(20 + i), gate_type=gate, approver_user_id=uid(30 + i))
            for i, gate in enumerate(("PLAN_APPROVAL", "PRD_APPROVAL"))
        ],
        created_by=uid(40),
        recorded_at="2026-10-21T12:00:00Z",
        digest="sha256:" + "c" * 64,
        controlling=False,
    )


def command_payload(version=2):
    data = observation()
    payload = {
        key: data[key]
        for key in (
            "schema_version",
            "policy_edition",
            "proposal_id",
            "scope_revision_id",
            "scope_revision",
            "membership_digest",
        )
    }
    if version == 1:
        payload.update(schema_version=V1_VERSION, policy_edition=V1_POLICY)
    return payload


def parse(payload):
    return parse_scoped_prd_command(
        route="observe",
        body=canonical(payload),
        if_match='"1"',
        idempotency_key="synthetic-scoped-review",
        edition=payload.get("schema_version"),
    )


def test_legacy_route_cannot_activate_successor_from_request_body():
    with pytest.raises(PrdCommandError):
        parse_scoped_prd_command(
            route="observe",
            body=canonical(command_payload()),
            if_match='"1"',
            idempotency_key="synthetic-scoped-review",
        )


def test_both_contract_bundles_retain_exact_integrity():
    require_v1_integrity()
    manifest = successor.require_contract_integrity()
    for name in manifest:
        if name.endswith(".schema.json"):
            Draft202012Validator.check_schema(json.loads((successor.DIRECTORY / name).read_bytes()))


def test_two_stage_observation_requires_both_distinct_assignments():
    value = observation()
    assert validate_versioned_scoped_contract("observation", value) == value
    # LOW-risk overlap remains a policy decision: the metadata contract allows
    # one human with two distinct assignments, while preserving both gates.
    value["reviewers"][1]["approver_user_id"] = value["reviewers"][0]["approver_user_id"]
    assert validate_versioned_scoped_contract("observation", value) == value


@pytest.mark.parametrize(
    "attack",
    [
        "code",
        "third",
        "missing",
        "duplicate-gate",
        "duplicate-assignment",
        "reorder",
        "mixed-policy",
        "extra",
        "unknown-edition",
        "missing-edition",
    ],
)
def test_observation_rejects_mixed_or_ambiguous_review_records(attack):
    value = observation()
    if attack == "code":
        value["reviewers"][0]["gate_type"] = "CODE_READINESS"
    elif attack == "third":
        value["reviewers"].append(
            dict(gate_assignment_id=uid(60), gate_type="CODE_READINESS", approver_user_id=uid(61))
        )
    elif attack == "missing":
        value["reviewers"].pop()
    elif attack == "duplicate-gate":
        value["reviewers"][1]["gate_type"] = "PLAN_APPROVAL"
    elif attack == "duplicate-assignment":
        value["reviewers"][1]["gate_assignment_id"] = value["reviewers"][0]["gate_assignment_id"]
    elif attack == "reorder":
        value["reviewers"].reverse()
    elif attack == "mixed-policy":
        value["policy_edition"] = V1_POLICY
    elif attack == "extra":
        value["document_body"] = "Synthetic text that belongs in protected storage"
    elif attack == "unknown-edition":
        value["schema_version"] = "curve.scoped-prd/v999-candidate"
    else:
        del value["schema_version"]
    with pytest.raises(PrdCommandError):
        validate_versioned_scoped_contract("observation", value)


def test_original_three_reviewer_observation_keeps_original_contract():
    value = observation()
    value.update(schema_version=V1_VERSION, policy_edition=V1_POLICY)
    value["reviewers"].insert(0, dict(gate_assignment_id=uid(60), gate_type="CODE_READINESS", approver_user_id=uid(61)))
    assert validate_versioned_scoped_contract("observation", value) == value
    value.update(schema_version=successor.SCHEMA_VERSION, policy_edition=successor.POLICY_EDITION)
    with pytest.raises(PrdCommandError):
        validate_versioned_scoped_contract("observation", value)


def test_new_commands_bind_edition_in_request_and_replay_identity():
    previous = parse(command_payload(1))
    current = parse(command_payload(2))
    for command in (previous, current):
        assert validate_scoped_command(command, edition=command.subject_metadata()["schema_version"]) == command
        assert (
            json.loads(command.operation_request_identity())["edition"] == command.subject_metadata()["schema_version"]
        )
    assert previous.request_digest != current.request_digest
    assert previous.operation_request_identity() != current.operation_request_identity()
    assert previous.request_digest == digest(
        dict(edition=V1_VERSION, action=previous.action, expected_version=1, payload=command_payload(1))
    )


def test_legacy_service_cannot_reinterpret_explicit_successor_command():
    with pytest.raises(PrdCommandError):
        validate_scoped_command(parse(command_payload(2)))


@pytest.mark.parametrize("field", ["schema_version", "policy_edition"])
def test_parser_rejects_mixed_editions(field):
    payload = command_payload(2)
    payload[field] = command_payload(1)[field]
    with pytest.raises(PrdCommandError):
        parse(payload)


@pytest.mark.parametrize("name", ["manifest-v2.json", "scoped-prd-observation-v2.schema.json", "policy-v2.json"])
def test_successor_tampering_fails_closed(tmp_path, monkeypatch, name):
    shutil.copytree(successor.DIRECTORY, tmp_path / "contracts")
    monkeypatch.setattr(successor, "DIRECTORY", tmp_path / "contracts")
    with (successor.DIRECTORY / name).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(PrdCommandError, match="SCOPED_PRD_CONTRACT_UNAVAILABLE"):
        parse(command_payload())


def test_explicit_validator_does_not_accept_paths_or_old_names():
    for name in ("../scoped_prd_candidate/scoped-prd-observation-v1", "Observation-v1", "scoped-prd-observation-v1"):
        with pytest.raises(PrdCommandError):
            successor.validate_scoped_v2_contract(name, deepcopy(observation()))
