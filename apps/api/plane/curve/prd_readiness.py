# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Exact-byte structural readiness; trusted runtime reads supply all authority."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from plane.curve.prd_metadata_validation import metadata_digest
from plane.curve.providers.google_docs_normalization import STRUCTURAL_TYPES, PARAGRAPH_TYPES

PROFILE_PATH = Path(__file__).parent / "prd_candidate_policy/prd-readiness-profile-v1.json"
PROFILE_SHA256 = "96b7c67dd686d52adcad5fad6c937c843468007362bcc8da0c728bdcd4086577"
SUBJECT_FIELDS = {
    "id",
    "workspace_id",
    "initiative_id",
    "initiative_version",
    "prd_binding_id",
    "provider_file_id",
    "provider_version",
    "content_digest",
    "idea_brief_version_id",
    "idea_brief_digest",
    "evidence_snapshot_id",
    "inventory_digest",
    "checked_at",
}
REPORT_FIELDS = SUBJECT_FIELDS | {"schema_version", "profile_digest", "status", "reasons"}
INVENTORY_FIELDS = {
    "workspace_id",
    "initiative_id",
    "prd_digest",
    "idea_brief_digest",
    "checked_at",
    "complete",
    "blockers",
    "assumptions",
}
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PrdReadinessError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class ReadinessCapture:
    workspace_id: str
    initiative_id: str
    provider_file_id: str
    content_bytes: bytes
    content_digest: str
    binding_id: str | None = None
    provider_version: str | None = None
    artifact_version_id: str | None = None


@dataclass(frozen=True, repr=False)
class ReadinessReport:
    _encoded: bytes

    def as_dict(self):
        return json.loads(self._encoded)


def _require(value, code):
    if not value:
        raise PrdReadinessError(code)


def _reference(value):
    return type(value) is str and REF.fullmatch(value) is not None


def _closed(value, fields):
    return type(value) is dict and set(value) == set(fields)


def _time(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z", value):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def readiness_profile():
    try:
        _require(not PROFILE_PATH.is_symlink(), "READINESS_PROFILE_INVALID")
        data = PROFILE_PATH.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == PROFILE_SHA256, "READINESS_PROFILE_INVALID")
        return json.loads(data)
    except (OSError, ValueError):
        raise PrdReadinessError("READINESS_PROFILE_INVALID") from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "READINESS_CAPTURE_REQUIRED")
        result[key] = value
    return result


def _capture(capture, workspace_id, initiative_id, limit):
    _require(type(capture) is ReadinessCapture, "READINESS_CAPTURE_REQUIRED")
    _require(
        capture.workspace_id == workspace_id
        and capture.initiative_id == initiative_id
        and _reference(capture.provider_file_id),
        "READINESS_SOURCE_MISMATCH",
    )
    raw = capture.content_bytes
    _require(type(raw) is bytes and 0 < len(raw) <= limit, "READINESS_CAPTURE_LIMIT_EXCEEDED")
    _require(capture.content_digest == "sha256:" + hashlib.sha256(raw).hexdigest(), "READINESS_CAPTURE_DIGEST_MISMATCH")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        nodes = 0

        def check(item, depth=0):
            nonlocal nodes
            nodes += 1
            _require(depth <= 100 and nodes <= 100000, "READINESS_CAPTURE_LIMIT_EXCEEDED")
            if item is None or type(item) is bool:
                return
            if type(item) is str:
                item.encode("utf-8")
            elif type(item) in {int, float}:
                _require(
                    math.isfinite(item) and (type(item) is not int or abs(item) <= 9007199254740991),
                    "READINESS_CAPTURE_REQUIRED",
                )
            elif type(item) is list:
                for child in item:
                    check(child, depth + 1)
            elif type(item) is dict:
                for key, child in item.items():
                    check(key, depth + 1)
                    check(child, depth + 1)
            else:
                raise PrdReadinessError("READINESS_CAPTURE_REQUIRED")

        check(value)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise PrdReadinessError("READINESS_CAPTURE_REQUIRED") from None
    _require(
        type(value) is dict
        and value.get("normalization_version") == "curve.google-docs.normalized/v1-candidate"
        and value.get("complete") is True
        and type(value.get("unsupported_nodes")) is int
        and value["unsupported_nodes"] == 0
        and type(value.get("tabs")) is list
        and bool(value["tabs"]),
        "READINESS_CAPTURE_REQUIRED",
    )
    _require(
        type(value.get("document_properties")) is dict
        and value["document_properties"].get("documentId") == capture.provider_file_id,
        "READINESS_SOURCE_MISMATCH",
    )
    return value


def _meaningful(text):
    cleaned = re.sub(r"[.!;:]+$", "", text.strip()).strip()
    return bool(cleaned) and re.fullmatch(r"tbd|todo|tbc|n/?a|none|unknown|[-?.\s]+", cleaned, re.I) is None


def _sections(content, expected, prefix):
    def key(text):
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    lookup = {key(label): identifier for identifier, label in expected.items()}
    found, duplicates = {}, set()

    def open_section(label):
        _require(type(label) is str, "READINESS_CAPTURE_REQUIRED")
        identifier = lookup.get(key(label))
        if identifier:
            if identifier in found:
                duplicates.add(identifier)
            else:
                found[identifier] = []
        return identifier

    def visit(nodes, active, table=False):
        _require(type(nodes) is list, "READINESS_CAPTURE_REQUIRED")
        for node in nodes:
            _require(type(node) is dict, "READINESS_CAPTURE_REQUIRED")
            kinds = STRUCTURAL_TYPES.intersection(node)
            _require(
                len(kinds) == 1 and set(node) <= STRUCTURAL_TYPES | {"startIndex", "endIndex"},
                "READINESS_CAPTURE_REQUIRED",
            )
            _require(type(node[next(iter(kinds))]) is dict, "READINESS_CAPTURE_REQUIRED")
            if "paragraph" in node:
                paragraph = node["paragraph"]
                _require(
                    type(paragraph) is dict and type(paragraph.get("elements")) is list, "READINESS_CAPTURE_REQUIRED"
                )
                chunks = []
                for element in paragraph["elements"]:
                    _require(type(element) is dict, "READINESS_CAPTURE_REQUIRED")
                    kinds = PARAGRAPH_TYPES.intersection(element)
                    _require(
                        len(kinds) == 1 and set(element) <= PARAGRAPH_TYPES | {"startIndex", "endIndex"},
                        "READINESS_CAPTURE_REQUIRED",
                    )
                    _require(type(element[next(iter(kinds))]) is dict, "READINESS_CAPTURE_REQUIRED")
                    if "textRun" in element:
                        run = element["textRun"]
                        _require(type(run) is dict and type(run.get("content")) is str, "READINESS_CAPTURE_REQUIRED")
                        chunks.append(run["content"])
                text = "".join(chunks)
                style = paragraph.get("paragraphStyle", {})
                _require(type(style) is dict, "READINESS_CAPTURE_REQUIRED")
                heading = style.get("namedStyleType", "")
                if not table and type(heading) is str and re.fullmatch(r"HEADING_[1-6]", heading):
                    identifier, level = open_section(text), int(heading[-1])
                    if identifier:
                        active = (identifier, level)
                    elif active and level <= active[1]:
                        active = None
                elif active:
                    found[active[0]].append(text)
            elif "table" in node:
                for row in node["table"]["tableRows"]:
                    for cell in row["tableCells"]:
                        visit(cell["content"], active, True)
            # TOC and non-body segments cannot supply required sections.

    def tabs(items, inherited=None):
        for tab in items:
            identifier = open_section(tab.get("tabProperties", {}).get("title", ""))
            active = (identifier, 0) if identifier else inherited
            visit(tab["documentTab"]["body"]["content"], active)
            tabs(tab.get("childTabs", []), active)

    try:
        tabs(content["tabs"])
    except (KeyError, TypeError, AttributeError, RecursionError):
        raise PrdReadinessError("READINESS_CAPTURE_REQUIRED") from None
    reasons = []
    for identifier in expected:
        mode = (
            "DUPLICATE"
            if identifier in duplicates
            else "MISSING"
            if identifier not in found
            else "EMPTY"
            if not _meaningful("\n".join(found[identifier]))
            else None
        )
        if mode:
            reasons.append(f"{prefix}_SECTION_{mode}:{identifier}")
    return {identifier: "\n".join(chunks) for identifier, chunks in found.items()}, reasons


def _traceability(texts):
    def declarations(text, pattern):
        entries = []
        for line in text.split("\n"):
            match = re.fullmatch(pattern, line.strip())
            if match:
                entries.append([match[1], match[2]])
            elif entries:
                entries[-1][1] += "\n" + line
        return entries

    requirements = declarations(texts.get("requirements", ""), r"((?:FR|REQ)-[0-9]+)\s*:\s*(.*)")
    acceptance = declarations(texts.get("acceptance", ""), r"(AC-[0-9]+)\s*:\s*(.*)")
    reasons, covered = [], set()
    identifiers = {item[0] for item in requirements}
    for kind, entries in (("REQUIREMENT", requirements), ("ACCEPTANCE", acceptance)):
        if not entries:
            reasons.append(f"PRD_{kind}_ID_REQUIRED")
        if len({item[0] for item in entries}) != len(entries):
            reasons.append(f"PRD_{kind}_DUPLICATE")
        if any(not _meaningful(item[1]) for item in entries):
            reasons.append(f"PRD_{kind}_EMPTY")
    for _, text in acceptance:
        refs = re.findall(r"\b(?:FR|REQ)-[0-9]+\b", text)
        if not refs:
            reasons.append("PRD_ACCEPTANCE_TRACE_REQUIRED")
        if set(refs) - identifiers:
            reasons.append("PRD_ACCEPTANCE_UNKNOWN_REQUIREMENT")
        covered.update(refs)
    if identifiers - covered:
        reasons.append("PRD_REQUIREMENT_UNCOVERED")
    return list(dict.fromkeys(reasons))


def evaluate_prd_readiness(
    *,
    id,
    workspace_id,
    initiative_id,
    initiative_version,
    prd,
    idea_brief,
    evidence_snapshot_id,
    inventory,
    active_human_ids,
    checked_at,
    max_document_bytes,
):
    _require(
        all(_reference(value) for value in (id, workspace_id, initiative_id, evidence_snapshot_id))
        and type(initiative_version) is int
        and 0 < initiative_version <= 9007199254740991
        and _time(checked_at),
        "READINESS_CONTEXT_INVALID",
    )
    _require(type(max_document_bytes) is int and max_document_bytes > 0, "READINESS_CAPTURE_LIMIT_EXCEEDED")
    content = _capture(prd, workspace_id, initiative_id, max_document_bytes)
    brief = _capture(idea_brief, workspace_id, initiative_id, max_document_bytes)
    _require(
        all(_reference(value) for value in (prd.binding_id, prd.provider_version, idea_brief.artifact_version_id)),
        "READINESS_CONTEXT_INVALID",
    )
    _require(
        _closed(inventory, INVENTORY_FIELDS)
        and type(inventory["blockers"]) is list
        and type(inventory["assumptions"]) is list
        and len(inventory["blockers"]) <= 1000
        and len(inventory["assumptions"]) <= 1000
        and type(active_human_ids) is list
        and len(active_human_ids) <= 10000
        and all(_reference(value) for value in active_human_ids),
        "READINESS_INVENTORY_INVALID",
    )
    _require(
        all(_closed(item, {"id", "state", "resolution_ref"}) for item in inventory["blockers"])
        and all(
            _closed(item, {"id", "owner_actor_id", "validation_plan_ref", "due_stage"})
            for item in inventory["assumptions"]
        ),
        "READINESS_INVENTORY_INVALID",
    )
    try:
        inventory_digest = metadata_digest(inventory)
    except Exception:
        raise PrdReadinessError("READINESS_INVENTORY_INVALID") from None
    profile = readiness_profile()
    _, brief_reasons = _sections(brief, profile["idea_brief_sections"], "IDEA_BRIEF")
    texts, prd_reasons = _sections(content, profile["prd_sections"], "PRD")
    reasons = brief_reasons + prd_reasons + _traceability(texts)
    if (
        inventory["workspace_id"] != workspace_id
        or inventory["initiative_id"] != initiative_id
        or inventory["prd_digest"] != prd.content_digest
        or inventory["idea_brief_digest"] != idea_brief.content_digest
        or inventory["checked_at"] != checked_at
        or inventory["complete"] is not True
    ):
        reasons.append("READINESS_INVENTORY_STALE")
    identifiers = [item["id"] for item in inventory["blockers"] + inventory["assumptions"]]
    if not all(_reference(value) for value in identifiers) or len(set(identifiers)) != len(identifiers):
        reasons.append("READINESS_INVENTORY_INVALID")
    if any(item["state"] != "RESOLVED" or not _reference(item["resolution_ref"]) for item in inventory["blockers"]):
        reasons.append("BLOCKERS_UNRESOLVED")
    if any(
        not _reference(item["owner_actor_id"])
        or item["owner_actor_id"] not in active_human_ids
        or not _reference(item["validation_plan_ref"])
        or not _reference(item["due_stage"])
        for item in inventory["assumptions"]
    ):
        reasons.append("ASSUMPTION_PLAN_REQUIRED")
    payload = dict(
        schema_version="curve.prd-readiness/v1-candidate",
        id=id,
        workspace_id=workspace_id,
        initiative_id=initiative_id,
        initiative_version=initiative_version,
        profile_digest=metadata_digest(profile),
        prd_binding_id=prd.binding_id,
        provider_file_id=prd.provider_file_id,
        provider_version=prd.provider_version,
        content_digest=prd.content_digest,
        idea_brief_version_id=idea_brief.artifact_version_id,
        idea_brief_digest=idea_brief.content_digest,
        evidence_snapshot_id=evidence_snapshot_id,
        inventory_digest=inventory_digest,
        checked_at=checked_at,
        status="BLOCKED" if reasons else "READY",
        reasons=reasons,
    )
    return ReadinessReport(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def validate_prd_readiness_report(report):
    _require(_closed(report, REPORT_FIELDS), "PRD_READINESS_REQUIRED")
    profile = readiness_profile()
    allowed_reasons = {
        f"{prefix}_SECTION_{mode}:{identifier}"
        for prefix, sections in (("PRD", profile["prd_sections"]), ("IDEA_BRIEF", profile["idea_brief_sections"]))
        for mode in ("MISSING", "EMPTY", "DUPLICATE")
        for identifier in sections
    } | {
        "PRD_REQUIREMENT_ID_REQUIRED",
        "PRD_REQUIREMENT_DUPLICATE",
        "PRD_REQUIREMENT_EMPTY",
        "PRD_ACCEPTANCE_ID_REQUIRED",
        "PRD_ACCEPTANCE_DUPLICATE",
        "PRD_ACCEPTANCE_EMPTY",
        "PRD_ACCEPTANCE_TRACE_REQUIRED",
        "PRD_ACCEPTANCE_UNKNOWN_REQUIREMENT",
        "PRD_REQUIREMENT_UNCOVERED",
        "READINESS_INVENTORY_STALE",
        "READINESS_INVENTORY_INVALID",
        "BLOCKERS_UNRESOLVED",
        "ASSUMPTION_PLAN_REQUIRED",
    }
    _require(
        report["schema_version"] == "curve.prd-readiness/v1-candidate"
        and type(report["status"]) is str
        and report["status"] in {"READY", "BLOCKED"}
        and type(report["reasons"]) is list
        and len(report["reasons"]) <= len(allowed_reasons)
        and all(type(reason) is str and reason in allowed_reasons for reason in report["reasons"])
        and len(set(report["reasons"])) == len(report["reasons"])
        and bool(report["reasons"]) == (report["status"] == "BLOCKED")
        and report["profile_digest"] == metadata_digest(profile)
        and _time(report["checked_at"]),
        "PRD_READINESS_REQUIRED",
    )
    _require(
        type(report["initiative_version"]) is int and 0 < report["initiative_version"] <= 9007199254740991,
        "PRD_READINESS_REQUIRED",
    )
    for field in SUBJECT_FIELDS - {"initiative_version", "checked_at"}:
        value = report[field]
        _require(
            type(value) is str
            and (
                DIGEST.fullmatch(value)
                if field in {"content_digest", "idea_brief_digest", "inventory_digest"}
                else _reference(value)
            ),
            "PRD_READINESS_REQUIRED",
        )
    return True


def require_current_prd_readiness(report, expected):
    validate_prd_readiness_report(report)
    _require(_closed(expected, SUBJECT_FIELDS) and report["status"] == "READY", "PRD_READINESS_REQUIRED")
    _require(
        all(
            type(report[field]) is type(expected[field]) and report[field] == expected[field]
            for field in SUBJECT_FIELDS
        ),
        "PRD_READINESS_STALE",
    )
    return True
