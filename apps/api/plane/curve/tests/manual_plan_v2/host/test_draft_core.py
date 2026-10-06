# ruff: noqa: E402 -- Configure Django before candidate imports.
from datetime import datetime, timezone
import importlib.util
import json
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import bootstrap

bootstrap.install()

from manual_plan_v2 import contracts, models, policy, repository
from manual_plan_v2.validation import ROOT, canonical_json, metadata_digest


def fixture(name):
    return json.loads((ROOT / "fixtures" / (name + ".json")).read_text())


def command(payload=None, **changes):
    args = dict(
        initiative_id=uuid.UUID(fixture("revision.valid")["initiative_id"]),
        raw=canonical_json(payload if payload is not None else fixture("save.valid")),
        if_match='"curve-initiative:30000000-0000-4000-8000-000000000002:v9"',
        idempotency_key="synthetic-retry",
    )
    args.update(changes)
    return contracts.parse_save(**args)


def revision():
    return repository._revision_model(
        fixture("revision.valid"),
        identity=fixture("input-identity.valid"),
        validation_receipt=fixture("validation.valid"),
        policy_decision_id=uuid.UUID("30000000-0000-4000-8000-000000000060"),
        event_id=uuid.UUID("30000000-0000-4000-8000-000000000061"),
    )


def initiative(version=9):
    row = revision()
    return SimpleNamespace(
        id=row.initiative_id, workspace_id=row.workspace_id, product_id=row.product_id, version=version
    )


class CommandTests(unittest.TestCase):
    def test_request_identity_binds_target_version_and_payload_not_key(self):
        original = command()
        self.assertEqual(original.request_digest, command(idempotency_key="other-key").request_digest)
        changed = command(if_match='"curve-initiative:30000000-0000-4000-8000-000000000002:v10"')
        self.assertNotEqual(original.request_digest, changed.request_digest)
        payload = original.payload
        payload["expected_draft_revision"] = 3
        self.assertEqual(original.payload["expected_draft_revision"], 0)

    def test_required_headers(self):
        for values in ({"if_match": None}, {"idempotency_key": None}):
            with self.subTest(values=values), self.assertRaises(contracts.ManualPlanError) as error:
                command(**values)
            self.assertEqual(error.exception.status_code, 428)

    def test_closed_body_and_strict_headers(self):
        for values in (
            {"raw": b'{"x":1,"x":2}'},
            {"raw": b"{}"},
            {"raw": b"\xef\xbb\xbf{}"},
            {"if_match": '"9"'},
            {"if_match": "*"},
            {"if_match": 'W/"9"'},
            {"idempotency_key": ""},
            {"idempotency_key": "bad\nkey"},
            {"idempotency_key": "x" * 501},
        ):
            with self.subTest(values=values), self.assertRaises(contracts.ManualPlanError) as error:
                command(**values)
            self.assertEqual(error.exception.status_code, 422)

    def test_bound_precedes_parsing(self):
        with self.assertRaises(contracts.ManualPlanError) as error:
            command(raw=b" " * 65537)
        self.assertEqual(error.exception.status_code, 413)

    def test_unknown_body_field_is_rejected(self):
        payload = fixture("save.valid")
        payload["approve"] = True
        with self.assertRaises(contracts.ManualPlanError):
            command(payload)


class RevisionTests(unittest.TestCase):
    def build(self, **changes):
        stored = revision()
        args = dict(
            initiative=initiative(),
            actor_id=stored.created_by,
            draft_id=stored.draft_id,
            revision_id=stored.id,
            previous=None,
            command=command(),
            identity=fixture("input-identity.valid"),
            receipt=fixture("validation.valid"),
            recorded_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        )
        args.update(changes)
        return contracts.build_revision(**args)

    def test_new_revision_is_metadata_only_and_noncontrolling(self):
        data = self.build()
        self.assertEqual(data["revision"], 1)
        self.assertEqual(data["initiative_version"], 10)
        self.assertFalse(data["controlling"])
        self.assertIsNone(data["predecessor_id"])
        self.assertNotIn("original_input_identity", data)
        self.assertNotIn("slices", data)
        self.assertEqual(data["digest"], metadata_digest(data))

    def test_current_version_and_head_preconditions(self):
        for changes in ({"initiative": initiative(10)}, {"previous": revision()}):
            with self.subTest(changes=changes), self.assertRaises(contracts.ManualPlanError) as error:
                self.build(**changes)
            self.assertEqual(error.exception.status_code, 412)

    def test_next_revision_preserves_predecessor_with_version_gaps(self):
        previous = revision()
        payload = fixture("save.valid")
        payload["expected_draft_revision"] = 1
        request = command(payload, if_match='"curve-initiative:30000000-0000-4000-8000-000000000002:v15"')
        data = self.build(initiative=initiative(15), command=request, previous=previous, revision_id=uuid.uuid4())
        self.assertEqual(data["predecessor_id"], str(previous.id))
        self.assertEqual(data["revision"], 2)
        self.assertEqual(data["initiative_version"], 16)

    def test_wrong_validation_digest_or_original_inputs_are_rejected(self):
        for name, key in (("identity", "digest"), ("receipt", "digest"), ("receipt", "input_identity_digest")):
            value = fixture("input-identity.valid" if name == "identity" else "validation.valid")
            value[key] = "sha256:" + "0" * 64
            with self.subTest(name=name, key=key), self.assertRaises(contracts.ManualPlanError):
                self.build(**{name: value})

    def test_private_fields_are_detached_and_projection_is_revalidated(self):
        row = revision()
        self.assertEqual(row.as_record(), fixture("revision.valid"))
        data = row.as_record()
        data["definition_ref"]["object_id"] = str(uuid.uuid4())
        self.assertEqual(row.as_record(), fixture("revision.valid"))
        row.payload["created_by"] = str(uuid.uuid4())
        row.payload["digest"] = metadata_digest(row.payload)
        row.digest = row.payload["digest"]
        with self.assertRaises(contracts.ManualPlanError):
            row.as_record()

    def test_row_or_private_receipt_substitution_is_rejected(self):
        for field, value in (
            ("workspace_id", uuid.uuid4()),
            ("version", 2),
            ("initiative_version", 11),
            ("validation_receipt_digest", "sha256:" + "0" * 64),
            ("input_identity_digest", "sha256:" + "0" * 64),
        ):
            with self.subTest(field=field):
                row = revision()
                setattr(row, field, value)
                with self.assertRaises(contracts.ManualPlanError):
                    row.as_record()

    def test_event_has_no_bodies_and_original_request_is_reconstructible(self):
        row = revision()
        data = contracts.event_payload(row)
        self.assertEqual(data, fixture("event.valid"))
        self.assertEqual(repository.request_digest_from_revision(row), command().request_digest)


class ModelGuardTests(unittest.TestCase):
    def setUp(self):
        self.row = revision()
        self.head = models.ManualPlanDraftV2(
            id=self.row.draft_id,
            workspace_id=self.row.workspace_id,
            initiative_id=self.row.initiative_id,
            product_id=self.row.product_id,
            version=1,
            current_revision_id=self.row.id,
        )
        self.receipt = policy.WriteReceipt(
            self.row.workspace_id,
            self.row.product_id,
            self.row.initiative_id,
            self.row.created_by,
            self.row.policy_decision_id,
            "synthetic",
            command().request_digest,
            self.row.input_identity_digest,
            self.row.validation_receipt_digest,
            policy._TOKEN,
        )
        self.atomic = patch("django.db.transaction.get_connection", return_value=SimpleNamespace(in_atomic_block=True))
        self.atomic.start()
        self.addCleanup(self.atomic.stop)

    def test_no_active_receipt_forbids_instance_and_bulk_writes(self):
        for fn in (
            self.row.save,
            self.row.delete,
            self.head.save,
            self.head.delete,
            lambda: models.ManualPlanRevisionV2.objects.all().update(version=2),
            lambda: models.ManualPlanRevisionV2.objects.bulk_create([self.row]),
            lambda: models.ManualPlanRevisionV2.objects.bulk_update([self.row], ["version"]),
            lambda: models.ManualPlanRevisionV2.objects.all().delete(),
        ):
            with self.subTest(fn=fn), self.assertRaises(PermissionError):
                fn()

    def test_forged_receipt_is_not_active(self):
        with self.assertRaises(PermissionError):
            policy.assert_active_receipt(self.receipt)

    def test_exact_record_guard_rejects_mutation_and_restores_context(self):
        token = policy._ACTIVE.set(self.receipt)
        try:
            with repository._write_records(self.receipt, self.head, self.row):
                repository.assert_draft_write(self.row)
                self.row.payload["created_by"] = str(uuid.uuid4())
                with self.assertRaises(PermissionError):
                    repository.assert_draft_write(self.row)
            with self.assertRaises(PermissionError):
                repository.assert_draft_write(self.head)
        finally:
            policy._ACTIVE.reset(token)

    def test_wrong_workspace_receipt_and_existing_revision_rewrite_are_denied(self):
        token = policy._ACTIVE.set(self.receipt)
        try:
            with repository._write_records(self.receipt, self.head, self.row):
                self.row._state.adding = False
                with self.assertRaises(PermissionError):
                    self.row.save()
            self.head.workspace_id = uuid.uuid4()
            with self.assertRaises(contracts.ManualPlanError):
                with repository._write_records(self.receipt, self.head, self.row):
                    pass
        finally:
            policy._ACTIVE.reset(token)


class MigrationPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location = bootstrap.RUNTIME_ROOT / "migrations/0024_manual_draft_reconstruction.py"
        spec = importlib.util.spec_from_file_location("candidate_migration", location)
        cls.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.migration)

    def test_unqualified_migration_stops_before_any_sql(self):
        schema_editor = Mock()
        with (
            patch.object(self.migration, "CURRENT_CATALOG_DIGEST", None),
            self.assertRaisesRegex(RuntimeError, "POSTGRESQL_QUALIFICATION_REQUIRED"),
        ):
            self.migration.verify_predecessor(None, schema_editor)
        schema_editor.connection.cursor.assert_not_called()

    def test_frozen_sql_schemas_match_contracts_without_runtime_file_reads(self):
        schemas = {
            value["$id"]: value for path in ROOT.glob("*.schema.json") for value in [json.loads(path.read_text())]
        }

        def resolve(value):
            if isinstance(value, list):
                return [resolve(item) for item in value]
            if not isinstance(value, dict):
                return value
            if "$ref" in value:
                self.assertEqual(set(value), {"$ref"})
                base, _, pointer = value["$ref"].partition("#")
                target = schemas[base]
                if pointer:
                    for part in pointer.lstrip("/").split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                return resolve(target)
            return {key: resolve(item) for key, item in value.items()}

        names = dict(
            revision="manual-plan-draft-revision-v2",
            identity="manual-plan-input-identity-v2",
            validation="manual-plan-validation-receipt-v2",
            event="manual-plan-draft-event-v2",
        )
        literals = dict(re.findall(r" WHEN '([^']+)' THEN '((?:[^']|'')*)'::jsonb", self.migration.SCHEMA_SQL))
        self.assertEqual(set(literals), set(names))
        for key, name in names.items():
            expected = resolve(json.loads((ROOT / (name + ".schema.json")).read_text()))
            self.assertEqual(json.loads(literals[key].replace("''", "'")), expected)

    def test_snapshot_matches_canonical_curve_contract_bytes(self):
        source = bootstrap.REPOSITORY.parent / "curve/contracts/candidates/manual-planning-v2"
        for path in ROOT.rglob("*.json"):
            self.assertEqual(path.read_bytes(), (source / path.relative_to(ROOT)).read_bytes(), path.name)

    def test_exact_candidate_model_inventory(self):
        delta = json.loads((ROOT / "qualification-delta-v2.json").read_text())
        actual = sorted(
            (
                dict(
                    model_name=m._meta.model_name,
                    db_table=m._meta.db_table,
                    columns=sorted(f.column for f in m._meta.local_fields),
                )
                for m in (models.ManualPlanDraftV2, models.ManualPlanRevisionV2)
            ),
            key=lambda m: m["model_name"],
        )
        self.assertEqual(actual, delta["draft_successor"]["models_added"])

    def test_generated_migration_state_matches_models(self):
        from django.db.migrations.state import ModelState
        from django.db.migrations.operations.models import CreateModel

        operations = [op for op in self.migration.Migration.operations if isinstance(op, CreateModel)]
        self.assertEqual(len(operations), 2)
        for op, model in zip(operations, (models.ManualPlanDraftV2, models.ManualPlanRevisionV2)):
            state = ModelState.from_model(model)
            self.assertEqual(op.name, state.name)
            self.assertEqual(op.options, state.options)
            self.assertEqual(
                {name: field.deconstruct()[1:] for name, field in op.fields},
                {name: field.deconstruct()[1:] for name, field in state.fields.items()},
            )

    def test_all_23_predecessor_byte_pins_match_restored_source(self):
        import hashlib

        root = bootstrap.RUNTIME_ROOT / "migrations"
        self.assertEqual(len(self.migration.PREDECESSOR_MIGRATIONS), 23)
        for name, expected in self.migration.PREDECESSOR_MIGRATIONS.items():
            self.assertEqual("sha256:" + hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)

    def test_empty_reverse_gate_refuses_retained_evidence(self):
        cursor = Mock()
        cursor.fetchone.return_value = (True,)
        context = Mock()
        context.__enter__ = Mock(return_value=cursor)
        context.__exit__ = Mock(return_value=False)
        editor = Mock()
        editor.connection.cursor.return_value = context
        with self.assertRaisesRegex(RuntimeError, "RETAINED_EVIDENCE"):
            self.migration.require_empty_reverse(None, editor)


if __name__ == "__main__":
    unittest.main()
