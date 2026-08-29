# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from plane.curve.models import ImmutableRecordError, Product, ProductState
from plane.curve.product_guards import ProductArchived, assert_product_accepts_new_initiative


pytestmark = [pytest.mark.unit, pytest.mark.django_db(transaction=True)]
ACTOR = {"actor_type": "HUMAN", "actor_id": "00000000-0000-4000-8000-000000000001"}


def _product(*, workspace_id=None, key="mobile-platform", state=ProductState.ACTIVE, **overrides):
    values = {
        "workspace_id": workspace_id or uuid.uuid4(),
        "key": key,
        "name": "Mobile Platform",
        "description": None,
        "timezone": "UTC",
        "state": state,
        "owner_user_id": uuid.UUID(ACTOR["actor_id"]),
        "created_by": ACTOR,
        "updated_by": ACTOR,
    }
    values.update(overrides)
    return Product.objects.create(**values)


def _assert_integrity_error(callback):
    with pytest.raises(IntegrityError), transaction.atomic():
        callback()


def test_database_enforces_workspace_key_uniqueness_and_key_format():
    workspace_id = uuid.uuid4()
    _product(workspace_id=workspace_id)

    _assert_integrity_error(lambda: _product(workspace_id=workspace_id))
    _assert_integrity_error(lambda: _product(workspace_id=uuid.uuid4(), key="Invalid_Key"))

    assert _product(workspace_id=uuid.uuid4()).key == "mobile-platform"


def test_database_enforces_state_dependent_archival_fields():
    _assert_integrity_error(lambda: _product(state=ProductState.ARCHIVED))
    _assert_integrity_error(
        lambda: _product(
            state=ProductState.ACTIVE,
            archived_at=timezone.now(),
            archived_by=ACTOR,
        )
    )


def test_product_key_workspace_and_bulk_command_paths_are_immutable():
    product = _product()
    product.key = "changed"
    with pytest.raises(ImmutableRecordError):
        product.save()
    with pytest.raises(ImmutableRecordError):
        Product.objects.filter(id=product.id).update(name="Bypassed")
    with pytest.raises(ImmutableRecordError):
        Product.objects.bulk_update([product], ["name"])
    with pytest.raises(ImmutableRecordError):
        Product.objects.bulk_create([])


def test_initiative_acceptance_guard_locks_active_product_and_rejects_archived_product():
    active = _product()
    archived = _product(
        key="archived-product",
        state=ProductState.ARCHIVED,
        archived_at=timezone.now(),
        archived_by=ACTOR,
    )

    with transaction.atomic():
        assert (
            assert_product_accepts_new_initiative(
                workspace_id=active.workspace_id,
                product_id=active.id,
            ).id
            == active.id
        )
    with pytest.raises(ProductArchived), transaction.atomic():
        assert_product_accepts_new_initiative(
            workspace_id=archived.workspace_id,
            product_id=archived.id,
        )
