# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Host-only test bootstrap. No database backend or full Plane app is configured."""

from pathlib import Path
import os
import sys

RUNTIME_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = RUNTIME_ROOT.parents[3]
CURVE_REFERENCE_ROOT = Path(os.environ.get("CURVE_REFERENCE_ROOT", REPOSITORY.parent / "curve")).resolve()


def install():
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            SECRET_KEY="synthetic-host-tests-only",
            USE_TZ=True,
            INSTALLED_APPS=[],
            REST_FRAMEWORK={"UNAUTHENTICATED_USER": None},
        )
    import django

    django.setup()
    sys.path.insert(0, str(RUNTIME_ROOT))
