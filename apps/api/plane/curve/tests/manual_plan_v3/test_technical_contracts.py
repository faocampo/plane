# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Closed Technical-review contracts and exact embedded two-stage plan schemas."""

from copy import deepcopy
import json
from pathlib import Path
import shutil

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
import pytest
from plane.curve.manual_gate2_v3 import contracts as current
from plane.curve.manual_gate2_v2 import contracts as historical
from plane.curve.manual_plan_v3.validation import canonical_json
from plane.curve.tests.test_manual_plan_v3 import bundle, validate_bundle

pytestmark = pytest.mark.unit
ID = "30000000-0000-4000-8000-000000000001"
REF = dict(entity_id=ID, digest="sha256:" + "1" * 64)
RATIONALE = dict(object_id=ID, digest="sha256:" + "2" * 64, size_bytes=32, media_type="application/json")


def payload(action="PREPARE"):
    return dict(
        schema_version="curve.manual-gate2.command/v3-candidate",
        action=action,
        draft_revision_id=ID,
        subject_ref=None if action == "PREPARE" else deepcopy(REF),
        rationale_ref=None if action == "PREPARE" else deepcopy(RATIONALE),
        claims=[dict(claim_id=ID, generation=1)] if action in {"RECONCILE", "RELEASE"} else [],
        reconciliation_ref=deepcopy(REF) if action == "RELEASE" else None,
    )


def parse(value, parser=current, **overrides):
    args = dict(
        initiative_id=ID, raw=canonical_json(value), if_match=f'"curve-initiative:{ID}:v10"', key="synthetic-key"
    )
    args.update(overrides)
    return parser.parse_command(**args)


@pytest.mark.parametrize("action", sorted(current.ACTIONS))
def test_each_action_is_exact_versioned_and_detached(action):
    value = payload(action)
    command = parse(value)
    assert command.action == action and command.expected_version == 10
    assert command.payload == value
    value["draft_revision_id"] = "changed"
    assert command.payload["draft_revision_id"] == ID
    assert len(command.request_digest) == 71


@pytest.mark.parametrize("action", sorted(current.ACTIONS))
def test_current_and_historical_commands_cannot_cross_editions(action):
    value = payload(action)
    with pytest.raises(historical.Gate2Error):
        parse(value, historical)
    value["schema_version"] = "curve.manual-gate2.command/v2-candidate"
    assert parse(value, historical).action == action
    with pytest.raises(current.Gate2Error):
        parse(value)


@pytest.mark.parametrize(
    "damage",
    [
        "extra",
        "missing-subject",
        "missing-feedback",
        "unexpected-claims",
        "wrong-generation",
        "duplicate-claims",
        "missing-reconciliation",
        "old-schema",
    ],
)
def test_invalid_decision_inputs_are_rejected(damage):
    value = payload(
        "RELEASE" if damage in {"wrong-generation", "duplicate-claims", "missing-reconciliation"} else "APPROVE"
    )
    if damage == "extra":
        value["code_approver_id"] = ID
    elif damage == "missing-subject":
        value["subject_ref"] = None
    elif damage == "missing-feedback":
        value["rationale_ref"] = None
    elif damage == "unexpected-claims":
        value["claims"] = [dict(claim_id=ID, generation=1)]
    elif damage == "wrong-generation":
        value["claims"][0]["generation"] = True
    elif damage == "duplicate-claims":
        value["claims"] *= 2
    elif damage == "missing-reconciliation":
        value["reconciliation_ref"] = None
    else:
        value["schema_version"] = "curve.manual-gate2.command/v2-candidate"
    with pytest.raises(current.Gate2Error) as error:
        parse(value)
    assert error.value.status == 422


@pytest.mark.parametrize(
    "override", [dict(if_match=None), dict(key=None), dict(if_match='W/"10"'), dict(key="\n"), dict(raw=b"x" * 65537)]
)
def test_preconditions_and_request_size_are_enforced(override):
    with pytest.raises(current.Gate2Error):
        parse(payload(), **override)


@pytest.mark.parametrize("damage", ["bytes", "extra", "missing", "file-link", "manifest-link", "directory-link"])
def test_contract_manifest_rejects_incomplete_or_changed_sources(tmp_path, monkeypatch, damage):
    root = tmp_path / "snapshot"
    shutil.copytree(current.DIRECTORY, root)
    source = current.DIRECTORY
    if damage == "bytes":
        (root / "policy.json").write_bytes((root / "policy.json").read_bytes() + b" ")
    elif damage == "extra":
        (root / "unexpected.json").write_text("{}")
    elif damage == "missing":
        (root / "policy.json").unlink()
    elif damage in {"file-link", "manifest-link"}:
        name = "policy.json" if damage == "file-link" else "manifest.json"
        (root / name).unlink()
        (root / name).symlink_to(source / name)
    else:
        link = tmp_path / "linked"
        link.symlink_to(root, target_is_directory=True)
        root = link
    monkeypatch.setattr(current, "DIRECTORY", root)
    with pytest.raises(current.Gate2Error) as error:
        current.validate_manifest()
    assert error.value.code == "EDITION_UNAVAILABLE" and error.value.status == 503


def embedded(value, suffix):
    if isinstance(value, dict):
        if value.get("$id", "").endswith(suffix):
            return value
        for child in value.values():
            found = embedded(child, suffix)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = embedded(child, suffix)
            if found is not None:
                return found
    return None


def test_embedded_identity_is_exactly_two_stage_and_rejects_code_role():
    schema = json.loads((current.DIRECTORY / "record.schema.json").read_bytes())
    identity_schema = embedded(schema, "manual-plan-input-identity-v3.schema.json")
    assert identity_schema is not None
    definition, identity, facts = bundle()
    validate_bundle(definition, identity, facts)
    validator = Draft202012Validator(identity_schema, format_checker=FormatChecker())
    validator.validate(identity)
    identity["gate_assignments"][0]["gate_type"] = "CODE_READINESS"
    with pytest.raises(ValidationError):
        validator.validate(identity)


def test_embedded_save_accepts_current_profile_and_rejects_old_profile():
    schema = json.loads((current.DIRECTORY / "preparation.schema.json").read_bytes())
    save_schema = embedded(schema, "manual-plan-draft-save-v3.schema.json")
    assert save_schema is not None
    root = Path(__file__).parents[2] / "manual_plan_v2/contract_snapshot/fixtures"
    value = json.loads((root / "save.valid.json").read_bytes())
    old_profile = deepcopy(value["manual_profile_ref"])
    _, identity, _ = bundle()
    value.update(
        schema_version="curve.manual-plan-draft.save/v3-candidate",
        policy_edition="LOCAL_MANUAL_PLAN_DRAFT_RECONSTRUCTION_V3",
        manual_profile_ref=identity["manual_profile_ref"],
    )
    validator = Draft202012Validator(save_schema, format_checker=FormatChecker())
    validator.validate(value)
    value["manual_profile_ref"] = old_profile
    with pytest.raises(ValidationError):
        validator.validate(value)


def test_schemas_are_self_contained_and_policy_retains_quality_boundary():
    current.validate_manifest()
    for path in current.DIRECTORY.glob("*.schema.json"):
        text = path.read_text()
        schema = json.loads(text)
        Draft202012Validator.check_schema(schema)
        assert '"$ref"' not in text and "CODE_READINESS" not in text and "v2-candidate" not in text
    policy = json.loads((current.DIRECTORY / "policy.json").read_bytes())
    assert policy["execution"] is False and policy["completion_credit"] is False
    assert set(policy["actions"]) == current.ACTIONS
