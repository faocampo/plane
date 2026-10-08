# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Pure metadata and trusted-adapter conformance; no database/provider access."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plane.curve.prd_read_context import (
    PrdReadUnavailable,
    READ_ACTION,
    READ_POLICY_KEY,
    READ_POLICY_DIGEST,
    read_prd_review_context,
    validate_review_context,
)
from plane.curve.prd_readiness import SUBJECT_FIELDS

pytestmark = pytest.mark.unit
NOW = "2026-10-02T12:00:00.000Z"
CHECKED = "2026-10-02T11:00:00.000Z"


def uid(value):
    return f"00000000-0000-4000-8000-{value:012d}"


def digest(value):
    return "sha256:" + value * 64


class Runtime:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []
        self.on_observe = None
        self.fence = True

    def observe(self, *, scope, evaluated_at):
        self.calls.append("authorize")
        result = {
            **scope,
            "action": READ_ACTION,
            "policy_key": READ_POLICY_KEY,
            "policy_digest": READ_POLICY_DIGEST,
            "snapshot_revision": self.snapshot["snapshot_revision"],
            "evaluated_at": evaluated_at,
            "classification": "INTERNAL",
            "explicit_deny": False,
            **{
                key: "ALLOW"
                for key in (
                    "membership",
                    "classification_access",
                    "object_metadata",
                    "source_metadata",
                    "evidence_metadata",
                )
            },
        }
        return self.on_observe(result, self.calls.count("authorize")) if self.on_observe else result

    def read_metadata(self, **kwargs):
        self.calls.append("read")
        return self.snapshot

    def is_current(self, **kwargs):
        self.calls.append("fence")
        return self.fence

    def capture(self, *args, **kwargs):
        pytest.fail("A read invoked capture")

    append_readiness = create_operation = accept_command = capture


@pytest.fixture
def context():
    snapshot = json.loads((Path(__file__).parent / "fixtures/prd_review_context.json").read_text())
    scope = {key: snapshot[key] for key in ("workspace_id", "initiative_id", "initiative_version")}
    scope["actor_id"] = uid(3)
    runtime = Runtime(snapshot)
    return SimpleNamespace(snapshot=snapshot, scope=scope, runtime=runtime, clock=lambda: NOW)


def read(context, **kwargs):
    return read_prd_review_context(
        resolve_scope=kwargs.get("resolve_scope", lambda: deepcopy(context.scope)),
        runtime=kwargs.get("runtime", context.runtime),
        clock=kwargs.get("clock", context.clock),
    )


def denied(context, **kwargs):
    with pytest.raises(PrdReadUnavailable, match="^PRD_CONTEXT_UNAVAILABLE$") as result:
        read(context, **kwargs)
    assert str(result.value) == "PRD_CONTEXT_UNAVAILABLE"


def decision(context, edition="2.0-candidate"):
    s = context.snapshot
    cp = s["checkpoint"]["metadata"]
    s["state"] = "ALIGNING"
    s["controlling_decision_id"] = uid(26)
    s["decision_assignment"] = deepcopy(s["assignments"][0])
    s["decision"] = {
        "availability": "PRESENT",
        "metadata": {
            "id": uid(26),
            "metadata_schema_version": edition,
            "workspace_id": s["workspace_id"],
            "initiative_id": s["initiative_id"],
            "state": "CHANGES_REQUESTED",
            "gate_assignment_id": uid(10),
            "checkpoint_id": cp["id"],
            **{
                key: cp[key]
                for key in ("artifact_version_id", "evidence_snapshot_id", "content_digest", "provider_version")
            },
            "confirmed_risk_tier": "STANDARD",
            "decided_by": {"actor_type": "HUMAN", "actor_id": uid(3)},
            "provider_validation_cutoff": "2026-10-02T11:10:00.000Z",
            "decided_at": "2026-10-02T11:15:00.000Z",
        },
    }


def test_authorized_read_is_exact_closed_no_mutation(context):
    original = deepcopy(context.snapshot)
    result = read(context)
    assert validate_review_context(result) is True
    assert context.runtime.calls == ["authorize", "read", "authorize", "fence"]
    assert context.snapshot == original
    assert result["checkpoint"]["metadata"]["id"] == context.snapshot["current_checkpoint_id"]
    assert result["readiness"]["metadata"]["checked_at"] == CHECKED
    assert result["observed_at"] == NOW
    assert result["readiness"]["metadata"]["applicability"] == "CURRENT"
    assert result["reviewer"]["requesting_human_is_reviewer"] is True
    assert all(not item["available"] for item in result["capabilities"].values())
    result["checkpoint"]["metadata"]["id"] = uid(99)
    assert context.snapshot == original


@pytest.mark.parametrize(
    "field", ["membership", "classification_access", "object_metadata", "source_metadata", "evidence_metadata"]
)
@pytest.mark.parametrize("value", ["DENY", "UNKNOWN", None, True])
def test_current_checks_fail_closed_before_read(context, field, value):
    context.runtime.on_observe = lambda result, _: {**result, field: value}
    denied(context)
    assert context.runtime.calls == ["authorize"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "CURVE.PRD.SUBMIT"),
        ("action", "CURVE.INITIATIVE.READ"),
        ("classification", "UNKNOWN"),
        ("policy_digest", digest("f")),
        ("policy_key", "OTHER"),
        ("explicit_deny", True),
        ("workspace_id", uid(99)),
        ("initiative_id", uid(99)),
        ("actor_id", uid(99)),
        ("initiative_version", 8),
        ("initiative_version", True),
        ("evaluated_at", CHECKED),
    ],
)
def test_authority_is_current_scoped_and_exact(context, field, value):
    context.runtime.on_observe = lambda result, _: {**result, field: value}
    denied(context)
    assert "read" not in context.runtime.calls


@pytest.mark.parametrize("field", ["owner", "administrator", "rationale", "permission_topology"])
def test_extra_authority_claims_are_not_accepted(context, field):
    context.runtime.on_observe = lambda result, _: {**result, field: True}
    denied(context)


def test_no_runtime_fails_without_scope_read(context):
    def must_not_resolve():
        pytest.fail("Unconfigured runtime resolved an object")

    denied(context, runtime=None, resolve_scope=must_not_resolve)


def test_resolver_errors_are_redacted(context):
    def fail(**kwargs):
        raise ValueError("Synthetic protected diagnostic sentinel")

    context.runtime.observe = fail
    denied(context)
    assert "read" not in context.runtime.calls


@pytest.mark.parametrize("field", ["source_metadata", "evidence_metadata", "membership", "object_metadata"])
def test_revocation_at_final_fence(context, field):
    context.runtime.on_observe = lambda result, n: {**result, field: "DENY"} if n == 2 else result
    denied(context)
    assert context.runtime.calls == ["authorize", "read", "authorize"]


def test_scope_membership_loss_at_final_fence(context):
    calls = 0

    def scope():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PrdReadUnavailable
        return context.scope

    denied(context, resolve_scope=scope)


@pytest.mark.parametrize("field", ["actor_id", "workspace_id", "initiative_id", "initiative_version"])
def test_local_scope_change_at_final_fence(context, field):
    calls = 0

    def scope():
        nonlocal calls
        calls += 1
        return (
            {**context.scope, field: (8 if field == "initiative_version" else uid(99))} if calls == 2 else context.scope
        )

    denied(context, resolve_scope=scope)


@pytest.mark.parametrize("value", [False, None, 1, "ALLOW"])
def test_final_fence_requires_true(context, value):
    context.runtime.fence = value
    denied(context)


def test_snapshot_revision_change_is_not_accepted(context):
    context.runtime.on_observe = lambda result, n: {**result, "snapshot_revision": "changed"} if n == 2 else result
    denied(context)


@pytest.mark.parametrize("section", ["binding", "checkpoint", "readiness", "decision"])
@pytest.mark.parametrize("field", ["workspace_id", "initiative_id"])
def test_cross_scope_metadata_is_not_exposed(context, section, field):
    decision(context)
    context.snapshot[section]["metadata"][field] = uid(99)
    denied(context)


@pytest.mark.parametrize("field", sorted(SUBJECT_FIELDS))
def test_exact_readiness_subject_comparison(context, field):
    s = context.snapshot
    current = s["current_readiness_subject"]
    if field in {"workspace_id", "initiative_id", "id"}:
        current[field] = uid(99)
        denied(context)
        return
    if field == "initiative_version":
        current[field] = s[field] = context.scope[field] = 8
    elif field == "prd_binding_id":
        current[field] = s["binding"]["metadata"]["id"] = s["checkpoint"]["metadata"][
            "external_document_binding_id"
        ] = uid(99)
    elif field == "provider_file_id":
        current[field] = s["binding"]["metadata"][field] = s["checkpoint"]["metadata"][field] = "synthetic-new-file"
    elif field == "provider_version":
        current[field] = s["binding"]["metadata"]["current_provider_version"] = "5"
    elif field.endswith("digest"):
        current[field] = digest("d")
    elif field == "checked_at":
        current[field] = "2026-10-02T11:01:00.000Z"
    else:
        current[field] = uid(99)
    report = read(context)["readiness"]["metadata"]
    assert report["status"] == "READY"
    assert report["applicability"] == "STALE"
    assert report["ready_for_submission"] is False


def test_post_submit_version_change_does_not_invalidate_checkpoint_review(context):
    context.snapshot["readiness"]["metadata"]["initiative_version"] = 6
    result = read(context)
    assert result["readiness"]["metadata"]["applicability_scope"] == "NEW_SUBMISSION"
    assert result["readiness"]["metadata"]["applicability"] == "STALE"
    assert result["command_preconditions"]["commandETag"] == '"7"'
    assert result["capabilities"]["approve"]["reason_codes"] == ["COMMAND_RUNTIME_NOT_EVALUATED"]


def test_blocked_can_be_current(context):
    context.snapshot["readiness"]["metadata"].update(status="BLOCKED", reasons=["BLOCKERS_UNRESOLVED"])
    report = read(context)["readiness"]["metadata"]
    assert report["applicability"] == "CURRENT" and report["ready_for_submission"] is False


def test_changed_current_profile_is_stale(context):
    context.snapshot["current_profile_digest"] = digest("d")
    assert read(context)["readiness"]["metadata"]["applicability_reasons"] == ["PROFILE_CHANGED"]


@pytest.mark.parametrize("field", ["current_readiness_subject", "current_profile_digest"])
def test_missing_current_observations_are_unverified(context, field):
    context.snapshot[field] = None
    assert read(context)["readiness"]["metadata"]["applicability"] == "UNVERIFIED"


@pytest.mark.parametrize("status", ["CHANGED_SINCE_SUBMISSION", "PROVIDER_UNAVAILABLE", "RECONCILIATION_REQUIRED"])
def test_source_status_does_not_impose_approval_only_rules_on_negative_outcomes(context, status):
    context.snapshot["binding"]["metadata"]["synchronization_status"] = status
    result = read(context)
    assert result["readiness"]["metadata"]["applicability"] == "UNVERIFIED"
    for name in ("request_changes", "reject"):
        assert result["capabilities"][name]["reason_codes"] == ["COMMAND_RUNTIME_NOT_EVALUATED"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("valid_from", "2026-10-03T00:00:00.000Z"),
        ("valid_until", NOW),
        ("valid_until", CHECKED),
        ("member_active", False),
    ],
)
def test_all_assignments_must_be_active_in_half_open_window(context, field, value):
    context.snapshot["assignments"][1][field] = value
    reviewer = read(context)["reviewer"]
    assert reviewer["validity"] == "INVALID" and reviewer["requesting_human_is_reviewer"] is False


@pytest.mark.parametrize("risk", ["LOW", "STANDARD", "HIGH"])
def test_risk_separation_retains_exact_existing_rules(context, risk):
    context.snapshot["risk_tier"] = risk
    for assignment in context.snapshot["assignments"]:
        assignment["approver"]["actor_id"] = uid(3)
    assert read(context)["reviewer"]["validity"] == ("VALID" if risk == "LOW" else "INVALID")


@pytest.mark.parametrize("risk", ["LOW", "STANDARD", "HIGH"])
def test_duplicate_assignment_ids_are_invalid(context, risk):
    context.snapshot["risk_tier"] = risk
    context.snapshot["assignments"][1]["id"] = uid(10)
    assert read(context)["reviewer"]["validity"] == "INVALID"


@pytest.mark.parametrize("field", ["id", "actor_id"])
def test_uuid_aliases_cannot_bypass_identity_uniqueness(context, field):
    same = "abcdefab-cdef-4abc-8def-abcdefabcdef"
    for i, assignment in enumerate(context.snapshot["assignments"]):
        target = assignment if field == "id" else assignment["approver"]
        target[field] = same if i == 0 else same.upper()
    denied(context)


@pytest.mark.parametrize("risk", [None, "UNKNOWN", "MINIMAL"])
def test_unknown_risk_has_no_overlap_exception(context, risk):
    context.snapshot["risk_tier"] = risk
    denied(context)


@pytest.mark.parametrize("edition", ["1.0", "2.0"])
def test_preserve_checkpoint_editions(context, edition):
    context.snapshot["checkpoint"]["metadata"]["metadata_schema_version"] = edition
    assert read(context)["checkpoint"]["metadata"]["metadata_schema_version"] == edition


@pytest.mark.parametrize("edition", ["1.0-candidate", "2.0-candidate"])
def test_preserve_decision_edition_and_historical_assignment(context, edition):
    decision(context, edition)
    context.snapshot["decision_assignment"]["member_active"] = False
    context.snapshot["assignments"][0]["id"] = uid(97)
    context.snapshot["assignments"][0]["approver"]["actor_id"] = uid(98)
    result = read(context)
    assert result["decision"]["metadata"]["metadata_schema_version"] == edition
    assert result["decision"]["metadata"]["gate_assignment_id"] == uid(10)
    assert result["reviewer"]["assignment_id"] == uid(97)


@pytest.mark.parametrize(
    "field", ["checkpoint_id", "artifact_version_id", "evidence_snapshot_id", "content_digest", "provider_version"]
)
def test_decision_exact_checkpoint_pins(context, field):
    decision(context)
    context.snapshot["decision"]["metadata"][field] = (
        digest("d") if field == "content_digest" else "5" if field == "provider_version" else uid(99)
    )
    denied(context)


def test_latest_history_cannot_replace_current_pointer(context):
    context.snapshot["checkpoint"]["metadata"].update(id=uid(99), checkpoint_number=99)
    denied(context)


def test_prd_review_requires_current_checkpoint_without_terminal_decision(context):
    context.snapshot["checkpoint"] = {"availability": "UNAVAILABLE", "metadata": None}
    assert read(context)["checkpoint"]["availability"] == "UNAVAILABLE"
    context.snapshot["current_checkpoint_id"] = None
    context.snapshot["checkpoint"]["availability"] = "ABSENT"
    denied(context)


def test_prd_review_cannot_already_have_terminal_decision(context):
    decision(context)
    context.snapshot["state"] = "PRD_REVIEW"
    denied(context)


@pytest.mark.parametrize(
    "field",
    [
        "rationale",
        "rationale_ref",
        "body",
        "normalized_content_ref",
        "access_envelope_id",
        "canonical_url",
        "title",
        "provider_container_id",
    ],
)
def test_no_unknown_protected_fields_on_either_side(context, field):
    decision(context)
    result = read(context)
    result["decision"]["metadata"][field] = "Synthetic protected sentinel"
    with pytest.raises(PrdReadUnavailable):
        validate_review_context(result)
    context.snapshot["decision"]["metadata"][field] = "Synthetic protected sentinel"
    denied(context)


@pytest.mark.parametrize(
    "etag", ["7", 'W/"7"', '"07"', "*", '"curve-initiative:synthetic:v7"', '"8"', '"9007199254740992"']
)
def test_wrong_etag_never_passes(context, etag):
    result = read(context)
    result["command_preconditions"]["commandETag"] = etag
    with pytest.raises(PrdReadUnavailable):
        validate_review_context(result)


@pytest.mark.parametrize("version", [1, 7, 9007199254740991])
def test_numeric_etag_uses_current_aggregate_version(context, version):
    context.scope["initiative_version"] = context.snapshot["initiative_version"] = version
    context.snapshot["current_readiness_subject"]["initiative_version"] = version
    assert read(context)["command_preconditions"]["commandETag"] == f'"{version}"'


@pytest.mark.parametrize("version", [0, -1, True, "7", 1.5, 9007199254740992])
def test_invalid_aggregate_version_fails_closed(context, version):
    context.scope["initiative_version"] = version
    denied(context)


def test_repeated_reads_do_not_mutate_or_dispatch(context):
    original = deepcopy(context.snapshot)
    assert read(context) == read(context)
    assert context.snapshot == original
    assert set(context.runtime.calls) == {"authorize", "read", "fence"}


def test_closed_response_semantics(context):
    result = read(context)
    for change in (
        lambda r: r["readiness"]["metadata"].update(reasons=["protected arbitrary rationale"]),
        lambda r: r["readiness"]["metadata"].update(status="BLOCKED", ready_for_submission=False),
        lambda r: r["readiness"]["metadata"].update(applicability_reasons=[]),
        lambda r: r["reviewer"].update(identity=None),
        lambda r: r["capabilities"]["approve"].update(reason_codes=[]),
    ):
        altered = deepcopy(result)
        change(altered)
        with pytest.raises(PrdReadUnavailable):
            validate_review_context(altered)


@pytest.mark.parametrize(
    "field", ["checkpoint_id", "artifact_version_id", "evidence_snapshot_id", "provider_version", "content_digest"]
)
def test_response_validator_rejects_decision_checkpoint_pin_mismatch(context, field):
    decision(context)
    result = read(context)
    result["decision"]["metadata"][field] = (
        digest("e") if field == "content_digest" else "5" if field == "provider_version" else uid(99)
    )
    with pytest.raises(PrdReadUnavailable):
        validate_review_context(result)


@pytest.mark.parametrize("availability", ["ABSENT", "UNAVAILABLE"])
def test_response_validator_requires_displayed_checkpoint_for_decision(context, availability):
    decision(context)
    result = read(context)
    result["checkpoint"] = {"availability": availability, "metadata": None}
    with pytest.raises(PrdReadUnavailable):
        validate_review_context(result)
