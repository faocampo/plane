# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
import gzip

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from plane.middleware.curve_gzip import CurveAwareGZipMiddleware

pytestmark = pytest.mark.unit
PATH = "/api/v1/workspaces/example/curve/products/example/roadmaps/example/milestones/"
BODY = b"synthetic-response " * 100
TAG = '"curve-roadmap:00000000-0000-4000-8000-000000000001:v2"'


def response(path=PATH, tag=TAG, encoding="gzip"):
    value = HttpResponse(BODY, content_type="application/json")
    value["Cache-Control"] = "no-store"
    if tag is not None:
        value["ETag"] = tag
    request = RequestFactory().get(path, HTTP_ACCEPT_ENCODING=encoding)
    return CurveAwareGZipMiddleware(lambda _: value)(request)


def test_browser_compression_cannot_weaken_curve_write_version():
    value = response()
    assert value["ETag"] == TAG
    assert value.content == BODY
    assert "Content-Encoding" not in value
    assert value["Cache-Control"] == "no-store"


@pytest.mark.parametrize("tag", [None, "W/" + TAG])
def test_unversioned_and_weak_curve_responses_retain_normal_gzip(tag):
    value = response(tag=tag)
    assert value["Content-Encoding"] == "gzip"
    assert gzip.decompress(value.content) == BODY
    assert value.get("ETag") == tag


@pytest.mark.parametrize("path", ["/api/workspaces/example/members/", "/api/v1/workspaces/example/not-curve/"])
def test_other_routes_keep_standard_compression_and_weakening(path):
    value = response(path=path)
    assert value["Content-Encoding"] == "gzip"
    assert value["ETag"] == "W/" + TAG
    assert gzip.decompress(value.content) == BODY


def test_identity_request_retains_response_bytes_and_validator():
    value = response(encoding="identity")
    assert value.content == BODY and value["ETag"] == TAG
    assert "Content-Encoding" not in value
