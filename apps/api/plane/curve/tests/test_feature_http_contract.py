# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""HTTP boundary checks with service doubles; native session tests are separate."""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from plane.curve.feature_editor_rules import FeatureEditorFacts, feature_editor_reason
from plane.curve.feature_read import _metadata, _read_reason
from plane.curve.feature_services import FeatureCommandError
from plane.curve.feature_views import FeatureDetailEndpoint, FeatureListEndpoint

PRODUCT = UUID("00000000-0000-0000-0000-000000000001")
FEATURE = UUID("00000000-0000-0000-0000-000000000002")
ACTOR = UUID("00000000-0000-0000-0000-000000000003")


@override_settings(
    CURVE_FEATURE_COMMANDS_ENABLED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class FeatureHTTPContractTests(SimpleTestCase):
    def call(self, method="get", *, detail=False, query="", data=None, **headers):
        request = getattr(APIRequestFactory(), method)("/" + query, data=data, format="json", **headers)
        force_authenticate(
            request, SimpleNamespace(id=ACTOR, is_authenticated=True, is_active=True, user_timezone="UTC")
        )
        endpoint = FeatureDetailEndpoint if detail else FeatureListEndpoint
        kwargs = {"slug": "synthetic-workspace", "product_id": PRODUCT}
        if detail:
            kwargs["feature_id"] = FEATURE
        return endpoint.as_view()(request, **kwargs)

    def test_default_off_blocks_before_service_and_disables_caching(self):
        with (
            override_settings(CURVE_FEATURE_COMMANDS_ENABLED=False),
            patch("plane.curve.feature_views.read_features") as read,
        ):
            result = self.call()
        self.assertEqual(result.status_code, 404)
        self.assertEqual(result["Cache-Control"], "no-store")
        read.assert_not_called()

    def test_closed_bounded_list_queries_reject_before_service(self):
        for query in (
            "?page_size=0",
            "?page_size=101",
            "?page_size=01",
            "?page_size=1&page_size=2",
            "?after=invalid",
            "?extra=1",
        ):
            with self.subTest(query=query), patch("plane.curve.feature_views.read_features") as read:
                self.assertEqual(self.call(query=query).status_code, 422)
                read.assert_not_called()

    def test_valid_cursor_and_page_are_forwarded_as_typed_values(self):
        with patch(
            "plane.curve.feature_views.read_features", return_value={"results": [], "next_cursor": None}
        ) as read:
            self.assertEqual(self.call(query=f"?page_size=100&after={FEATURE}").status_code, 200)
            self.assertEqual(read.call_args.kwargs["after"], FEATURE)
            self.assertEqual(read.call_args.kwargs["page_size"], 100)

    def test_detail_query_and_missing_or_foreign_version_never_execute(self):
        cases = (
            {},
            {"HTTP_IF_MATCH": f'"curve-feature:{PRODUCT}:v1"'},
            {"HTTP_IF_MATCH": f'"curve-feature:{FEATURE}:v0"'},
            {"HTTP_IF_MATCH": f'"curve-feature:{FEATURE}:v9223372036854775808"'},
        )
        for headers in cases:
            with self.subTest(headers=headers), patch("plane.curve.feature_views.execute_feature_command") as command:
                result = self.call("patch", detail=True, data={}, **headers)
                self.assertEqual(result.status_code, 428 if not headers else 412)
                command.assert_not_called()
        with patch("plane.curve.feature_views.read_features") as read:
            self.assertEqual(self.call(detail=True, query="?extra=1").status_code, 422)
            read.assert_not_called()

    def test_creation_rejects_if_match_and_requires_idempotency(self):
        with patch("plane.curve.feature_views.execute_feature_command") as command:
            self.assertEqual(self.call("post", data={}, HTTP_IF_MATCH='"any"').status_code, 422)
            self.assertEqual(self.call("post", data={}).status_code, 422)
            command.assert_not_called()

    def test_update_forwards_version_and_returns_retained_receipt(self):
        ref = {"resource_type": "FEATURE", "resource_id": str(FEATURE), "resource_version": 8}
        receipt = SimpleNamespace(resource_ref=ref, response_status=200, replayed=True)
        with patch("plane.curve.feature_views.execute_feature_command", return_value=receipt) as command:
            response = self.call(
                "patch",
                detail=True,
                data={"name": "Example", "description": None},
                HTTP_IF_MATCH=f'"curve-feature:{FEATURE}:v7"',
                HTTP_IDEMPOTENCY_KEY="synthetic-update",
            )
            self.assertEqual(command.call_args.kwargs["action"], "UPDATE_FEATURE")
            self.assertEqual(command.call_args.kwargs["expected_version"], 7)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"resource_ref": ref})
        self.assertEqual(response["ETag"], f'"curve-feature:{FEATURE}:v8"')
        self.assertEqual(response["Idempotent-Replay"], "true")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response["Location"].endswith(f"features/{FEATURE}/"))

    def test_internal_command_messages_are_not_exposed(self):
        with patch(
            "plane.curve.feature_views.execute_feature_command",
            side_effect=FeatureCommandError("synthetic-internal-detail"),
        ):
            response = self.call("post", data={}, HTTP_IDEMPOTENCY_KEY="synthetic-create")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("synthetic-internal-detail", str(response.data))


class FeatureReadProjectionTests(TestCase):
    def test_list_metadata_never_contains_protected_reference(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row = SimpleNamespace(
            id=FEATURE,
            version=3,
            name="Example",
            created_at=now,
            updated_at=now,
            description={"object_id": "synthetic-protected-object"},
        )
        self.assertEqual(set(_metadata(row)), {"id", "version", "name", "created_at", "updated_at"})

    def test_reading_metadata_does_not_require_editor_grant(self):
        facts = FeatureEditorFacts(
            workspace_id=PRODUCT,
            product_id=PRODUCT,
            actor_id=ACTOR,
            owner_id=FEATURE,
            actor_active_human=True,
            actor_active_member=True,
            actor_administrator=False,
            product_active=True,
            product_format_supported=True,
            feature_enabled=True,
        )
        self.assertEqual(_read_reason(facts), "ALLOW")
        self.assertEqual(feature_editor_reason("CREATE_FEATURE", facts), "PRODUCT_OWNER_OR_FEATURE_EDITOR_REQUIRED")
        for key in (
            "actor_active_human",
            "actor_active_member",
            "product_active",
            "product_format_supported",
            "feature_enabled",
        ):
            with self.subTest(key=key):
                self.assertNotEqual(_read_reason(replace(facts, **{key: False})), "ALLOW")
