# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Fail closed until a real binding repository and its concurrency fence exist."""


class AssociationBindingGuardUnavailable(RuntimeError):
    code = "PROJECT_ASSOCIATION_BINDING_GUARD_UNAVAILABLE"


class AssociationHasActiveBindings(RuntimeError):
    code = "PROJECT_ASSOCIATION_HAS_ACTIVE_BINDINGS"


def assert_association_can_end(*, workspace_id, association_id):
    # The absence of a WorkItemBinding implementation is NOT evidence of no
    # dependencies. A future implementation must lock/fence binding creation
    # and reconciliation in this same transaction. No settings/caller hook.
    raise AssociationBindingGuardUnavailable
