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
