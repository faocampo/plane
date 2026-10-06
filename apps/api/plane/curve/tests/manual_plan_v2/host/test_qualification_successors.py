"""Structural successor review tests only; no proof hash or DB catalog is approved."""

# ruff: noqa: E402
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bootstrap

bootstrap.install()


class SuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = bootstrap.RUNTIME_ROOT
        source = cls.root / "scope_reopening_qualification.py"
        spec = importlib.util.spec_from_file_location("plane.curve.successor_candidate", source)
        cls.module = importlib.util.module_from_spec(spec)
        modules = {
            "plane.curve.prd_commands": SimpleNamespace(PrdCommandError=RuntimeError),
            "plane.curve.scope_reopening_contracts": SimpleNamespace(require_reopening_contract_integrity=lambda: None),
        }
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(cls.module)
        original = cls.root / "project_association_read_qualification.json"
        cls.predecessor = json.loads(original.read_text())["qualification"]

    def successor(self):
        m = self.module
        qualified = deepcopy(self.predecessor)
        qualified["model_edition"] = m._MANUAL_EDITION
        qualified["models"] = sorted(
            qualified["models"] + m._MANUAL_ADDED_MODELS, key=lambda value: value["model_name"]
        )
        qualified["runtime_writer_inventory"].append(m._MANUAL_WRITER)
        qualified["migration_digests"][m._MANUAL_MIGRATION] = "sha256:" + "a" * 64
        for name in m._MANUAL_ADDED_MODULES | m._MANUAL_REPLACED_MODULES:
            qualified["runtime_sources"][name] = "sha256:" + "b" * 64
        qualified["physical_catalog_digest"] = "sha256:" + "c" * 64
        return dict(
            schema_version="curve.manual-plan-draft-reconstruction-qualification/v2-candidate",
            predecessor_digest=m.READ_SUCCESSOR_DIGEST,
            writer_edition=m._MANUAL_WRITER,
            qualification=qualified,
        )

    def test_exact_declared_delta_is_structurally_accepted_without_approving_hashes(self):
        successor = self.successor()
        self.assertEqual(self.module.validate_manual_successor(self.predecessor, successor), successor["qualification"])
        self.assertRegex(self.module.MANUAL_SUCCESSOR_DIGEST, r"^sha256:[0-9a-f]{64}$")
        self.assertIsNone(self.module.SCOPE_EDITOR_SUCCESSOR_DIGEST)

    def test_missing_extra_or_changed_historical_source_is_rejected(self):
        for change in (
            lambda q: q["runtime_sources"].update({"new_unreviewed.py": "sha256:" + "d" * 64}),
            lambda q: q["runtime_sources"].pop("manual_plan_v2/policy.py"),
            lambda q: q["runtime_sources"].update({"services.py": "sha256:" + "e" * 64}),
        ):
            successor = self.successor()
            change(successor["qualification"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.validate_manual_successor(self.predecessor, successor)

    def test_model_migration_writer_and_exclusion_changes_fail_closed(self):
        changes = [
            lambda q: q["models"][0]["columns"].append("surprise"),
            lambda q: q["migration_digests"].update({"0001_initial.py": "sha256:" + "f" * 64}),
            lambda q: q["runtime_writer_inventory"].append("PLAN_APPROVAL"),
            lambda q: q["excluded_writers"].remove("PLAN_APPROVAL"),
            lambda q: q.update(physical_catalog_digest=self.predecessor["physical_catalog_digest"]),
        ]
        for change in changes:
            successor = self.successor()
            change(successor["qualification"])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.validate_manual_successor(self.predecessor, successor)

    def test_wrong_predecessor_and_unknown_fields_are_rejected(self):
        for changes in ({"predecessor_digest": "sha256:" + "0" * 64}, {"approved": True}):
            successor = self.successor() | changes
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.module.validate_manual_successor(self.predecessor, successor)

    def test_read_successor_cannot_add_writers_models_or_storage(self):
        prior = self.successor()["qualification"]
        qualified = deepcopy(prior)
        for name in self.module._SCOPE_EDITOR_ADDED_MODULES | {"urls.py"}:
            qualified["runtime_sources"][name] = "sha256:" + "9" * 64
        successor = dict(
            schema_version="curve.scope-editor-read-reconstruction-qualification/v2-candidate",
            predecessor_digest="sha256:" + "8" * 64,
            read_edition="LOCAL_SCOPE_EDITOR_PRECONDITION_RECONSTRUCTION_V2",
            qualification=qualified,
        )
        self.assertEqual(
            self.module.validate_scope_editor_successor(prior, successor, successor["predecessor_digest"]), qualified
        )
        qualified["runtime_writer_inventory"].append("EXECUTION")
        with self.assertRaises(ValueError):
            self.module.validate_scope_editor_successor(prior, successor, successor["predecessor_digest"])

    def test_unreviewed_pin_stops_before_reading_proof(self):
        with self.assertRaises(ValueError):
            self.module._read_pinned_successor(Path("missing-private-proof.json"), None)
