# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Independent closed-edition and raw-input checks for bounded C2b reopening."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import uuid

import pytest

from plane.curve.prd_commands import PrdCommandError
from plane.curve.scope_reopening_contracts import ACTION, POLICY_EDITION, SCHEMA_VERSION
from plane.curve.scope_reopening_services import parse_scope_reopening_body

pytestmark = pytest.mark.contract
ROOT = Path(__file__).parents[1] / "scope_reopening_candidate"
PINNED_MANIFEST = {
    "policy-v1.json": "sha256:598e492b7dc23369eaf3029d7e208b4fd338d03d3e3388fcb10305e9c02b0094",
    "pre-plan-baseline-v1.json": "sha256:f3829e16aa91e055d8bb907477c51b3b5b78ac07e1d58e446cef4b835c2c65bb",
    "scope-proposal-revision-v2.schema.json": "sha256:def7127b3bc5644ce96428dc127a345d87faf8c875a7314fd8b8ac2e716ef7cd",
    "scope-reopening-command-v1.schema.json": "sha256:312af5442338f406230c63f12a1752d7f0e0a0e3e2fba41a76836ef693ab5eb9",
    "scope-reopening-event-v1.schema.json": "sha256:e12b7a83111ecdab7608b7b4880051171f01b5b27ac496864cc058f81a201d5b",
    "scope-reopening-receipt-v1.schema.json": "sha256:84f75afe3baffa50927906abb9c088c9196b3db486688b53c8ff0adaa6d03f75",
}


def payload():
    return dict(
        schema_version=SCHEMA_VERSION,
        policy_edition=POLICY_EDITION,
        expected_scope_revision=1,
        reason="Reconcile the exact remaining outcome",
        items=[
            dict(
                association_id=str(uuid.uuid4()),
                association_version=1,
                source_issue_id=str(uuid.uuid4()),
                purpose="PROPOSED_DELIVERY",
            )
        ],
    )


def parse(value):
    return parse_scope_reopening_body(json.dumps(value).encode())


def test_independently_pinned_closed_packet_and_reopening_only_policy():
    assert SCHEMA_VERSION == "curve.scope-reopening/v1-candidate"
    assert POLICY_EDITION == "EXPLICIT_EXISTING_WORK_SCOPE_REOPENING_V1"
    assert ACTION == "CURVE.SCOPE.REOPEN_AND_REPLACE_SCOPE"
    assert (
        "sha256:" + sha256((ROOT / "manifest-v1.json").read_bytes()).hexdigest()
        == "sha256:a16cca4313a159fb8297c9f7f90afbab5ab99c3574305f8be8ccd44eba2780df"
    )
    assert json.loads((ROOT / "manifest-v1.json").read_text()) == PINNED_MANIFEST
    for name, digest in PINNED_MANIFEST.items():
        assert "sha256:" + sha256((ROOT / name).read_bytes()).hexdigest() == digest
    policy = json.loads((ROOT / "policy-v1.json").read_text())
    assert policy["policy_key"] == "CURVE_SCOPE_REOPENING_POLICY"
    assert len(policy["actions"]) == 1
    assert policy["actions"][0]["action"] == ACTION
    assert policy["actions"][0]["allowed_roles"] == ["PRODUCT_APPROVER"]
    assert policy["actions"][0]["owner_satisfies_acl"] is False


@pytest.mark.parametrize(
    "damage",
    [
        "missing_edition",
        "old_edition",
        "missing_policy",
        "old_policy",
        "extra",
        "missing_revision",
        "zero_revision",
        "bool_revision",
        "float_revision",
        "null_revision",
        "huge_revision",
        "empty",
        "too_many",
        "duplicate_issue",
        "extra_item",
        "invalid_uuid",
        "upper_uuid",
        "bool_association_version",
        "missing_reason",
        "empty_reason",
        "blank_reason",
        "long_reason",
        "nonstring_reason",
    ],
)
def test_closed_command_rejects_invalid_direct_input(damage):
    value = payload()
    if damage == "missing_edition":
        del value["schema_version"]
    elif damage == "old_edition":
        value["schema_version"] = "1.0"
    elif damage == "missing_policy":
        del value["policy_edition"]
    elif damage == "old_policy":
        value["policy_edition"] = "EXPLICIT_EXISTING_WORK_SCOPE_PROPOSAL_V1"
    elif damage == "extra":
        value["permit_reopening"] = True
    elif damage == "missing_revision":
        del value["expected_scope_revision"]
    elif damage.endswith("revision"):
        value["expected_scope_revision"] = {
            "zero_revision": 0,
            "bool_revision": True,
            "float_revision": 1.0,
            "null_revision": None,
            "huge_revision": 9007199254740992,
        }[damage]
    elif damage == "empty":
        value["items"] = []
    elif damage == "too_many":
        value["items"] = [dict(value["items"][0], source_issue_id=str(uuid.uuid4())) for _ in range(101)]
    elif damage == "duplicate_issue":
        value["items"].append(dict(value["items"][0], purpose="CONTEXT_EVIDENCE"))
    elif damage == "extra_item":
        value["items"][0]["include_children"] = True
    elif damage == "invalid_uuid":
        value["items"][0]["source_issue_id"] = "invalid"
    elif damage == "upper_uuid":
        value["items"][0]["source_issue_id"] = "AAAAAAAA-AAAA-4AAA-AAAA-AAAAAAAAAAAA"
    elif damage == "bool_association_version":
        value["items"][0]["association_version"] = True
    elif damage == "missing_reason":
        del value["reason"]
    else:
        value["reason"] = {
            "empty_reason": "",
            "blank_reason": " \t\r\n",
            "long_reason": "x" * 2001,
            "nonstring_reason": 42,
        }[damage]
    with pytest.raises(PrdCommandError):
        parse(value)


@pytest.mark.parametrize(
    "body",
    [
        b"\xff",
        b"[]",
        b"null",
        b"{",
        b'"text"',
        b'{"expected_scope_revision":NaN}',
        b'{"expected_scope_revision":Infinity}',
        b'{"expected_scope_revision":-Infinity}',
    ],
)
def test_malformed_utf8_and_nonfinite_json_fail_closed(body):
    with pytest.raises(PrdCommandError):
        parse_scope_reopening_body(body)


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_json_keys_are_not_normalized_away(nested):
    value = payload()
    body = json.dumps(value)
    if nested:
        body = body.replace('"association_version": 1', '"association_version": 1, "association_version": 1')
    else:
        body = body[:-1] + ', "reason":"substituted"}'
    with pytest.raises(PrdCommandError):
        parse_scope_reopening_body(body.encode())


def test_exact_64k_raw_limit_and_canonical_member_order_preserve_reason_bytes():
    value = payload()
    value["reason"] = "  exact reason é  "
    value["items"].append(dict(value["items"][0], source_issue_id=str(uuid.uuid4())))
    encoded = json.dumps(value).encode()
    valid = parse_scope_reopening_body(encoded + b" " * (65536 - len(encoded)))
    assert valid["reason"] == value["reason"]
    assert valid["items"] == sorted(value["items"], key=lambda item: item["source_issue_id"])
    with pytest.raises(PrdCommandError) as rejected:
        parse_scope_reopening_body(encoded + b" " * (65537 - len(encoded)))
    assert rejected.value.status == 413
    reverse = deepcopy(value)
    reverse["items"].reverse()
    assert parse(reverse) == valid


@pytest.mark.parametrize("body", ["{}", bytearray(b"{}"), None])
def test_parser_requires_raw_bytes(body):
    with pytest.raises(PrdCommandError):
        parse_scope_reopening_body(body)
