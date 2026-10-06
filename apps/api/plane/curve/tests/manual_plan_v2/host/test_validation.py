"""Cross-language, boundary and adversarial checks against frozen v2 inputs."""

# ruff: noqa: E402 -- host-only bootstrap precedes runtime module imports.

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import bootstrap

bootstrap.install()

from manual_plan_v2.validation import (
    InvalidPlan,
    MAX_DEFINITION,
    ROOT,
    candidate_schemas,
    canonical_json,
    digest,
    metadata_digest,
    parse_strict_json,
    parse_typed_initiative_etag,
    validate_definition,
    validate_definition_semantics,
    validate_input_identity,
    validate_schema,
)


def fixture(name):
    return json.loads((ROOT / "fixtures" / (name + ".json")).read_text())


class ParsingTests(unittest.TestCase):
    def test_strict_json_rejections_and_javascript_parity(self):
        cases = [
            b'{"x":1,"x":2}',
            b'{"x":1,"\\u0078":2}',
            b'{"x":1.0}',
            b'{"x":1e0}',
            b'{"x":-0}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b'{"x":9007199254740992}',
            b'{"x":01}',
            b'{"x":true}garbage',
            b'{"x":"\\ud800"}',
            b'{"x":"\\udfff"}',
            b"\xef\xbb\xbf{}",
            b'{"x":1,}',
            b"[1,]",
            b"[undefined]",
            b"\xff",
            b'"\xc0\xaf"',
            b'"\xed\xa0\x80"',
            b'"raw\nnewline"',
            b"",
            b"  ",
            b"{}\x00",
            b"\v{}",
            b"[truefalse]",
            b"{1:2}",
            b"1" * 65536,
        ]
        for raw in cases:
            with self.subTest(raw=raw[:30]), self.assertRaises(InvalidPlan):
                parse_strict_json(raw)
        valid = [
            b"null",
            b"true",
            b"false",
            b"0",
            b"-1",
            b"9007199254740991",
            b"-9007199254740991",
            b'{"__proto__":null}',
            '{"z":true,"a":"é😀","n":9007199254740991}'.encode(),
            b'{"x":"\\ud83d\\ude00"}',
            b' {"x": [false, null]} \n',
        ]
        self.assertEqual(
            self.node_parse(cases + valid),
            [None] * len(cases) + [canonical_json(parse_strict_json(raw)).decode() for raw in valid],
        )

    def node_parse(self, cases):
        program = """import {parseStrictJson,canonicalJson} from "./scripts/lib/manual-planning-v2.mjs";
let text=""; for await (const part of process.stdin) text+=part;
const out=JSON.parse(text).map(value=>{
  try{return canonicalJson(parseStrictJson(Buffer.from(value,"base64")));}catch{return null;}
});
console.log(JSON.stringify(out));"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program],
            input=json.dumps([base64.b64encode(raw).decode() for raw in cases]),
            text=True,
            capture_output=True,
            check=True,
            cwd=bootstrap.REPOSITORY.parent / "curve",
            timeout=20,
        )
        return json.loads(result.stdout)

    def test_inclusive_byte_depth_and_node_bounds(self):
        for bound in (65536, MAX_DEFINITION):
            raw = b'"' + b"a" * (bound - 2) + b'"'
            self.assertEqual(len(parse_strict_json(raw, max_bytes=bound)), bound - 2)
            with self.assertRaises(InvalidPlan):
                parse_strict_json(raw + b" ", max_bytes=bound)
        nested = parse_strict_json(b"[" * 32 + b"]" * 32)
        for _ in range(31):
            self.assertEqual(len(nested), 1)
            nested = nested[0]
        self.assertEqual(nested, [])
        for raw, options in (
            (b"[[]]", {"max_depth": 1}),
            (b"[null]", {"max_nodes": 1}),
            (b'{"x":1}', {"max_nodes": 2}),
            (b"[" * 33 + b"]" * 33, {}),
        ):
            with self.subTest(options=options), self.assertRaises(InvalidPlan):
                parse_strict_json(raw, **options)
        self.assertEqual(parse_strict_json(b'{"x":1}', max_nodes=3), {"x": 1})

    def test_canonicalization_digest_and_unicode_scalar_order(self):
        self.assertEqual(canonical_json({"2": "b", "10": "a"}), b'{"10":"a","2":"b"}')
        self.assertEqual(canonical_json({"😀": 1, "\uffff": 2}).decode(), '{"￿":2,"😀":1}')
        self.assertNotEqual(canonical_json("é"), canonical_json("e\u0301"))
        for name in ("revision", "input-identity", "validation"):
            value = fixture(name + ".valid")
            self.assertEqual(metadata_digest(value), value["digest"])
            self.assertEqual(metadata_digest({**value, "digest": "ignored"}), value["digest"])
        for value in (float("nan"), float("inf"), 1.5, -0.0, 2**53, {1: "a"}, "\ud800", object()):
            with self.subTest(value=type(value).__name__), self.assertRaises(InvalidPlan):
                canonical_json(value)
        self.assertNotEqual(canonical_json(True), canonical_json(1))

    def test_exact_strong_etag(self):
        identity = "30000000-0000-4000-8000-000000000002"
        self.assertEqual(parse_typed_initiative_etag(f'"curve-initiative:{identity}:v1"', identity), 1)
        self.assertEqual(
            parse_typed_initiative_etag(f'"curve-initiative:{identity}:v9007199254740991"', identity), 2**53 - 1
        )
        for value in (
            '"1"',
            "*",
            None,
            f'W/"curve-initiative:{identity}:v1"',
            f'"curve-initiative:{identity}:v01"',
            f'"curve-initiative:{identity}:v0"',
            f'"curve-initiative:{identity}:v9007199254740992"',
            f'"curve-initiative:{identity}:v1"\n',
            f'"curve-initiative:{identity}:v1", "other"',
        ):
            with self.subTest(value=value), self.assertRaises(InvalidPlan):
                parse_typed_initiative_etag(value, identity)
        with self.assertRaises(InvalidPlan):
            parse_typed_initiative_etag(f'"curve-initiative:{identity}:v1"', identity[:-1] + "3")


class DefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = candidate_schemas()

    def setUp(self):
        self.definition = fixture("definition.valid")
        self.identity = fixture("input-identity.valid")
        self.facts = fixture("immutable-semantic-facts")

    def validate(self, definition=None, identity=None):
        definition = definition if definition is not None else self.definition
        identity = deepcopy(identity if identity is not None else self.identity)
        raw = canonical_json(definition)
        identity["definition_ref"].update(digest=digest(raw), size_bytes=len(raw))
        identity["digest"] = metadata_digest(identity)
        return validate_definition(raw, identity, self.facts)

    def test_pinned_fixture_and_original_byte_identity(self):
        raw = (ROOT / "fixtures/definition.valid.json").read_bytes()
        receipt = validate_definition(raw, self.identity, self.facts)
        self.assertEqual(receipt["definition_digest"], digest(raw))
        self.assertEqual(receipt["input_identity_digest"], self.identity["digest"])
        self.assertEqual(receipt["digest"], metadata_digest(receipt))
        self.assertEqual(receipt["required_conditions"], "FUTURE_NOT_ASSERTED")
        with self.assertRaises(InvalidPlan):
            validate_definition(raw + b" ", self.identity, self.facts)

    def test_every_nested_definition_object_is_closed(self):
        paths = []

        def walk(value, path=()):
            if type(value) is dict:
                paths.append(path)
                for key, child in value.items():
                    walk(child, path + (key,))
            elif type(value) is list:
                for index, child in enumerate(value):
                    walk(child, path + (index,))

        walk(self.definition)
        for path in paths:
            value = deepcopy(self.definition)
            target = value
            for key in path:
                target = target[key]
            target["injected_authority"] = True
            with self.subTest(path=path), self.assertRaises(InvalidPlan):
                self.validate(value)

    def test_all_required_top_level_fields_remain_required(self):
        for key in self.definition:
            value = deepcopy(self.definition)
            del value[key]
            with self.subTest(key=key), self.assertRaises(InvalidPlan):
                self.validate(value)

    def test_privacy_receipts_are_not_revision_dtos(self):
        validate_schema("manual-plan-input-identity-v2.schema.json", self.identity, self.schemas)
        for value in (self.identity, fixture("current-authority.valid")):
            with self.assertRaises(InvalidPlan):
                validate_schema("manual-plan-draft-revision-v2.schema.json", value, self.schemas)

    def test_scope_profile_owner_quality_and_risk_cannot_be_weakened(self):
        changes = [
            (("automatic_execution",), "ALLOWED"),
            (("initiative_mode",), "ROADMAP_BACKED"),
            (("approved_subject_ref", "digest"), "sha256:" + "a" * 64),
            (("slices", 0, "owner", "actor_id"), "30000000-0000-4000-8000-000000000099"),
            (("slices", 0, "code_approver", "actor_id"), "30000000-0000-4000-8000-000000000099"),
            (("slices", 0, "risk_tier"), "LOW"),
            (("slices", 0, "verification_steps"), []),
            (("slices", 0, "requirement_ids"), ["FR-UNKNOWN"]),
            (("slices", 0, "branch_name"), "main"),
            (("slices", 0, "expected_components", 0, "path"), "../escape"),
            (("slices", 0, "expected_components", 0, "path"), "/absolute"),
            (("slices", 0, "expected_components", 0, "path"), "part\\escape"),
            (("slices", 0, "expected_components", 0, "path"), "part\x00escape"),
        ]
        for path, replacement in changes:
            value = deepcopy(self.definition)
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path), self.assertRaises(InvalidPlan):
                self.validate(value)

    def test_dependency_cycle_duplicate_and_future_claims_rejected(self):
        for changes in (
            {"condition_status": "SATISFIED"},
            {"required_state": "PLAN_APPROVED"},
            {"condition_subject": "PR_MR_BINDING"},
            {"predecessor_slice_key": "missing"},
        ):
            value = deepcopy(self.definition)
            value["dependencies"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(InvalidPlan):
                self.validate(value)
        for reverse in (False, True):
            value = deepcopy(self.definition)
            edge = deepcopy(value["dependencies"][0])
            if reverse:
                edge["predecessor_slice_key"], edge["successor_slice_key"] = (
                    edge["successor_slice_key"],
                    edge["predecessor_slice_key"],
                )
            value["dependencies"].append(edge)
            with self.assertRaises(InvalidPlan):
                self.validate(value)

    def test_prd_and_delivery_coverage_are_required(self):
        for key in ("requirement_ids", "acceptance_ids", "proposed_delivery_refs"):
            value = deepcopy(self.definition)
            for item in value["slices"]:
                item[key] = []
            with self.subTest(key=key), self.assertRaises(InvalidPlan):
                self.validate(value)

    def test_original_identity_gate_separation_and_immutability(self):
        for key in ("gate_assignment_id", "approver_user_id"):
            value = deepcopy(self.identity)
            value["gate_assignments"][1][key] = value["gate_assignments"][0][key]
            value["digest"] = metadata_digest(value)
            with self.subTest(key=key), self.assertRaises(InvalidPlan):
                validate_input_identity(value, self.definition)
        value = deepcopy(self.identity)
        value["protected_inputs"] = []
        value["digest"] = metadata_digest(value)
        with self.assertRaises(InvalidPlan):
            validate_input_identity(value, self.definition)
        value = deepcopy(self.identity)
        value["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(InvalidPlan):
            validate_input_identity(value, self.definition)

    def test_definition_instructions_are_inert_and_repeated_validation_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-exist"
            self.definition["slices"][0]["verification_steps"][0]["command_text"] = f"touch {marker}"
            before = deepcopy(self.definition)
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.validate(), range(8)))
            self.assertTrue(all(result == results[0] for result in results))
            self.assertEqual(self.definition, before)
            self.assertFalse(marker.exists())

    def test_semantic_result_matches_javascript_reference(self):
        cases = [deepcopy(self.definition) for _ in range(4)]
        cases[1]["slices"][0]["risk_tier"] = "LOW"
        cases[2]["dependencies"][0]["required_state"] = "PLAN_APPROVED"
        cases[3]["slices"][0]["branch_name"] = "wrong"
        program = """import {validateManualDefinitionSemantics} from "./scripts/lib/manual-planning-v2.mjs";
let text=""; for await (const part of process.stdin) text+=part;
const {cases,facts}=JSON.parse(text);
console.log(JSON.stringify(cases.map(value=>{
  try{validateManualDefinitionSemantics(value,facts);return true;}catch{return false;}
})));"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program],
            input=json.dumps({"cases": cases, "facts": self.facts}),
            text=True,
            capture_output=True,
            check=True,
            cwd=bootstrap.REPOSITORY.parent / "curve",
            timeout=20,
        )
        expected = json.loads(result.stdout)
        actual = []
        for value in cases:
            try:
                validate_definition_semantics(value, self.facts)
                actual.append(True)
            except InvalidPlan:
                actual.append(False)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
