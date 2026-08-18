# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings


CURVE_ENVIRONMENTS = frozenset({"LOCAL", "STAGING", "PRODUCTION"})


class CurvePolicyConfigurationError(RuntimeError):
    pass


def is_curve_enabled_for_workspace(workspace_slug: str) -> bool:
    """Return the fail-closed local enablement decision for one workspace."""

    return bool(settings.CURVE_ENABLED and workspace_slug and workspace_slug in settings.CURVE_ENABLED_WORKSPACE_SLUGS)


def curve_environment() -> str:
    environment = getattr(settings, "CURVE_ENVIRONMENT", "")
    if environment not in CURVE_ENVIRONMENTS:
        raise CurvePolicyConfigurationError("CURVE_ENVIRONMENT is not configured")
    return environment


def curve_policy_recorder() -> dict[str, str]:
    actor_id = getattr(settings, "CURVE_POLICY_RECORDER_ACTOR_ID", "")
    if not isinstance(actor_id, str) or not actor_id or len(actor_id) > 255:
        raise CurvePolicyConfigurationError("CURVE_POLICY_RECORDER_ACTOR_ID is not configured")
    return {"actor_type": "SERVICE", "actor_id": actor_id}


def validate_curve_policy_configuration():
    """Fail closed when an enabled Curve process lacks trusted policy inputs."""

    if not settings.CURVE_ENABLED:
        return
    curve_environment()
    curve_policy_recorder()
