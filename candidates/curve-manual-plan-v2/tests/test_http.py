# ruff: noqa: E402 -- Configure Django before candidate imports.
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bootstrap

bootstrap.install()

from rest_framework.test import APIRequestFactory
from manual_plan_v2 import contracts, reads, repository, services, views
from test_draft_core import fixture


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.factory = APIRequestFactory(enforce_csrf_checks=True)
        self.id = fixture("revision.valid")["initiative_id"]
        self.user = SimpleNamespace(id=fixture("revision.valid")["created_by"], is_authenticated=True, is_active=True)
        self.headers = dict(HTTP_IF_MATCH=f'"curve-initiative:{self.id}:v9"', HTTP_IDEMPOTENCY_KEY="synthetic-retry")

    def request(self, raw=None, *, csrf=True, authenticated=True, path="/", **headers):
        request = self.factory.post(
            path,
            data=raw if raw is not None else json.dumps(fixture("save.valid")),
            content_type="application/json",
            **(self.headers | headers),
        )
        if authenticated:
            request.user = self.user
        if csrf:
            # Real SessionAuthentication/CSRF middleware token comparison.
            token = "a" * 32
            request.COOKIES["csrftoken"] = token
            request.META["HTTP_X_CSRFTOKEN"] = token
        return request

    def response(self, request, view=None, **kwargs):
        result = (view or views.ManualPlanSaveEndpoint.as_view())(
            request, slug="synthetic", initiative_id=self.id, **kwargs
        )
        result.render()
        self.assertEqual(result["Cache-Control"], "no-store")
        return result

    def error(self, response, suffix, status):
        self.assertEqual(response.status_code, status)
        self.assertEqual(json.loads(response.content), {"error": "MANUAL_PLAN_DRAFT_" + suffix})
        self.assertNotIn("ETag", response)
        self.assertNotIn("Location", response)

    def test_new_save_and_replay_keep_original_location_and_current_etag(self):
        for replay in (False, True):
            with self.subTest(replay=replay):
                data = fixture("revision.valid")
                result = repository.DraftResult(data, 25 if replay else 10, replay)
                with patch.object(services, "save_manual_plan", return_value=result) as service:
                    response = self.response(self.request())
                    self.assertEqual(response.status_code, 200 if replay else 201)
                    self.assertEqual(response["ETag"], f'"curve-initiative:{self.id}:v{result.initiative_version}"')
                    self.assertTrue(response["Location"].endswith(f"revisions/{data['id']}/"))
                    self.assertEqual(service.call_args.kwargs["command"].expected_version, 9)

    def test_missing_csrf_and_anonymous_requests_are_denied_before_service(self):
        for options in (
            {"csrf": False},
            {"authenticated": False},
            {"csrf": False, "HTTP_AUTHORIZATION": "Bearer synthetic"},
        ):
            with self.subTest(options=options), patch.object(services, "save_manual_plan") as service:
                self.error(self.response(self.request(**options)), "UNAVAILABLE", 404)
                service.assert_not_called()

    def test_wrong_csrf_token_and_foreign_origin_are_denied(self):
        for headers in ({"HTTP_X_CSRFTOKEN": "b" * 32}, {"HTTP_ORIGIN": "https://foreign.example.invalid"}):
            request = self.request()
            request.META.update(headers)
            with self.subTest(headers=headers), patch.object(services, "save_manual_plan") as service:
                self.error(self.response(request), "UNAVAILABLE", 404)
                service.assert_not_called()

    def test_body_bound_query_and_invalid_json(self):
        for options, suffix, status in (
            ({"raw": " " * 65537}, "REQUEST_TOO_LARGE", 413),
            ({"raw": '{"x":1,"x":2}'}, "REQUEST_INVALID", 422),
            ({"path": "/?approve=true"}, "REQUEST_INVALID", 422),
        ):
            with self.subTest(options=options), patch.object(services, "save_manual_plan") as service:
                self.error(self.response(self.request(**options)), suffix, status)
                service.assert_not_called()

    def test_missing_preconditions_and_service_errors_remain_closed(self):
        request = self.request()
        del request.META["HTTP_IF_MATCH"]
        self.error(self.response(request), "PRECONDITION_REQUIRED", 428)
        for suffix, status in contracts.ERROR_STATUS.items():
            with (
                self.subTest(suffix=suffix),
                patch.object(services, "save_manual_plan", side_effect=contracts.ManualPlanError(suffix)),
            ):
                self.error(self.response(self.request()), suffix, status)

    def test_private_exception_details_are_never_returned(self):
        with patch.object(services, "save_manual_plan", side_effect=RuntimeError("private filesystem detail")):
            self.error(self.response(self.request()), "UNAVAILABLE", 404)

    def test_current_history_and_status_have_independent_actions(self):
        for action in ("READ_CURRENT", "READ_REVISION", "READ_STATUS"):
            data = fixture("status-current.valid" if action == "READ_STATUS" else "revision.valid")
            view = views.ManualPlanReadEndpoint.as_view(action=action)
            request = self.factory.get("/")
            request.user = self.user
            kwargs = dict(revision_id=data["id"]) if action == "READ_REVISION" else {}
            with (
                self.subTest(action=action),
                patch.object(reads, "read_manual_plan", return_value=reads.ReadResult(data, 30)) as service,
            ):
                response = self.response(request, view, **kwargs)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(service.call_args.kwargs["action"], action)
                self.assertEqual(response["ETag"], f'"curve-initiative:{self.id}:v30"')


if __name__ == "__main__":
    unittest.main()
