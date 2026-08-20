# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bounded settings for the D-003 local Curve Temporal worker."""

import os

from .common import *  # noqa: F403


DEBUG = False
CURVE_ENVIRONMENT = "LOCAL"
CURVE_POLICY_RECORDER_ACTOR_ID = os.environ.get("TEMPORAL_WORKER_IDENTITY", "")

# The worker needs Django models and the Curve application service boundary. It
# does not serve HTTP, create sessions, send mail, use shared cache, or access
# object storage.
MIDDLEWARE = []
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "curve-temporal-worker",
    }
}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_ROOT = "/tmp/curve-worker-media"
STATIC_ROOT = "/tmp/curve-worker-static"

# Fail closed even if a library tries to dispatch Plane background work from
# this process. No broker endpoint or result backend is configured.
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_IMPORTS = ()
# Plane constructs its Celery Redis client while importing the package. Keep
# that inert client loopback-only; the Curve worker never starts or calls it.
REDIS_URL = "redis://127.0.0.1:6379/0"
REDIS_SSL = False

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "curve_safe": {
            "format": "%(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "curve_safe",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}
