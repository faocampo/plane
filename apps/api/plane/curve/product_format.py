# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Application-owned supported Product format boundary."""


class ProductFormatUnavailable(RuntimeError):
    code = "CURVE_PRODUCT_FORMAT_UNAVAILABLE"


def require_supported_product_format(product) -> None:
    if type(product.schema_version) is not str or product.schema_version != "1.0":
        raise ProductFormatUnavailable
