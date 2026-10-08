# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Python candidate validator. Pure data checks; no runtime or authority grant.

This independently executable preparation stays outside Plane's qualified runtime
inventory until its database predecessor can be verified and its successor reviewed.
"""

import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

MAX_INTEGER = 2**53 - 1
MAX_DEFINITION = 5 * 1024 * 1024
MANIFEST_DIGEST = "sha256:2e2bbd7f1a4db7095510b0dcbb7fa685b7a82dcc2b3f853aae02a23e66d2bac4"
ROOT = Path(__file__).parent / "contract_snapshot"


class InvalidPlan(ValueError):
    """A fixed code only: input values never enter the public error message."""


def require(condition, code="VALIDATION_FAILED"):
    if not condition:
        raise InvalidPlan(code)


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_strict_json(raw, *, max_bytes=65536, max_depth=32, max_nodes=100000):
    require(type(raw) is bytes and len(raw) <= max_bytes, "JSON_BOUND_EXCEEDED")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise InvalidPlan("STRICT_JSON_INVALID") from None
    offset, nodes = 0, 0

    def whitespace():
        nonlocal offset
        while offset < len(text) and text[offset] in " \t\n\r":
            offset += 1

    def string():
        nonlocal offset
        require(offset < len(text) and text[offset] == '"', "STRICT_JSON_INVALID")
        try:
            result, offset = json.decoder.scanstring(text, offset + 1, True)
            result.encode("utf-8", errors="strict")
        except (ValueError, UnicodeError):
            raise InvalidPlan("STRICT_JSON_INVALID") from None
        return result

    def value(depth):
        nonlocal offset, nodes
        nodes += 1
        require(nodes <= max_nodes, "STRICT_JSON_INVALID")
        whitespace()
        require(offset < len(text), "STRICT_JSON_INVALID")
        char = text[offset]
        if char == '"':
            return string()
        if char in "{[":
            require(depth < max_depth, "STRICT_JSON_INVALID")
            offset += 1
            is_object = char == "{"
            result = {} if is_object else []
            end = "}" if is_object else "]"
            whitespace()
            if offset < len(text) and text[offset] == end:
                offset += 1
                return result
            while True:
                whitespace()
                if is_object:
                    nodes += 1
                    require(nodes <= max_nodes, "STRICT_JSON_INVALID")
                    key = string()
                    require(key not in result, "STRICT_JSON_INVALID")
                    whitespace()
                    require(offset < len(text) and text[offset] == ":", "STRICT_JSON_INVALID")
                    offset += 1
                child = value(depth + 1)
                if is_object:
                    result[key] = child
                else:
                    result.append(child)
                whitespace()
                require(offset < len(text), "STRICT_JSON_INVALID")
                if text[offset] == end:
                    offset += 1
                    return result
                require(text[offset] == ",", "STRICT_JSON_INVALID")
                offset += 1
        for token, result in (("true", True), ("false", False), ("null", None)):
            if text.startswith(token, offset):
                offset += len(token)
                return result
        match = re.match(r"-?(?:0|[1-9][0-9]*)", text[offset:])
        require(match is not None and match[0] != "-0", "STRICT_JSON_INVALID")
        token = match[0]
        require(len(token.lstrip("-")) <= 16, "STRICT_JSON_INVALID")
        offset += len(token)
        require(offset == len(text) or text[offset] not in ".eE0123456789", "STRICT_JSON_INVALID")
        result = int(token)
        require(abs(result) <= MAX_INTEGER, "STRICT_JSON_INVALID")
        return result

    result = value(0)
    whitespace()
    require(offset == len(text), "STRICT_JSON_INVALID")
    return result


def canonical_json(value):
    def check(item, depth=0):
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            require(abs(item) <= MAX_INTEGER, "NONCANONICAL_NUMBER")
        elif type(item) is str:
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeError:
                raise InvalidPlan("NONCANONICAL_STRING") from None
        elif type(item) in (dict, list):
            require(depth < 32, "NONCANONICAL_DEPTH")
            if type(item) is dict:
                require(all(type(key) is str for key in item), "NONCANONICAL_KEY")
                for key, child in item.items():
                    check(key, depth + 1)
                    check(child, depth + 1)
            else:
                for child in item:
                    check(child, depth + 1)
        else:
            raise InvalidPlan("NONCANONICAL_JSON_TYPE")

    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def metadata_digest(value):
    require(type(value) is dict, "NONCANONICAL_OBJECT")
    return digest(canonical_json({key: item for key, item in value.items() if key != "digest"}))


def same(left, right):
    return canonical_json(left) == canonical_json(right)


def parse_typed_initiative_etag(value, initiative_id):
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    require(type(value) is str and type(initiative_id) is str, "INITIATIVE_ETAG_INVALID")
    require(re.fullmatch(uuid_pattern, initiative_id) is not None, "INITIATIVE_ETAG_INVALID")
    match = re.fullmatch(r'"curve-initiative:(' + uuid_pattern + r'):v([1-9][0-9]{0,15})"', value)
    require(match is not None and match[1] == initiative_id, "INITIATIVE_ETAG_INVALID")
    version = int(match[2])
    require(version <= MAX_INTEGER, "INITIATIVE_ETAG_INVALID")
    return version


def candidate_schemas(root=ROOT):
    raw = (root / "manifest-v2.json").read_bytes()
    require(digest(raw) == MANIFEST_DIGEST, "CONTRACT_UNAVAILABLE")
    manifest = parse_strict_json(raw)
    require(
        set(manifest) == {p.name for p in root.glob("*.json") if p.name != "manifest-v2.json"}, "CONTRACT_UNAVAILABLE"
    )
    schemas = {}
    for name, expected in manifest.items():
        path = root / name
        require(not path.is_symlink(), "CONTRACT_UNAVAILABLE")
        raw = path.read_bytes()
        require(digest(raw) == expected, "CONTRACT_UNAVAILABLE")
        if name.endswith(".schema.json"):
            schema = parse_strict_json(raw)
            Draft202012Validator.check_schema(schema)
            schemas[name] = schema
    return schemas


def validate_schema(name, value, schemas):
    # A closed in-memory registry has no network retrieval callback.
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    try:
        Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker()).validate(value)
    except Exception:
        raise InvalidPlan("SCHEMA_INVALID") from None


def sorted_unique(values):
    return values == sorted(set(values))


def issue_key(ref):
    return ref["provider_installation_id"] + ":" + ref["source_issue_id"]


def validate_definition_semantics(definition, facts):
    for key in (
        "manual_profile_ref",
        "approved_subject_ref",
        "scope_revision_ref",
        "workflow_ref",
        "quality_policy_ref",
        "workspace_id",
        "initiative_id",
    ):
        require(same(definition[key], facts[key]), "INPUT_REFERENCE_MISMATCH")
    require(
        same(facts["workflow_conditions"]["workflow_ref"], definition["workflow_ref"]),
        "WORKFLOW_CONDITION_EDITION_MISMATCH",
    )
    repos = definition["repositories"]
    require(same(repos, facts["repositories"]), "REPOSITORY_INPUT_MISMATCH")
    repo_ids = [r["repository_ref"]["entity_id"] for r in repos]
    require(sorted_unique(repo_ids), "REPOSITORY_ORDER")
    slices = definition["slices"]
    slice_keys = [s["slice_key"] for s in slices]
    require(sorted_unique(slice_keys), "SLICE_ORDER")
    requirements, acceptances, deliveries = set(), set(), set()
    ranks = {"LOW": 0, "STANDARD": 1, "HIGH": 2}
    for item in slices:
        require(item["repository_binding_id"] in repo_ids, "SLICE_REPOSITORY_MISSING")
        require(
            item["owner"]["actor_type"] == "HUMAN" and item["owner"]["actor_id"] in facts["owner_ids"],
            "OWNER_UNAVAILABLE",
        )
        require(
            item["code_approver"]["actor_type"] == "HUMAN"
            and item["code_approver"]["actor_id"] == facts["code_approver_id"],
            "CODE_APPROVER_MISMATCH",
        )
        require(ranks[item["risk_tier"]] >= ranks[facts["risk_tier"]], "RISK_UNDERSTATED")
        require(same(item["budget_policy_ref"], facts["budget_policy_ref"]), "BUDGET_POLICY_MISMATCH")
        for key, covered in (("requirement_ids", requirements), ("acceptance_ids", acceptances)):
            require(sorted_unique(item[key]) and set(item[key]) <= set(facts[key]), "TRACE_INVALID")
            covered.update(item[key])
        checks = [step["check_id"] for step in item["verification_steps"]]
        require(len(set(checks)) == len(checks), "DUPLICATE_CHECK")
        require(set(facts["required_check_ids"]) <= set(checks), "QUALITY_CHECK_MISSING")
        for component in item["expected_components"]:
            path = component["path"]
            require(
                not re.search(r"[\x00-\x1f\x7f\\]", path) and all(p not in ("", ".", "..") for p in path.split("/")),
                "COMPONENT_PATH_INVALID",
            )
        require(re.fullmatch(r"[a-z][a-z0-9-]{0,79}", facts["initiative_key"]) is not None, "BRANCH_INVALID")
        require(item["branch_name"] == f"curve/{facts['initiative_key']}/{item['slice_key']}", "BRANCH_INVALID")
        refs = item["proposed_delivery_refs"]
        require(sorted_unique([issue_key(ref) for ref in refs]), "DELIVERY_ORDER")
        require(
            all(any(same(ref, known) for known in facts["proposed_delivery_refs"]) for ref in refs),
            "UNAPPROVED_DELIVERY_ITEM",
        )
        deliveries.update(map(issue_key, refs))
    require(set(facts["requirement_ids"]) <= requirements, "REQUIREMENT_COVERAGE_MISSING")
    require(set(facts["acceptance_ids"]) <= acceptances, "ACCEPTANCE_COVERAGE_MISSING")
    require(deliveries == set(map(issue_key, facts["proposed_delivery_refs"])), "DELIVERY_COVERAGE_MISSING")
    outgoing = {key: set() for key in slice_keys}
    seen = set()
    for edge in definition["dependencies"]:
        a, b = edge["predecessor_slice_key"], edge["successor_slice_key"]
        require(a in outgoing and b in outgoing and a != b, "EDGE_ENDPOINT_INVALID")
        identity = (a, b, edge["dependency_type"])
        require(identity not in seen, "DUPLICATE_EDGE")
        seen.add(identity)
        require(edge["condition_status"] == "FUTURE_NOT_ASSERTED", "FUTURE_CONDITION_ASSERTED")
        if edge["artifact_ref"] is not None:
            for inventory in (facts["dependency_artifact_refs"], facts["protected_object_refs"]):
                require(any(same(edge["artifact_ref"], ref) for ref in inventory), "DEPENDENCY_ARTIFACT_UNAVAILABLE")
        require(same(edge["workflow_ref"], definition["workflow_ref"]), "EDGE_WORKFLOW_MISMATCH")
        condition = {
            key: edge[key] for key in ("dependency_type", "condition_subject", "required_state", "condition_source")
        }
        require(
            any(same(condition, known) for known in facts["workflow_conditions"]["allowed_conditions"]),
            "EDGE_CONDITION_INVALID",
        )
        outgoing[a].add(b)
    visiting, visited = set(), set()

    def visit(key):
        require(key not in visiting, "CYCLIC_GRAPH")
        if key in visited:
            return
        visiting.add(key)
        for child in outgoing[key]:
            visit(child)
        visiting.remove(key)
        visited.add(key)

    for key in outgoing:
        visit(key)


def validate_input_identity(identity, definition):
    for key in (
        "workspace_id",
        "initiative_id",
        "approved_subject_ref",
        "manual_profile_ref",
        "scope_revision_ref",
        "workflow_ref",
        "quality_policy_ref",
    ):
        require(same(identity[key], definition[key]), "INPUT_REFERENCE_MISMATCH")
    require(same(identity["repository_inputs"], definition["repositories"]), "INPUT_REPOSITORY_MISMATCH")
    gates = identity["gate_assignments"]
    require(
        [g["gate_type"] for g in gates] == ["CODE_READINESS", "PLAN_APPROVAL", "PRD_APPROVAL"], "INPUT_GATES_MISSING"
    )
    require(len({g["gate_assignment_id"] for g in gates}) == 3, "INPUT_ASSIGNMENT_REUSED")
    if any(s["risk_tier"] != "LOW" for s in definition["slices"]):
        require(len({g["approver_user_id"] for g in gates}) == 3, "INPUT_GATE_SEPARATION")
    require(
        identity["human_owner_ids"] == sorted({s["owner"]["actor_id"] for s in definition["slices"]}),
        "INPUT_OWNER_MISMATCH",
    )
    objects = [item["object_ref"] for item in identity["protected_inputs"]]
    require(len({ref["object_id"] for ref in objects}) == len(objects), "INPUT_OBJECT_REUSED")
    for item in identity["protected_inputs"]:
        bound = 524288000 if item["input_kind"] == "CONTEXT_INPUT" else 104857600
        require(item["object_ref"]["size_bytes"] <= bound, "INPUT_OBJECT_TOO_LARGE")
    for repo in definition["repositories"]:
        require(
            any(
                item["input_kind"] == "CONTEXT_INPUT" and same(item["object_ref"], repo["context_input_ref"])
                for item in identity["protected_inputs"]
            ),
            "INPUT_CONTEXT_MISSING",
        )
    for edge in definition["dependencies"]:
        if edge["artifact_ref"] is not None:
            require(any(same(edge["artifact_ref"], ref) for ref in objects), "INPUT_DEPENDENCY_ARTIFACT_MISSING")
    require(identity["digest"] == metadata_digest(identity), "INPUT_DIGEST_MISMATCH")


def validate_definition(raw, identity, facts):
    schemas = candidate_schemas()
    definition = parse_strict_json(raw, max_bytes=MAX_DEFINITION)
    validate_schema("manual-plan-definition-v2.schema.json", definition, schemas)
    validate_schema("manual-plan-input-identity-v2.schema.json", identity, schemas)
    ref = identity["definition_ref"]
    require(
        ref["digest"] == digest(raw) and ref["size_bytes"] == len(raw) and ref["media_type"] == "application/json",
        "DEFINITION_IDENTITY_MISMATCH",
    )
    validate_definition_semantics(definition, facts)
    validate_input_identity(identity, definition)
    receipt = dict(
        schema_version="curve.manual-plan-validation-receipt/v2-candidate",
        validator_edition="DETERMINISTIC_SDLC_MANUAL_PLAN_V2",
        definition_digest=digest(raw),
        input_identity_digest=identity["digest"],
        result="VALID",
        repository_count=len(definition["repositories"]),
        slice_count=len(definition["slices"]),
        edge_count=len(definition["dependencies"]),
        required_conditions="FUTURE_NOT_ASSERTED",
    )
    receipt["digest"] = metadata_digest(receipt)
    validate_schema("manual-plan-validation-receipt-v2.schema.json", receipt, schemas)
    return receipt


def _normalized_prd_facts(value, identity):
    """Conservative local subset of the incumbent approved normalized PRD.

    Only one plain-text tab is admitted here. Tables, nested tabs and non-text
    elements fail closed instead of silently dropping possible requirements.
    Native immutable PRD metadata supplies workspace/Initiative ownership.
    """
    require(
        set(value) == {"normalization_version", "complete", "unsupported_nodes", "document_properties", "tabs"}
        and value["normalization_version"] == "curve.google-docs.normalized/v1-candidate"
        and value["complete"] is True
        and type(value["unsupported_nodes"]) is int
        and value["unsupported_nodes"] == 0
        and type(value["document_properties"]) is dict
        and type(value["document_properties"].get("documentId")) is str
        and type(value["tabs"]) is list
        and len(value["tabs"]) == 1,
        "NORMALIZED_PRD_SUBSET_UNAVAILABLE",
    )
    tab = value["tabs"][0]
    require(
        type(tab) is dict and set(tab) <= {"tabProperties", "documentTab", "childTabs"} and not tab.get("childTabs"),
        "NORMALIZED_PRD_SUBSET_UNAVAILABLE",
    )
    document = tab.get("documentTab", {})
    require(type(document) is dict and set(document) == {"body"}, "NORMALIZED_PRD_SUBSET_UNAVAILABLE")
    body = document["body"]
    require(type(body) is dict and set(body) == {"content"}, "NORMALIZED_PRD_SUBSET_UNAVAILABLE")
    nodes = body["content"]
    require(type(nodes) is list, "NORMALIZED_PRD_SUBSET_UNAVAILABLE")
    sections, active = {}, None
    for node in nodes:
        require(
            type(node) is dict and set(node) <= {"paragraph", "startIndex", "endIndex"},
            "NORMALIZED_PRD_SUBSET_UNAVAILABLE",
        )
        paragraph = node.get("paragraph")
        require(
            type(paragraph) is dict
            and set(paragraph) <= {"elements", "paragraphStyle"}
            and type(paragraph.get("elements")) is list,
            "NORMALIZED_PRD_SUBSET_UNAVAILABLE",
        )
        chunks = []
        for element in paragraph["elements"]:
            require(
                type(element) is dict
                and set(element) <= {"textRun", "startIndex", "endIndex"}
                and type(element.get("textRun")) is dict
                and set(element["textRun"]) <= {"content", "textStyle"}
                and type(element["textRun"].get("content")) is str,
                "NORMALIZED_PRD_SUBSET_UNAVAILABLE",
            )
            chunks.append(element["textRun"]["content"])
        text = "".join(chunks)
        style = paragraph.get("paragraphStyle", {})
        require(type(style) is dict, "NORMALIZED_PRD_SUBSET_UNAVAILABLE")
        heading = style.get("namedStyleType", "")
        if type(heading) is str and re.fullmatch(r"HEADING_[1-6]", heading):
            label, level = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip(), int(heading[-1])
            if label in {"requirements", "acceptance"}:
                require(label not in sections, "PRD_SECTION_DUPLICATE")
                sections[label], active = [], (label, level)
            elif active and level <= active[1]:
                active = None
            elif active:
                sections[active[0]].append(text)
        elif active:
            sections[active[0]].append(text)
    require(set(sections) == {"requirements", "acceptance"}, "PRD_SECTION_REQUIRED")

    def declarations(label, pattern):
        entries = []
        for line in "\n".join(sections[label]).splitlines():
            match = re.fullmatch(pattern, line.strip())
            if match:
                entries.append([match[1], match[2]])
            elif line.strip():
                require(entries and not re.match(r"\s*(?:FR|AC|REQ)-[0-9]+\b", line), "PRD_DECLARATION_INVALID")
                entries[-1][1] += "\n" + line
        require(entries and len({item[0] for item in entries}) == len(entries), "PRD_DECLARATION_INVALID")
        require(all(item[1].strip() for item in entries), "PRD_DECLARATION_INVALID")
        return sorted(entries)

    requirements = declarations("requirements", r"(FR-[0-9]+)\s*:\s*(.*)")
    acceptances = declarations("acceptance", r"(AC-[0-9]+)\s*:\s*(.*)")
    links = {key: [] for key, _ in requirements}
    for key, text in acceptances:
        refs = set(re.findall(r"\b(?:FR|REQ)-[0-9]+\b", text))
        require(refs and refs <= set(links), "PRD_ACCEPTANCE_TRACE_INVALID")
        for ref in refs:
            links[ref].append(key)
    require(all(links.values()), "PRD_ACCEPTANCE_TRACE_INVALID")
    return dict(
        schema_version="curve.synthetic-prd-body/v2",
        workspace_id=identity["workspace_id"],
        initiative_id=identity["initiative_id"],
        requirements=[dict(id=key, text=text, acceptance_ids=links[key]) for key, text in requirements],
        acceptances=[dict(id=key, text=text) for key, text in acceptances],
    )


def derive_semantic_facts(identity, sources, materials, native_facts):
    """Fixed synthetic-body adapter. No editable facts list can weaken these facts.

    All source bodies must be in the retained protected inventory and byte-bound.
    Native fields are independently bound to locked scoped PRD data by policy.
    Only these explicit local body editions are accepted; no provider parser.
    """
    from copy import deepcopy

    def closed(value, keys):
        require(type(value) is dict and set(value) == set(keys), "SEMANTIC_SOURCE_INVALID")

    def ordered(values, pattern, *, maximum=1024, nonempty=True):
        require(
            type(values) is list
            and (1 if nonempty else 0) <= len(values) <= maximum
            and all(type(item) is str and re.fullmatch(pattern, item) for item in values)
            and sorted_unique(values),
            "SEMANTIC_SOURCE_INVALID",
        )
        return values

    retained = {item["object_ref"]["object_id"]: item["object_ref"] for item in identity["protected_inputs"]}
    require(len(retained) == len(identity["protected_inputs"]), "INPUT_OBJECT_REUSED")
    closed(sources, ("prd", "workflow", "quality", "repositories"))

    def body(reference, edition, keys, pin=None):
        require(
            type(reference) is dict and retained.get(reference.get("object_id")) == reference,
            "SEMANTIC_SOURCE_NOT_RETAINED",
        )
        raw = materials.get(reference["object_id"])
        require(
            type(raw) is bytes
            and len(raw) == reference["size_bytes"]
            and digest(raw) == reference["digest"]
            and reference["media_type"] == "application/json",
            "SEMANTIC_SOURCE_IDENTITY_MISMATCH",
        )
        value = parse_strict_json(raw, max_bytes=MAX_DEFINITION)
        require(type(value) is dict, "SEMANTIC_SOURCE_INVALID")
        if edition == "curve.synthetic-prd-body/v2" and value.get("normalization_version"):
            value = _normalized_prd_facts(value, identity)
        closed(value, {"schema_version", "workspace_id", *keys})
        require(
            value["schema_version"] == edition and value["workspace_id"] == identity["workspace_id"],
            "SEMANTIC_SOURCE_EDITION_MISMATCH",
        )
        if pin is not None:
            require(value["id"] == pin["entity_id"] and digest(raw) == pin["digest"], "SEMANTIC_SOURCE_PIN_MISMATCH")
        return value

    prd = body(sources["prd"], "curve.synthetic-prd-body/v2", {"initiative_id", "requirements", "acceptances"})
    require(
        prd["initiative_id"] == identity["initiative_id"]
        and sources["prd"]["digest"] == identity["prd_content_digest"],
        "PRD_BODY_IDENTITY_MISMATCH",
    )
    requirement_ids, acceptance_ids, traces = [], [], set()
    require(
        type(prd["requirements"]) is list
        and type(prd["acceptances"]) is list
        and len(prd["requirements"]) <= 1024
        and len(prd["acceptances"]) <= 1024,
        "SEMANTIC_SOURCE_INVALID",
    )
    for item in prd["requirements"]:
        closed(item, ("id", "text", "acceptance_ids"))
        require(type(item["text"]) is str and 1 <= len(item["text"]) <= 8000, "SEMANTIC_SOURCE_INVALID")
        requirement_ids.append(item["id"])
        traces.update(ordered(item["acceptance_ids"], r"AC-[A-Za-z0-9][A-Za-z0-9._-]{0,96}"))
    for item in prd["acceptances"]:
        closed(item, ("id", "text"))
        require(type(item["text"]) is str and 1 <= len(item["text"]) <= 8000, "SEMANTIC_SOURCE_INVALID")
        acceptance_ids.append(item["id"])
    ordered(requirement_ids, r"FR-[A-Za-z0-9][A-Za-z0-9._-]{0,96}")
    ordered(acceptance_ids, r"AC-[A-Za-z0-9][A-Za-z0-9._-]{0,96}")
    require(traces == set(acceptance_ids), "PRD_ACCEPTANCE_TRACE_INVALID")
    workflow = body(
        sources["workflow"],
        "curve.synthetic-workflow/v2",
        {"id", "allowed_conditions", "dependency_artifact_refs"},
        identity["workflow_ref"],
    )
    allowed = parse_strict_json((ROOT / "workflow-condition-subset-v2.json").read_bytes())["allowed_conditions"]
    require(workflow["allowed_conditions"] == allowed, "WORKFLOW_CONDITION_EDITION_MISMATCH")
    quality = body(
        sources["quality"],
        "curve.synthetic-quality-policy/v2",
        {"id", "required_check_ids"},
        identity["quality_policy_ref"],
    )
    checks = set(ordered(quality["required_check_ids"], r"[a-z][a-z0-9-]{0,79}"))
    require(
        type(sources["repositories"]) is list and len(sources["repositories"]) == len(identity["repository_inputs"]),
        "REPOSITORY_INPUT_MISMATCH",
    )
    repositories = []
    for input_ref, source in zip(identity["repository_inputs"], sources["repositories"]):
        closed(source, ("repository", "policy"))
        repository = body(
            source["repository"],
            "curve.synthetic-repository/v2",
            {"id", "base_branch", "base_commit", "repository_policy_ref", "context_input_ref"},
            input_ref["repository_ref"],
        )
        policy = body(
            source["policy"],
            "curve.synthetic-repository-policy/v2",
            {"id", "repository_id", "allowed_base_branches", "required_check_ids"},
            input_ref["repository_policy_ref"],
        )
        require(policy["repository_id"] == repository["id"], "REPOSITORY_INPUT_MISMATCH")
        branches = ordered(policy["allowed_base_branches"], r"[^\x00-\x20\x7f]{1,255}", maximum=128)
        require(repository["base_branch"] in branches, "REPOSITORY_BASE_NOT_ALLOWED")
        checks.update(ordered(policy["required_check_ids"], r"[a-z][a-z0-9-]{0,79}"))
        derived = dict(
            repository_ref=deepcopy(input_ref["repository_ref"]),
            **{
                key: deepcopy(repository[key])
                for key in ("base_branch", "base_commit", "repository_policy_ref", "context_input_ref")
            },
        )
        require(derived == input_ref, "REPOSITORY_INPUT_MISMATCH")
        repositories.append(derived)
    # Every other fact is bound to immutable identity or rechecked native records.
    result = deepcopy(native_facts)
    for key in (
        "workspace_id",
        "initiative_id",
        "approved_subject_ref",
        "scope_revision_ref",
        "manual_profile_ref",
        "workflow_ref",
        "quality_policy_ref",
    ):
        result[key] = deepcopy(identity[key])
    result.update(
        requirement_ids=requirement_ids,
        acceptance_ids=acceptance_ids,
        required_check_ids=sorted(checks),
        repositories=repositories,
        dependency_artifact_refs=deepcopy(workflow["dependency_artifact_refs"]),
        owner_ids=deepcopy(identity["human_owner_ids"]),
        code_approver_id=next(
            item["approver_user_id"] for item in identity["gate_assignments"] if item["gate_type"] == "CODE_READINESS"
        ),
        protected_object_refs=[deepcopy(item["object_ref"]) for item in identity["protected_inputs"]],
        workflow_conditions=dict(workflow_ref=deepcopy(identity["workflow_ref"]), allowed_conditions=allowed),
    )
    budget = parse_strict_json((ROOT / "manual-plan-profile-v2.json").read_bytes())["budget_policy_ref"]
    result["budget_policy_ref"] = budget
    # Dependency artifacts need explicit retained objects, not asserted future outcomes.
    require(
        type(result["dependency_artifact_refs"]) is list
        and len(result["dependency_artifact_refs"]) <= 1024
        and all(ref in result["protected_object_refs"] for ref in result["dependency_artifact_refs"]),
        "DEPENDENCY_ARTIFACT_UNAVAILABLE",
    )
    require(result == native_facts, "SEMANTIC_FACTS_MISMATCH")
    return result
