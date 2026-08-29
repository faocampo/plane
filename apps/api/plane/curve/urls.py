# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.curve.views import (
    CurveEventStreamEndpoint,
    CurveFoundationProbeEndpoint,
    CurveOperationCancelEndpoint,
    CurveOperationDetailEndpoint,
    CurveOperationListEndpoint,
    CurveProductArchiveEndpoint,
    CurveProductDetailEndpoint,
    CurveProductListEndpoint,
    CurveProductOwnerEndpoint,
    CurveProductRestoreEndpoint,
    CurveWorkspaceShellEndpoint,
)


urlpatterns = [
    path(
        "workspaces/<str:slug>/curve/",
        CurveWorkspaceShellEndpoint.as_view(),
        name="curve-workspace-shell",
    ),
    path(
        "workspaces/<str:slug>/curve/operations/",
        CurveOperationListEndpoint.as_view(),
        name="curve-operation-list",
    ),
    path(
        "workspaces/<str:slug>/curve/operations/<uuid:resource_id>/",
        CurveOperationDetailEndpoint.as_view(),
        name="curve-operation-detail",
    ),
    path(
        "workspaces/<str:slug>/curve/operations/<uuid:resource_id>/cancel/",
        CurveOperationCancelEndpoint.as_view(),
        name="curve-operation-cancel",
    ),
    path(
        "workspaces/<str:slug>/curve/products/",
        CurveProductListEndpoint.as_view(),
        name="curve-product-list",
    ),
    path(
        "workspaces/<str:slug>/curve/products/<uuid:product_id>/",
        CurveProductDetailEndpoint.as_view(),
        name="curve-product-detail",
    ),
    path(
        "workspaces/<str:slug>/curve/products/<uuid:product_id>/owner/",
        CurveProductOwnerEndpoint.as_view(),
        name="curve-product-owner",
    ),
    path(
        "workspaces/<str:slug>/curve/products/<uuid:product_id>/archive/",
        CurveProductArchiveEndpoint.as_view(),
        name="curve-product-archive",
    ),
    path(
        "workspaces/<str:slug>/curve/products/<uuid:product_id>/restore/",
        CurveProductRestoreEndpoint.as_view(),
        name="curve-product-restore",
    ),
    path(
        "workspaces/<str:slug>/curve/events/",
        CurveEventStreamEndpoint.as_view(),
        name="curve-event-stream",
    ),
    path(
        "workspaces/<str:slug>/curve/foundation-probes/",
        CurveFoundationProbeEndpoint.as_view(),
        name="curve-foundation-probe",
    ),
]
