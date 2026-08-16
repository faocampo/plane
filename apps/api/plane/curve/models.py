# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

from django.db import models


class WorkspaceScopedModel(models.Model):
    """Abstract base for mutable Curve aggregate roots.

    Plane remains authoritative for workspace identity and membership. Curve
    stores the Plane workspace UUID as an opaque scope value without a hard
    foreign key, which keeps Curve lifecycle and migrations additive.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace_id = models.UUIDField(db_index=True, editable=False)
    aggregate_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    created_by = models.JSONField(editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)
    updated_by = models.JSONField(editable=False)
    tombstoned_at = models.DateTimeField(null=True, blank=True, editable=False)
    tombstoned_by = models.JSONField(null=True, blank=True, editable=False)
    tombstone_reason = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        abstract = True
