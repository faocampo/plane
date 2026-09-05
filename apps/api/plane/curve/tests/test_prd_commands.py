# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from plane.curve.prd_commands import MAX_COMMAND_BYTES, PrdCommandError, check_prd_command_subject, parse_prd_command


pytestmark = pytest.mark.unit
ID = "10000000-0000-4000-8000-000000000001"


def payload(route="approve"):
    if route == "submit":
        return dict(external_document_binding_id=ID, evidence_snapshot_id=ID, completeness_check_id=ID)
    value = dict(
        gate_assignment_id=ID,
        checkpoint_id=ID,
        artifact_version_id=ID,
        content_digest="sha256:" + "a" * 64,
        provider_version="opaque-123",
        evidence_snapshot_id=ID,
        confirmed_risk_tier="STANDARD",
        rationale="Synthetic protected rationale",
    )
    if route == "return-for-revision":
        value["decision"] = "CHANGES_REQUESTED"
    return value


def parse(route="approve", value=None, **overrides):
    args = dict(
        route=route,
        body=json.dumps(payload(route) if value is None else value).encode(),
        if_match='"3"',
        idempotency_key="synthetic-key",
    )
    args.update(overrides)
    return parse_prd_command(**args)


@pytest.mark.parametrize(
    "route,decision,action",
    [
        ("submit", None, "SUBMIT"),
        ("approve", None, "APPROVE"),
        ("return-for-revision", "CHANGES_REQUESTED", "REQUEST_CHANGES"),
        ("return-for-revision", "REJECTED", "REJECT"),
    ],
)
def test_all_routes_resolve_exact_action_without_persisting_rationale(route, decision, action):
    value = payload(route)
    if decision:
        value["decision"] = decision
    command = parse(route, value)
    assert command.action == f"CURVE.PRD.{action}" and command.expected_version == 3
    assert "rationale" not in command.subject_metadata()
    assert "Synthetic protected" not in repr(command)
    assert b"Synthetic protected" not in command.operation_request_identity()
    assert "synthetic-key" not in repr(command)
    assert command.rationale_bytes == (None if route == "submit" else value["rationale"].encode())
    with pytest.raises(FrozenInstanceError):
        command.expected_version = 99
    copy = command.subject_metadata()
    copy.clear()
    assert command.subject_metadata()


@pytest.mark.parametrize("route", ["submit", "approve", "return-for-revision"])
def test_each_required_field_and_every_caller_authority_field_is_rejected(route):
    for key in payload(route):
        value = payload(route)
        del value[key]
        with pytest.raises(PrdCommandError, match="PRD_COMMAND_INVALID"):
            parse(route, value)
    for key in ["actor", "workspace_id", "expected_version", "source_url", "object_acl", "policy_version_ids"]:
        value = payload(route)
        value[key] = "Synthetic protected sentinel"
        with pytest.raises(PrdCommandError) as error:
            parse(route, value)
        assert "sentinel" not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize("value", [None, [], True, 1, "text"])
def test_nonobject_json_is_rejected(value):
    with pytest.raises(PrdCommandError):
        parse(body=json.dumps(value).encode())


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b"\xff",
        b'{"rationale":"first","rationale":"second"}',
        b'{"actor":{"id":1,"id":2}}',
        b"NaN",
        b"Infinity",
        b"[" * 1500 + b"]" * 1500,
    ],
)
def test_raw_json_rejects_duplicates_invalid_encoding_and_excessive_nesting(body):
    with pytest.raises(PrdCommandError, match="PRD_COMMAND_INVALID") as error:
        parse(body=body)
    assert error.value.__suppress_context__


def test_request_byte_limit_and_raw_body_type():
    with pytest.raises(PrdCommandError) as error:
        parse(body=b" " * (MAX_COMMAND_BYTES + 1))
    assert error.value.status == 413
    with pytest.raises(PrdCommandError):
        parse(body=payload())


@pytest.mark.parametrize(
    "etag",
    [
        "",
        'W/"3"',
        "3",
        '"0"',
        '"03"',
        '"-1"',
        "*",
        '"3","4"',
        '"9007199254740992"',
        '"3"\n',
        True,
        '"' + "9" * 5000 + '"',
    ],
)
def test_only_bounded_strong_candidate_etag_is_accepted(etag):
    with pytest.raises(PrdCommandError) as error:
        parse(if_match=etag)
    assert error.value.code == "VERSION_CONFLICT" and error.value.status == 412


def test_missing_precondition_is_distinct_and_maximum_safe_version_works():
    with pytest.raises(PrdCommandError) as error:
        parse(if_match=None)
    assert error.value.status == 428
    assert parse(if_match='"9007199254740991"').expected_version == 9007199254740991


@pytest.mark.parametrize("key", [None, "", " ", "x" * 256, "line\nbreak", "nul\0byte", "del\x7f", True])
def test_idempotency_header_is_bounded_and_not_echoed(key):
    with pytest.raises(PrdCommandError, match="IDEMPOTENCY_KEY_INVALID"):
        parse(idempotency_key=key)


def test_candidate_short_key_is_preserved_exactly():
    assert parse(idempotency_key="k").idempotency_key == "k"
    assert parse(idempotency_key=" key ").idempotency_key == " key "


def test_invalid_unicode_key_fails_before_idempotency_kernel():
    with pytest.raises(PrdCommandError, match="IDEMPOTENCY_KEY_INVALID"):
        parse(idempotency_key="\ud800")


@pytest.mark.parametrize(
    "error",
    [
        ValidationError("PRD_SCHEMA_INTEGRITY_FAILED", code="PRD_SCHEMA_INTEGRITY_FAILED"),
        OSError("Synthetic protected filesystem sentinel"),
    ],
)
def test_unavailable_pinned_contract_is_a_safe_service_failure(monkeypatch, error):
    def unavailable(*_):
        raise error

    monkeypatch.setattr("plane.curve.prd_commands.validate_external_record", unavailable)
    with pytest.raises(PrdCommandError) as caught:
        parse()
    assert caught.value.status == 503 and caught.value.code == "PRD_CONTRACT_UNAVAILABLE"
    assert caught.value.__suppress_context__ and "sentinel" not in str(caught.value)


@pytest.mark.parametrize("rationale", ["", " \t\n", "a" * 2001, "\ud800"])
def test_invalid_rationale_is_rejected_without_diagnostics(rationale):
    value = payload()
    value["rationale"] = rationale
    with pytest.raises(PrdCommandError, match="PRD_COMMAND_INVALID"):
        parse(value=value)


def test_digest_is_canonical_but_preserves_rationale_unicode_and_whitespace():
    value = payload()
    value["rationale"] = "  cafe\u0301 🧪  "
    original = parse(value=value)
    assert original.rationale_bytes == value["rationale"].encode()
    assert (
        original.request_digest
        == parse(body=json.dumps(dict(reversed(list(value.items()))), indent=2).encode()).request_digest
    )
    assert original.request_digest == parse(value=value, idempotency_key="another-key").request_digest
    assert original.request_digest != parse(value=value, if_match='"4"').request_digest
    value["rationale"] = "  café 🧪  "
    assert original.request_digest != parse(value=value).request_digest


@pytest.mark.parametrize(
    "key,value",
    [
        ("checkpoint_id", "foreign"),
        ("provider_version", 123),
        ("provider_version", "https://example.invalid"),
        ("confirmed_risk_tier", "CRITICAL"),
        ("content_digest", "a" * 64),
    ],
)
def test_subject_field_shapes_are_enforced(key, value):
    body = payload()
    body[key] = value
    with pytest.raises(PrdCommandError):
        parse(value=body)


def records(state="PRD_REVIEW"):
    identifier = uuid.UUID(ID)
    initiative = SimpleNamespace(
        id=identifier,
        workspace_id=identifier,
        version=3,
        state=state,
        risk_tier="STANDARD",
        current_prd_checkpoint_id=identifier,
    )
    checkpoint = SimpleNamespace(
        id=identifier,
        workspace_id=identifier,
        initiative_id=identifier,
        artifact_version_id=identifier,
        evidence_snapshot_id=identifier,
        content_digest="sha256:" + "a" * 64,
        provider_version="opaque-123",
    )
    binding = SimpleNamespace(id=identifier, workspace_id=identifier, initiative_id=identifier)
    gate = SimpleNamespace(id=identifier, workspace_id=identifier, initiative_id=identifier, gate_type="PRD_APPROVAL")
    return dict(initiative=initiative, checkpoint=checkpoint, binding=binding, gate_assignment=gate)


@pytest.mark.parametrize("route", ["submit", "approve", "return-for-revision"])
def test_current_exact_subject_passes_but_any_version_change_conflicts(route):
    current = records()
    check_prd_command_subject(command=parse(route), **current)
    current["initiative"].version += 1
    with pytest.raises(PrdCommandError) as error:
        check_prd_command_subject(command=parse(route), **current)
    assert error.value.status == 412


@pytest.mark.parametrize("route", ["submit", "approve", "return-for-revision"])
@pytest.mark.parametrize("state", ["DRAFT", "ALIGNING", "PRD_REVIEW", "PLANNING", "PAUSED", "CANCELLED"])
def test_lifecycle_state_matrix(route, state):
    allowed = state == "PRD_REVIEW" or (route == "submit" and state == "ALIGNING")
    if allowed:
        check_prd_command_subject(command=parse(route), **records(state))
    else:
        with pytest.raises(PrdCommandError, match="PRD_STATE_CONFLICT"):
            check_prd_command_subject(command=parse(route), **records(state))


@pytest.mark.parametrize(
    "record,attribute",
    [
        ("initiative", "current_prd_checkpoint_id"),
        ("initiative", "risk_tier"),
        ("checkpoint", "workspace_id"),
        ("checkpoint", "initiative_id"),
        ("checkpoint", "id"),
        ("checkpoint", "artifact_version_id"),
        ("checkpoint", "content_digest"),
        ("checkpoint", "provider_version"),
        ("checkpoint", "evidence_snapshot_id"),
        ("gate_assignment", "id"),
        ("gate_assignment", "workspace_id"),
        ("gate_assignment", "initiative_id"),
        ("gate_assignment", "gate_type"),
    ],
)
def test_delayed_review_cannot_act_on_replaced_checkpoint_or_assignment(record, attribute):
    current = records()
    setattr(current[record], attribute, "changed")
    for route in ["approve", "return-for-revision"]:
        with pytest.raises(PrdCommandError, match="PRD_SUBJECT_CONFLICT"):
            check_prd_command_subject(command=parse(route), **current)


@pytest.mark.parametrize("attribute", ["id", "workspace_id", "initiative_id"])
def test_submission_binding_must_match_current_same_tenant_initiative(attribute):
    current = records("ALIGNING")
    setattr(current["binding"], attribute, uuid.uuid4())
    with pytest.raises(PrdCommandError, match="PRD_SUBJECT_CONFLICT"):
        check_prd_command_subject(command=parse("submit"), **current)
