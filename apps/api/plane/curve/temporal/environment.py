# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os


REQUIRED_ENVIRONMENT = frozenset(
    {
        "DJANGO_SETTINGS_MODULE",
        "DATABASE_URL",
        "CURVE_ENABLED",
        "CURVE_ENABLED_WORKSPACE_SLUGS",
        "TEMPORAL_ADDRESS",
        "TEMPORAL_NAMESPACE",
        "TEMPORAL_TASK_QUEUE",
        "TEMPORAL_WORKER_IDENTITY",
        "LOG_LEVEL",
    }
)
FORBIDDEN_EXACT = frozenset(
    {
        "AMQP_URL",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "RABBITMQ_HOST",
        "RABBITMQ_PASSWORD",
        "RABBITMQ_USER",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_ACCESS_TOKEN",
        "GITLAB_TOKEN",
        "SMTP_PASSWORD",
    }
)
FORBIDDEN_PREFIXES = ("OPENAI_", "ANTHROPIC_", "ONYX_", "OPENHANDS_", "ORCA_", "VCS_")


def validate_worker_environment(environment=None) -> None:
    environment = environment or os.environ
    missing = sorted(key for key in REQUIRED_ENVIRONMENT if not environment.get(key))
    if missing:
        raise RuntimeError(f"Curve worker environment is missing required keys: {','.join(missing)}")
    if environment["DJANGO_SETTINGS_MODULE"] != "plane.settings.curve_worker":
        raise RuntimeError("Curve worker settings module is invalid")
    forbidden = sorted(
        key
        for key, value in environment.items()
        if value and (key in FORBIDDEN_EXACT or any(key.startswith(prefix) for prefix in FORBIDDEN_PREFIXES))
    )
    if forbidden:
        raise RuntimeError(f"Curve worker received forbidden environment keys: {','.join(forbidden)}")
