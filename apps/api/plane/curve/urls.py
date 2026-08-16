# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.curve.views import CurveWorkspaceShellEndpoint


urlpatterns = [
    path(
        "workspaces/<str:slug>/curve/",
        CurveWorkspaceShellEndpoint.as_view(),
        name="curve-workspace-shell",
    ),
]
