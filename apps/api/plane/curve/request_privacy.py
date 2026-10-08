# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Early request classification; available before authentication or URL dispatch."""

import re

PRD_COMMAND_MAX_BYTES = 65536
_CURVE = re.compile(r"^/api/v1/workspaces/[^/]+/curve(?:/|$)")
_PRD = re.compile(r"^/api/v1/workspaces/[^/]+/curve/initiatives/[^/]+/prd/(submit|approve|return-for-revision)/?$")
_SCOPED_PRD = re.compile(
    r"^/api/v1/workspaces/[^/]+/curve/initiatives/[^/]+/scoped-prd/v1/"
    r"(observations|submit|approve|return-for-revision)/?$"
)

_REOPENING = re.compile(r"^/api/v1/workspaces/[^/]+/curve/initiatives/[^/]+/scope-reopening/v1/reopen-and-replace/?$")


def is_curve_request(request):
    return bool(_CURVE.match(request.path_info))


def is_prd_command_request(request):
    return bool(
        _PRD.fullmatch(request.path_info)
        or _SCOPED_PRD.fullmatch(request.path_info)
        or _REOPENING.fullmatch(request.path_info)
    )


SCOPE_PROPOSAL_MAX_BYTES = 65536
_SCOPE = re.compile(r"^/api/v1/workspaces/[^/]+/curve/initiatives/[^/]+/scope-proposal/?$")


def is_scope_proposal_request(request):
    return bool(_SCOPE.fullmatch(request.path_info))
