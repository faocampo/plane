# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.curve.models import Product


def human_actor(user_id) -> dict[str, str]:
    return {"actor_type": "HUMAN", "actor_id": str(user_id)}


def serialize_product(product: Product) -> dict:
    return {
        "schema_version": product.schema_version,
        "id": str(product.id),
        "workspace_id": str(product.workspace_id),
        "key": product.key,
        "name": product.name,
        "description": product.description,
        "timezone": product.timezone,
        "state": product.state,
        "owner": human_actor(product.owner_user_id),
        "version": product.version,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
        "created_by": product.created_by,
        "updated_by": product.updated_by,
        "archived_at": product.archived_at.isoformat() if product.archived_at is not None else None,
        "archived_by": product.archived_by,
    }


def product_etag(product: Product) -> str:
    return f'"curve-product:{product.id}:v{product.version}"'
