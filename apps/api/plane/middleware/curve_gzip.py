# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Preserve strong Curve version validators used as write preconditions."""

import re

from django.middleware.gzip import GZipMiddleware

_CURVE_ROUTE = re.compile(r"^/api/v1/workspaces/[^/]+/curve/")


class CurveAwareGZipMiddleware(GZipMiddleware):
    def process_response(self, request, response):
        etag = response.get("ETag", "")
        if _CURVE_ROUTE.match(request.path_info) and etag.startswith('"') and etag.endswith('"'):
            # Django weakens a strong ETag when it compresses the representation.
            # Curve clients require the original strong version for If-Match.
            # Keep this representation unchanged rather than strengthening a weak tag.
            return response
        return super().process_response(request, response)
