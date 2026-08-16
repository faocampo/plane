# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings


def is_curve_enabled_for_workspace(workspace_slug: str) -> bool:
    """Return the fail-closed local enablement decision for one workspace."""

    return bool(settings.CURVE_ENABLED and workspace_slug and workspace_slug in settings.CURVE_ENABLED_WORKSPACE_SLUGS)
