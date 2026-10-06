"""Host unit/HTTP tests; no database qualification is claimed by this suite."""

import copy
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack, nullcontext
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="synthetic-unit-tests-only",
        USE_TZ=True,
        INSTALLED_APPS=[],
        REST_FRAMEWORK={"UNAUTHENTICATED_USER": None},
    )

import django

django.setup()

package = ModuleType("overlay")
package.__path__ = [str(Path(__file__).resolve().parents[3])]
sys.modules["overlay"] = package
reader = import_module("overlay.scope_editor_read_v2")
views = import_module("overlay.scope_editor_read_views_v2")
override_settings = import_module("django.test").override_settings
APIRequestFactory = import_module("rest_framework.test").APIRequestFactory


def uid(n):
    return uuid.UUID(f"30000000-0000-4000-8000-{n:012x}")


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def example(count=3):
    initiative = SimpleNamespace(id=uid(1), workspace_id=uid(2), product_id=uid(3), version=count * 2 + 1)
    head = dict(
        id=uid(4),
        workspace_id=uid(2),
        initiative_id=uid(1),
        product_id=uid(3),
        version=count,
        current_revision_id=uid(100 + count),
    )
    revisions = [
        dict(
            id=uid(100 + seq),
            workspace_id=uid(2),
            initiative_id=uid(1),
            product_id=uid(3),
            proposal_id=uid(4),
            version=seq,
            initiative_version=seq * 2,
            predecessor_id=uid(99 + seq) if seq > 1 else None,
            item_count=0,
            delivery_count=0,
            membership_digest="sha256:" + "a" * 64,
            created_by=uid(5),
            recorded_at=NOW + timedelta(seconds=seq),
            policy_edition="EXPLICIT_EXISTING_WORK_SCOPE_PROPOSAL_V1",
            command_receipt_id=uid(2000 + seq),
        )
        for seq in range(1, count + 1)
    ]
    return initiative, [head], revisions


class LineageTests(unittest.TestCase):
    def test_absent_is_only_empty_graph(self):
        initiative, _, revisions = example()
        self.assertEqual(reader.validate_lineage(initiative, [], []), reader.ScopeSnapshot("ABSENT", 0, ()))
        with self.assertRaises(reader.ScopeEditorUnavailable):
            reader.validate_lineage(initiative, [], revisions)

    def test_empty_saved_selection_is_present_and_version_gaps_are_valid(self):
        snapshot = reader.validate_lineage(*example())
        self.assertEqual((snapshot.status, snapshot.version), ("PRESENT", 3))

    def test_valid_maximum_and_overflow(self):
        self.assertEqual(reader.validate_lineage(*example(1000)).version, 1000)
        with self.assertRaises(reader.ScopeEditorUnavailable):
            reader.validate_lineage(*example(1001))

    def test_rejects_cross_identity_at_every_history_position(self):
        for position in range(3):
            for key in ("workspace_id", "initiative_id", "product_id", "proposal_id"):
                with self.subTest(position=position, key=key):
                    args = example()
                    args[2][position][key] = uid(9999)
                    with self.assertRaises(reader.ScopeEditorUnavailable):
                        reader.validate_lineage(*args)

    def test_rejects_broken_links_duplicate_rows_gaps_and_order(self):
        for change in (
            lambda rows: rows[0].update(predecessor_id=uid(800)),
            lambda rows: rows[1].update(predecessor_id=uid(800)),
            lambda rows: rows[2].update(predecessor_id=uid(101)),
            lambda rows: rows[1].update(id=rows[0]["id"]),
            lambda rows: rows[1].update(version=9),
            lambda rows: rows.reverse(),
            lambda rows: rows.pop(0),
            lambda rows: rows.append(copy.deepcopy(rows[-1])),
        ):
            with self.subTest(change=change):
                args = example()
                change(args[2])
                with self.assertRaises(reader.ScopeEditorUnavailable):
                    reader.validate_lineage(*args)

    def test_rejects_non_monotonic_time_and_initiative_version(self):
        for values in (
            {"recorded_at": NOW},
            {"recorded_at": NOW.replace(tzinfo=None)},
            {"initiative_version": 2},
            {"initiative_version": 100},
            {"initiative_version": True},
        ):
            with self.subTest(values=values):
                args = example()
                args[2][1].update(values)
                with self.assertRaises(reader.ScopeEditorUnavailable):
                    reader.validate_lineage(*args)

    def test_equal_times_are_valid(self):
        args = example()
        for row in args[2]:
            row["recorded_at"] = NOW
        reader.validate_lineage(*args)

    def test_invalid_head_cannot_hide_as_absence(self):
        for values in (
            {"workspace_id": uid(900)},
            {"product_id": uid(900)},
            {"initiative_id": uid(900)},
            {"version": True},
            {"version": 2},
            {"version": 0},
            {"version": 1001},
            {"current_revision_id": uid(101)},
            {"current_revision_id": str(uid(103))},
        ):
            with self.subTest(values=values):
                args = example()
                args[1][0].update(values)
                with self.assertRaises(reader.ScopeEditorUnavailable):
                    reader.validate_lineage(*args)
        args = example()
        args[1].append(copy.deepcopy(args[1][0]))
        with self.assertRaises(reader.ScopeEditorUnavailable):
            reader.validate_lineage(*args)

    def test_invalid_metadata_and_unknown_edition(self):
        for values in (
            {"created_by": "not-a-uuid"},
            {"command_receipt_id": None},
            {"item_count": 101},
            {"delivery_count": 1},
            {"item_count": False},
            {"membership_digest": "sha256:invalid"},
            {"membership_digest": "sha256:" + "a" * 64 + "\n"},
            {"policy_edition": "UNKNOWN"},
        ):
            with self.subTest(values=values):
                args = example()
                args[2][0].update(values)
                with self.assertRaises(reader.ScopeEditorUnavailable):
                    reader.validate_lineage(*args)

    def test_fence_includes_older_metadata(self):
        args = example()
        before = reader.validate_lineage(*args)
        args[2][0]["command_receipt_id"] = uid(900)
        self.assertNotEqual(before, reader.validate_lineage(*args))

    def test_reopened_edition_is_valid(self):
        args = example()
        args[2][-1]["policy_edition"] = "REOPENED_EXISTING_WORK_SCOPE_PROPOSAL_V1"
        reader.validate_lineage(*args)


class ReadQuery:
    """Query spy intentionally exposes no write operation."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select_for_update(self):
        self.calls.append(("lock",))
        return self

    def filter(self, *args, **kwargs):
        self.calls.append(("filter", args, kwargs))
        self.rows = [
            row
            for row in self.rows
            if all(
                getattr(row, key[:-4]) in value if key.endswith("__in") else getattr(row, key) == value
                for key, value in kwargs.items()
            )
        ]
        return self

    def find_by_id(self, **kwargs):
        self.calls.append(("find", kwargs))
        return next(
            (row for row in self.rows if row.id == kwargs["record_id"] and row.workspace_id == kwargs["workspace_id"]),
            None,
        )

    def first(self):
        return self.rows[0] if self.rows else None

    def order_by(self, *fields):
        self.calls.append(("order", fields))
        return self

    def values(self, *fields):
        self.calls.append(("values", fields))
        return self

    def __getitem__(self, selection):
        self.calls.append(("slice", selection.start, selection.stop))
        return self.rows[selection]


class QueryTests(unittest.TestCase):
    def test_initial_fetch_bounded_and_includes_orphans(self):
        initiative, heads, rows = example()
        # Metadata query filtering is captured, not evaluated by this spy.
        head_query, revision_query = ReadQuery([]), ReadQuery(rows)
        head_query.filter = Mock(return_value=head_query)
        head_query.rows = heads
        revision_query.filter = Mock(return_value=revision_query)
        models = SimpleNamespace(
            ScopeProposal=SimpleNamespace(objects=head_query),
            ScopeProposalRevision=SimpleNamespace(objects=revision_query),
        )
        with patch.dict(sys.modules, {"overlay.scope_proposal_models": models}):
            self.assertEqual(reader._metadata_snapshot(initiative).version, 3)
        self.assertIn(("slice", None, 2), head_query.calls)
        self.assertIn(("slice", None, 1001), revision_query.calls)
        condition = revision_query.filter.call_args.args[0]
        self.assertEqual(condition.connector, "OR")
        self.assertEqual(
            dict(condition.children),
            dict(
                initiative_id=initiative.id,
                proposal_id=heads[0]["id"],
                id=heads[0]["current_revision_id"],
            ),
        )
        head_query.filter.assert_called_once_with(initiative_id=initiative.id)


class ActivationTests(unittest.TestCase):
    def test_old_qualification_is_never_a_fallback(self):
        old = Mock()
        loader = SimpleNamespace(require_reopening_qualification=old)
        with patch.dict(sys.modules, {"overlay.scope_reopening_qualification": loader}):
            with self.assertRaises(ImportError):
                reader._require_qualified_successor()
        old.assert_not_called()

    def test_contract_bytes_cannot_be_replaced_under_original_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "contracts"
            shutil.copytree(reader.DIRECTORY, destination)
            (destination / "policy-v2.json").write_text("{}")
            with patch.object(reader, "DIRECTORY", destination):
                with self.assertRaises(reader.ScopeEditorUnavailable):
                    reader.require_contract_integrity()


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.initiative, _, _ = example()
        self.initiative.__dict__.update(
            mode="STANDALONE", state="DRAFT", creator_user_id=uid(5), updated_at=NOW, pending_scope_reopening_id=None
        )
        self.workspace = SimpleNamespace(id=uid(2), slug="synthetic", owner_id=uid(5), updated_at=NOW)
        self.user = SimpleNamespace(id=uid(5), is_active=True, is_bot=False, is_authenticated=True, updated_at=NOW)
        self.membership = SimpleNamespace(
            id=uid(6), workspace_id=uid(2), member_id=uid(5), is_active=True, role=15, updated_at=NOW
        )
        self.product = SimpleNamespace(
            id=uid(3), workspace_id=uid(2), state="ACTIVE", version=1, owner_user_id=uid(5), updated_at=NOW
        )

    def call_authorize(self, **overrides):
        flags = dict(
            CURVE_SCOPE_EDITOR_READ_V2_ENABLED=True,
            CURVE_ENVIRONMENT="LOCAL",
            CURVE_LOCAL_PLANE_INSTALLATION_ID=str(uid(7)),
        )
        flags.update(overrides)
        native = SimpleNamespace(
            **{
                name: SimpleNamespace(objects=ReadQuery([row]))
                for name, row in (
                    ("Workspace", self.workspace),
                    ("User", self.user),
                    ("WorkspaceMember", self.membership),
                )
            }
        )
        models = SimpleNamespace(
            Initiative=SimpleNamespace(objects=ReadQuery([self.initiative])),
            Product=SimpleNamespace(objects=ReadQuery([self.product])),
        )
        modules = {
            "plane": ModuleType("plane"),
            "plane.db": ModuleType("plane.db"),
            "plane.db.models": native,
            "overlay.models": models,
            "overlay.config": SimpleNamespace(is_curve_enabled_for_workspace=lambda s: True),
        }
        with patch.dict(sys.modules, modules), override_settings(**flags):
            return reader._authorize(
                request=SimpleNamespace(user=self.user), workspace_slug="synthetic", initiative_id=uid(1)
            )

    def test_creator_and_current_admin(self):
        self.assertIs(self.call_authorize()[0], self.initiative)
        self.initiative.creator_user_id = uid(999)
        self.membership.role = 20
        self.assertIs(self.call_authorize()[0], self.initiative)

    def test_member_without_creator_authority_denied(self):
        self.initiative.creator_user_id = uid(999)
        with self.assertRaises(reader.ScopeEditorUnavailable):
            self.call_authorize()

    def test_fresh_user_membership_and_product_checks(self):
        for name, key, value in (
            ("user", "is_active", False),
            ("user", "is_bot", True),
            ("membership", "is_active", False),
            ("membership", "role", 99),
            ("product", "state", "ARCHIVED"),
            ("initiative", "state", "PLANNING"),
            ("initiative", "state", "PAUSED"),
            ("initiative", "mode", "ROADMAP"),
        ):
            with self.subTest(name=name, key=key):
                self.setUp()
                setattr(getattr(self, name), key, value)
                with self.assertRaises(reader.ScopeEditorUnavailable):
                    self.call_authorize()

    def test_default_off_local_and_installation_gates(self):
        for flags in (
            {"CURVE_SCOPE_EDITOR_READ_V2_ENABLED": False},
            {"CURVE_SCOPE_EDITOR_READ_V2_ENABLED": "true"},
            {"CURVE_ENVIRONMENT": "PRODUCTION"},
            {"CURVE_LOCAL_PLANE_INSTALLATION_ID": "invalid"},
        ):
            with self.subTest(flags=flags), self.assertRaises((reader.ScopeEditorUnavailable, ValueError)):
                self.call_authorize(**flags)

    def test_fence_captures_version_and_membership_generation(self):
        before = self.call_authorize()[1]
        self.initiative.version += 1
        self.assertNotEqual(before, self.call_authorize()[1])
        self.initiative.version -= 1
        self.membership.updated_at += timedelta(seconds=1)
        self.assertNotEqual(before, self.call_authorize()[1])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.initiative, _, _ = example()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("django.db.transaction.atomic", side_effect=lambda: nullcontext()))
        self.authorize = self.stack.enter_context(
            patch.object(reader, "_authorize", return_value=(self.initiative, ("same",)))
        )
        self.snapshot = self.stack.enter_context(
            patch.object(reader, "_metadata_snapshot", return_value=reader.ScopeSnapshot("ABSENT", 0, ()))
        )
        self.qualify = self.stack.enter_context(patch.object(reader, "_require_qualified_successor"))
        self.integrity = self.stack.enter_context(patch.object(reader, "_verify_current_scope"))

    def read(self, query=None):
        return reader.read_scope_editor_preconditions(
            request=SimpleNamespace(query_params=query or {}), workspace_slug="synthetic", initiative_id=uid(1)
        )

    def test_success_exact_fields_and_absence_still_requires_qualification(self):
        data = self.read()
        self.assertEqual(
            set(data),
            {
                "schema_version",
                "policy_edition",
                "workspace_id",
                "product_id",
                "initiative_id",
                "initiative_version",
                "scope_status",
                "expected_scope_revision",
            },
        )
        self.assertEqual((data["scope_status"], data["expected_scope_revision"]), ("ABSENT", 0))
        self.qualify.assert_called_once()
        self.integrity.assert_called_once()
        self.assertEqual(self.authorize.call_count, 2)

    def test_query_denied_before_authorization(self):
        with self.assertRaises(reader.ScopeEditorUnavailable):
            self.read({"tasks": "include"})
        self.authorize.assert_not_called()

    def test_lineage_bound_checked_before_qualification_or_integrity(self):
        self.snapshot.side_effect = reader.ScopeEditorUnavailable
        with self.assertRaises(reader.ScopeEditorUnavailable):
            self.read()
        self.qualify.assert_not_called()
        self.integrity.assert_not_called()

    def test_authority_change_denies(self):
        self.authorize.side_effect = [(self.initiative, ("before",)), (self.initiative, ("after",))]
        with self.assertRaises(reader.ScopeEditorUnavailable):
            self.read()

    def test_old_lineage_change_denies(self):
        self.snapshot.side_effect = [
            reader.ScopeSnapshot("PRESENT", 3, ("before",)),
            reader.ScopeSnapshot("PRESENT", 3, ("after",)),
        ]
        with self.assertRaises(reader.ScopeEditorUnavailable):
            self.read()

    def test_missing_successor_proof_and_corruption_deny(self):
        for dependency in (self.qualify, self.integrity):
            with self.subTest(dependency=dependency):
                dependency.side_effect = RuntimeError("private diagnostic")
                with self.assertRaises(reader.ScopeEditorUnavailable) as error:
                    self.read()
                self.assertEqual(str(error.exception), "")
                dependency.side_effect = None

    def test_contract_integrity(self):
        reader.require_contract_integrity()
        with patch.object(reader, "MANIFEST_DIGEST", "sha256:" + "0" * 64):
            with self.assertRaises(reader.ScopeEditorUnavailable):
                self.read()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = views.CurveScopeEditorPreconditionsV2Endpoint.as_view()
        self.data = dict(
            schema_version=reader.SCHEMA_VERSION,
            policy_edition=reader.POLICY_EDITION,
            workspace_id=str(uid(2)),
            product_id=str(uid(3)),
            initiative_id=str(uid(1)),
            initiative_version=7,
            scope_status="ABSENT",
            expected_scope_revision=0,
        )

    def request(self, method="get", path="/", authenticated=True, **headers):
        request = getattr(self.factory, method)(path, **headers)
        if authenticated:
            request.user = SimpleNamespace(id=uid(5), is_active=True, is_authenticated=True)
        return request

    def response(self, request):
        response = self.view(request, slug="synthetic", initiative_id=uid(1))
        response.render()
        self.assertEqual(response["Cache-Control"], "no-store")
        return response

    def assert_denied(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content), {"error": "SCOPE_EDITOR_PRECONDITION_UNAVAILABLE"})
        self.assertNotIn("ETag", response)

    def test_success_and_typed_etag(self):
        with patch.object(views, "read_scope_editor_preconditions", return_value=self.data):
            response = self.response(self.request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), self.data)
        self.assertEqual(response["ETag"], f'"curve-initiative:{uid(1)}:v7"')

    def test_anonymous_and_api_key_are_denied(self):
        for headers in ({}, {"HTTP_AUTHORIZATION": "Bearer synthetic-token"}, {"HTTP_X_API_KEY": "synthetic-key"}):
            with self.subTest(headers=headers), patch.object(views, "read_scope_editor_preconditions") as service:
                self.assert_denied(self.response(self.request(authenticated=False, **headers)))
                service.assert_not_called()

    def test_queries_and_unsupported_methods_are_denied(self):
        for method, path in (("get", "/?x=1"), ("get", "/?x=1&x=2"), ("post", "/"), ("options", "/")):
            with (
                self.subTest(method=method, path=path),
                patch.object(views, "read_scope_editor_preconditions") as service,
            ):
                self.assert_denied(self.response(self.request(method, path)))
                service.assert_not_called()

    def test_private_exception_detail_is_never_exposed(self):
        for error in (reader.ScopeEditorUnavailable(), RuntimeError("private source details")):
            with self.subTest(error=error), patch.object(views, "read_scope_editor_preconditions", side_effect=error):
                self.assert_denied(self.response(self.request()))

    def test_head_rechecks_authority(self):
        with patch.object(
            views, "read_scope_editor_preconditions", side_effect=reader.ScopeEditorUnavailable
        ) as service:
            self.assert_denied(self.response(self.request("head")))
            service.assert_called_once()


if __name__ == "__main__":
    unittest.main()
