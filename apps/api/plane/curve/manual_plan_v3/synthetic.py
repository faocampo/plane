# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Fixed local two-stage resolver; shares protected file and grant enforcement."""

import os

from plane.curve.manual_plan_v2.contracts import require
from plane.curve.manual_plan_v2.synthetic import (
    SyntheticManualPlanResolverV2,
    _stamp,
    advance_native_authority as advance_native_authority,
)


EDITION = "FIXED_SYNTHETIC_LOCAL_MANUAL_PLAN_V3"


class SyntheticManualPlanResolverV3(SyntheticManualPlanResolverV2):
    def __init__(self, root):
        require(type(self) is SyntheticManualPlanResolverV3, "EDITION_UNAVAILABLE")
        self.root = root
        self.root_fd = self._open_root(root)
        self.root_stamp = _stamp(os.fstat(self.root_fd))

    @classmethod
    def from_settings(cls):
        from django.conf import settings

        require(cls is SyntheticManualPlanResolverV3, "EDITION_UNAVAILABLE")
        require(getattr(settings, "CURVE_ENVIRONMENT", None) == "LOCAL", "EDITION_UNAVAILABLE")
        return cls(getattr(settings, "CURVE_MANUAL_PLAN_V3_SYNTHETIC_ROOT", None))

    @staticmethod
    def _decode_catalog(raw):
        return SyntheticManualPlanResolverV2._decode_catalog(raw, _edition=3)
