# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from collections.abc import Callable, Iterable
from contextlib import contextmanager

from plane.curve.models import Initiative, Product, ProductState


TERMINAL_INITIATIVE_STATES = frozenset({"READY_FOR_REPOSITORY_REVIEW", "CANCELLED"})


class ProductInitiativeGuardUnavailable(RuntimeError):
    code = "PRODUCT_INITIATIVE_GUARD_UNAVAILABLE"


class ProductHasNonTerminalInitiative(RuntimeError):
    code = "PRODUCT_HAS_NON_TERMINAL_INITIATIVE"


class ProductArchived(RuntimeError):
    code = "PRODUCT_ARCHIVED"


class ProductGuardResourceNotFound(LookupError):
    code = "PRODUCT_NOT_FOUND"


def _database_initiative_guard(*, workspace_id, product_id) -> tuple[str, ...]:
    return tuple(
        Initiative.objects.for_workspace(workspace_id).filter(product_id=product_id).values_list("state", flat=True)
    )


_initiative_state_guard: Callable[..., Iterable[str]] | None = _database_initiative_guard


@contextmanager
def override_product_initiative_guard(guard):
    global _initiative_state_guard
    previous = _initiative_state_guard
    _initiative_state_guard = guard
    try:
        yield
    finally:
        _initiative_state_guard = previous


def list_product_initiative_states(*, workspace_id, product_id) -> tuple[str, ...]:
    if _initiative_state_guard is None:
        raise ProductInitiativeGuardUnavailable
    try:
        states = tuple(_initiative_state_guard(workspace_id=workspace_id, product_id=product_id))
    except ProductInitiativeGuardUnavailable:
        raise
    except Exception as error:
        raise ProductInitiativeGuardUnavailable from error
    if any(not isinstance(state, str) or not state for state in states):
        raise ProductInitiativeGuardUnavailable
    return states


def assert_product_can_archive(*, workspace_id, product_id) -> None:
    states = list_product_initiative_states(workspace_id=workspace_id, product_id=product_id)
    if any(state not in TERMINAL_INITIATIVE_STATES for state in states):
        raise ProductHasNonTerminalInitiative


def assert_product_accepts_new_initiative(*, workspace_id, product_id) -> Product:
    product = Product.objects.find_by_id(
        workspace_id=workspace_id,
        record_id=product_id,
        for_update=True,
    )
    if product is None:
        raise ProductGuardResourceNotFound
    if product.state != ProductState.ACTIVE:
        raise ProductArchived
    return product
