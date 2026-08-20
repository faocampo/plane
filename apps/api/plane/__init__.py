# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os


if os.environ.get("DJANGO_SETTINGS_MODULE") == "plane.settings.curve_worker":
    celery_app = None
else:
    from .celery import app as celery_app

__all__ = ("celery_app",)
