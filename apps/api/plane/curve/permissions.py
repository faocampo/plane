# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission

from plane.curve.config import CurvePolicyConfigurationError
from plane.curve.policy_manifest import PolicyManifestIntegrityError
from plane.curve.policy_services import (
    CurvePolicyDenied,
    CurvePolicyResourceNotFound,
    authorize_query,
)


_RECEIPT_ATTRIBUTE = "_curve_policy_receipt"


class CurveCorePolicyPermission(BasePermission):
    """Authorize a Curve query and persist its exact decision/audit evidence."""

    def has_permission(self, request, view):
        action = getattr(view, "curve_policy_action", None)
        resource_type = getattr(view, "curve_policy_resource_type", None)
        if not action or not resource_type:
            return False
        try:
            receipt = authorize_query(
                request=request,
                action=action,
                workspace_slug=view.kwargs.get("slug"),
                resource_type=resource_type,
                resource_id=view.kwargs.get("resource_id"),
            )
        except CurvePolicyResourceNotFound as error:
            raise NotFound() from error
        except CurvePolicyDenied as error:
            if "FEATURE_DISABLED" in error.reason_codes:
                raise NotFound() from error
            return False
        except (CurvePolicyConfigurationError, PolicyManifestIntegrityError):
            return False

        setattr(request, _RECEIPT_ATTRIBUTE, receipt)
        return True


def query_authorization_receipt(request):
    receipt = getattr(request, _RECEIPT_ATTRIBUTE, None)
    if receipt is None:
        raise PermissionError("Curve query authorization receipt is required")
    return receipt
