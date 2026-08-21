# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.test import override_settings

from plane.curve.config import is_curve_enabled_for_workspace
from plane.urls import get_curve_urlpatterns


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("enabled", "allowlist", "slug", "expected"),
    [
        (False, frozenset({"alpha"}), "alpha", False),
        (True, frozenset(), "alpha", False),
        (True, frozenset({"alpha"}), "beta", False),
        (True, frozenset({"alpha"}), "alpha", True),
    ],
)
def test_curve_enablement_fails_closed(enabled, allowlist, slug, expected):
    with override_settings(
        CURVE_ENABLED=enabled,
        CURVE_ENABLED_WORKSPACE_SLUGS=allowlist,
    ):
        assert is_curve_enabled_for_workspace(slug) is expected


def test_disabled_curve_contributes_no_root_url_pattern():
    with override_settings(CURVE_ENABLED=False):
        assert get_curve_urlpatterns() == []


def test_enabled_curve_contributes_one_root_url_pattern():
    with override_settings(CURVE_ENABLED=True):
        patterns = get_curve_urlpatterns()

    assert len(patterns) == 1
    assert str(patterns[0].pattern) == "api/v1/"
