# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
from dataclasses import replace, FrozenInstanceError

import pytest

from plane.curve.prd_readiness import (
    ReadinessCapture,
    PrdReadinessError,
    evaluate_prd_readiness,
    readiness_profile,
    require_current_prd_readiness,
    SUBJECT_FIELDS,
)
from plane.curve.providers.google_docs_normalization import normalize_google_document

pytestmark = pytest.mark.unit


def paragraph(text, style=None):
    return {
        "paragraph": {
            "elements": [{"textRun": {"content": text}}],
            **({"paragraphStyle": {"namedStyleType": style}} if style else {}),
        }
    }


def capture(sections, file_id, **kwargs):
    nodes = []
    for label in sections.values():
        text = (
            "FR-1: Support synthetic onboarding"
            if label == "Requirements"
            else "AC-1: Verify synthetic FR-1"
            if label == "Acceptance"
            else "Synthetic protected definition content"
        )
        nodes.extend([paragraph(label, "HEADING_1"), paragraph(text)])
    document = {
        "documentId": file_id,
        "title": "Synthetic definition",
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
        "tabs": [
            {"tabProperties": {"tabId": "main", "title": "Definition"}, "documentTab": {"body": {"content": nodes}}}
        ],
    }
    value = normalize_google_document(
        response_bytes=json.dumps(document).encode(),
        expected_document_id=file_id,
        read_options={"includeTabsContent": True, "suggestionsViewMode": "SUGGESTIONS_INLINE"},
        image_captures={},
        max_document_bytes=1000000,
        max_image_bytes=10000,
    ).content
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return ReadinessCapture(
        "synthetic-workspace",
        "synthetic-initiative",
        file_id,
        raw,
        "sha256:" + hashlib.sha256(raw).hexdigest(),
        **kwargs,
    )


@pytest.fixture
def scenario():
    profile = readiness_profile()
    prd = capture(
        profile["prd_sections"], "synthetic-prd", binding_id="synthetic-binding", provider_version="9007199254740993"
    )
    brief = capture(profile["idea_brief_sections"], "synthetic-brief", artifact_version_id="synthetic-brief-version")
    return dict(
        id="synthetic-readiness",
        workspace_id=prd.workspace_id,
        initiative_id=prd.initiative_id,
        initiative_version=2,
        prd=prd,
        idea_brief=brief,
        evidence_snapshot_id="synthetic-evidence",
        active_human_ids=["synthetic-author"],
        checked_at="2026-01-01T00:00:00Z",
        max_document_bytes=1000000,
        inventory=dict(
            workspace_id=prd.workspace_id,
            initiative_id=prd.initiative_id,
            prd_digest=prd.content_digest,
            idea_brief_digest=brief.content_digest,
            checked_at="2026-01-01T00:00:00Z",
            complete=True,
            blockers=[],
            assumptions=[],
        ),
    )


def mutate(scenario, kind, callback, refresh=True):
    original = scenario[kind]
    content = json.loads(original.content_bytes)
    callback(content)
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    scenario[kind] = replace(original, content_bytes=raw, content_digest="sha256:" + hashlib.sha256(raw).hexdigest())
    if refresh:
        scenario["inventory"]["prd_digest" if kind == "prd" else "idea_brief_digest"] = scenario[kind].content_digest


def body(content):
    return content["tabs"][0]["documentTab"]["body"]["content"]


def test_complete_capture_has_immutable_metadata_only_report(scenario):
    report = evaluate_prd_readiness(**scenario)
    result = report.as_dict()
    assert result["status"] == "READY" and result["reasons"] == []
    assert "protected definition" not in json.dumps(result)
    assert "protected definition" not in repr(report) + repr(scenario["prd"])
    assert require_current_prd_readiness(result, {field: result[field] for field in SUBJECT_FIELDS})
    result["reasons"].append("mutated")
    assert report.as_dict()["reasons"] == []
    with pytest.raises(FrozenInstanceError):
        report._encoded = b"{}"


@pytest.mark.parametrize("kind", ["prd", "idea_brief"])
@pytest.mark.parametrize("mode", ["missing", "empty", "placeholder", "punctuated", "duplicate"])
def test_required_section_failures(scenario, kind, mode):
    def edit(value):
        nodes = body(value)
        if mode == "missing":
            del nodes[:2]
        elif mode == "duplicate":
            nodes.extend([nodes[0], paragraph("Synthetic duplicate")])
        else:
            nodes[1] = paragraph({"empty": " \n", "placeholder": "TBD", "punctuated": "N/A."}[mode])

    mutate(scenario, kind, edit)
    result = evaluate_prd_readiness(**scenario).as_dict()
    assert result["status"] == "BLOCKED"
    assert any(reason.startswith(kind.upper() + "_SECTION_") for reason in result["reasons"])
    with pytest.raises(PrdReadinessError, match="PRD_READINESS_REQUIRED"):
        require_current_prd_readiness(result, {field: result[field] for field in SUBJECT_FIELDS})


@pytest.mark.parametrize(
    "section,text,reason",
    [
        ("Requirements", "Description", "PRD_REQUIREMENT_ID_REQUIRED"),
        ("Requirements", "FR-1: TBD", "PRD_REQUIREMENT_EMPTY"),
        ("Requirements", "FR-1: First\nFR-1: Duplicate", "PRD_REQUIREMENT_DUPLICATE"),
        ("Requirements", "FR-1: First\nFR-2: Uncovered", "PRD_REQUIREMENT_UNCOVERED"),
        ("Acceptance", "Criterion", "PRD_ACCEPTANCE_ID_REQUIRED"),
        ("Acceptance", "AC-1: TBD", "PRD_ACCEPTANCE_EMPTY"),
        ("Acceptance", "AC-1: Verify FR-1\nAC-1: Duplicate FR-1", "PRD_ACCEPTANCE_DUPLICATE"),
        ("Acceptance", "AC-1: No reference", "PRD_ACCEPTANCE_TRACE_REQUIRED"),
        ("Acceptance", "AC-1: Unknown FR-2", "PRD_ACCEPTANCE_UNKNOWN_REQUIREMENT"),
    ],
)
def test_traceability(scenario, section, text, reason):
    def edit(content):
        nodes = body(content)
        index = next(
            i for i, node in enumerate(nodes) if node["paragraph"]["elements"][0]["textRun"]["content"] == section
        )
        nodes[index + 1] = paragraph(text)

    mutate(scenario, "prd", edit)
    assert reason in evaluate_prd_readiness(**scenario).as_dict()["reasons"]


def test_nested_headings_tables_and_section_tabs(scenario):
    def edit(content):
        nodes = body(content)
        nodes.insert(1, paragraph("Supporting detail", "HEADING_2"))
        nodes[2] = {"table": {"tableRows": [{"tableCells": [{"content": [paragraph("Synthetic detail")]}]}]}}
        removed = nodes[:3]
        del nodes[:3]
        content["tabs"].append(
            {
                "tabProperties": {"tabId": "summary", "title": "Executive summary"},
                "documentTab": {"body": {"content": []}},
                "childTabs": [
                    {
                        "tabProperties": {"tabId": "details", "title": "Details"},
                        "documentTab": {"body": {"content": [removed[2]]}},
                    }
                ],
            }
        )

    mutate(scenario, "prd", edit)
    assert evaluate_prd_readiness(**scenario).as_dict()["status"] == "READY"


def test_toc_and_footnotes_cannot_supply_body_section(scenario):
    def edit(content):
        nodes = body(content)
        removed = nodes[:2]
        del nodes[:2]
        nodes.append({"tableOfContents": {"content": removed}})
        content["tabs"][0]["documentTab"]["footnotes"] = {"note": {"content": removed}}

    mutate(scenario, "prd", edit)
    assert "PRD_SECTION_MISSING:executive_summary" in evaluate_prd_readiness(**scenario).as_dict()["reasons"]


@pytest.mark.parametrize("field", sorted(SUBJECT_FIELDS))
def test_every_subject_field_is_mandatory_and_exact(scenario, field):
    report = evaluate_prd_readiness(**scenario).as_dict()
    expected = {key: report[key] for key in SUBJECT_FIELDS}
    del expected[field]
    with pytest.raises(PrdReadinessError, match="PRD_READINESS_REQUIRED"):
        require_current_prd_readiness(report, expected)
    expected[field] = 99 if field == "initiative_version" else "different"
    with pytest.raises(PrdReadinessError, match="PRD_READINESS_STALE"):
        require_current_prd_readiness(report, expected)


@pytest.mark.parametrize("kind", ["prd", "idea_brief"])
@pytest.mark.parametrize("field", ["workspace_id", "initiative_id", "provider_file_id", "content_digest"])
def test_capture_scope_and_bytes_are_bound(scenario, kind, field):
    scenario[kind] = replace(scenario[kind], **{field: "synthetic-other"})
    with pytest.raises(PrdReadinessError):
        evaluate_prd_readiness(**scenario)


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete", False),
        ("workspace_id", "other"),
        ("initiative_id", "other"),
        ("prd_digest", "other"),
        ("idea_brief_digest", "other"),
        ("checked_at", "2026-01-01T00:00:01Z"),
    ],
)
def test_inventory_must_be_current(scenario, field, value):
    scenario["inventory"][field] = value
    assert "READINESS_INVENTORY_STALE" in evaluate_prd_readiness(**scenario).as_dict()["reasons"]


@pytest.mark.parametrize("kind", ["prd", "idea_brief"])
def test_document_edit_requires_new_inventory(scenario, kind):
    mutate(
        scenario,
        kind,
        lambda content: body(content).__setitem__(1, paragraph("Changed synthetic outcome")),
        refresh=False,
    )
    assert "READINESS_INVENTORY_STALE" in evaluate_prd_readiness(**scenario).as_dict()["reasons"]


def test_blocker_resolution_and_owned_assumption_plans(scenario):
    inventory = scenario["inventory"]
    inventory["blockers"] = [{"id": "synthetic-blocker", "state": "OPEN", "resolution_ref": None}]
    inventory["assumptions"] = [
        {"id": "synthetic-assumption", "owner_actor_id": "inactive", "validation_plan_ref": None, "due_stage": None}
    ]
    report = evaluate_prd_readiness(**scenario).as_dict()
    assert "BLOCKERS_UNRESOLVED" in report["reasons"] and "ASSUMPTION_PLAN_REQUIRED" in report["reasons"]
    inventory["blockers"][0].update(state="RESOLVED", resolution_ref="synthetic-resolution")
    inventory["assumptions"][0].update(
        owner_actor_id="synthetic-author", validation_plan_ref="synthetic-plan", due_stage="PLANNING"
    )
    assert evaluate_prd_readiness(**scenario).as_dict()["status"] == "READY"
    inventory["assumptions"][0]["id"] = "synthetic-blocker"
    assert "READINESS_INVENTORY_INVALID" in evaluate_prd_readiness(**scenario).as_dict()["reasons"]


@pytest.mark.parametrize(
    "field,value", [("blockers", [None]), ("raw_body", "synthetic private sentinel"), ("assumptions", [{}])]
)
def test_inventory_has_closed_metadata_shape(scenario, field, value):
    scenario["inventory"][field] = value
    with pytest.raises(PrdReadinessError, match="^READINESS_INVENTORY_INVALID$"):
        evaluate_prd_readiness(**scenario)


def test_report_injection_profile_substitution_and_boolean_version_fail(scenario):
    report = evaluate_prd_readiness(**scenario).as_dict()
    expected = {key: report[key] for key in SUBJECT_FIELDS}
    for field, value in (("raw_body", "synthetic"), ("profile_digest", "unknown"), ("initiative_version", True)):
        with pytest.raises(PrdReadinessError, match="PRD_READINESS_REQUIRED"):
            require_current_prd_readiness({**report, field: value}, expected)


@pytest.mark.parametrize("raw", [b'{"complete":true,"complete":false}', b"\xff", b"null"])
def test_invalid_protected_json_fails_without_content(scenario, raw):
    scenario["prd"] = replace(
        scenario["prd"], content_bytes=raw, content_digest="sha256:" + hashlib.sha256(raw).hexdigest()
    )
    with pytest.raises(PrdReadinessError, match="READINESS_CAPTURE_REQUIRED"):
        evaluate_prd_readiness(**scenario)


def test_profile_integrity_is_enforced_and_limits_are_required(scenario, monkeypatch):
    from plane.curve import prd_readiness

    with pytest.raises(PrdReadinessError, match="READINESS_CAPTURE_LIMIT_EXCEEDED"):
        evaluate_prd_readiness(**{**scenario, "max_document_bytes": 1})
    monkeypatch.setattr(prd_readiness, "PROFILE_SHA256", "0" * 64)
    with pytest.raises(PrdReadinessError, match="READINESS_PROFILE_INVALID"):
        evaluate_prd_readiness(**scenario)


@pytest.mark.parametrize(
    "node", [{"canvas": {}}, {"paragraph": {}, "table": {}}, {"paragraph": {"elements": [{"equation": {}}]}}]
)
def test_unsupported_body_structures_cannot_be_ignored(scenario, node):
    mutate(scenario, "prd", lambda content: body(content).append(node))
    with pytest.raises(PrdReadinessError, match="READINESS_CAPTURE_REQUIRED"):
        evaluate_prd_readiness(**scenario)


@pytest.mark.parametrize(
    "checked_at", ["2026-01-01T00:00:60Z", "2026-02-30T00:00:00Z", "2026-01-01T00:00:00+00:00", None]
)
def test_readiness_timestamp_is_strict(scenario, checked_at):
    with pytest.raises(PrdReadinessError, match="READINESS_CONTEXT_INVALID"):
        evaluate_prd_readiness(**{**scenario, "checked_at": checked_at})
