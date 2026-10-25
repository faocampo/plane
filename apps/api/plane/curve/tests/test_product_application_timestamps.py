# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.
"""Application clock semantics preserve aggregate ordering and no-effect history."""

from datetime import datetime, timedelta

from plane.curve.models import Product
from plane.curve import product_services
from plane.curve.tests.test_product_api import _add_member, _client, _product_url
from plane.curve.tests import test_product_format_api as format_helpers
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]

product_context = format_helpers.product_context
settings_profile = format_helpers.settings_profile
authoritative_snapshot = format_helpers.authoritative_snapshot


def test_creation_representation_uses_supported_edition_and_aware_utc(product_context):
    _, _, client, product_id = product_context
    data = client.get(_product_url(product_id)).json()
    assert data["schema_version"] == "1.0"
    assert data["version"] == 1
    for field in ("created_at", "updated_at"):
        value = datetime.fromisoformat(data[field])
        assert value.utcoffset() == timedelta(0)


def test_all_product_mutations_preserve_creation_time_and_edition(product_context, monkeypatch):
    workspace, _, client, product_id = product_context
    next_owner = _add_member(workspace, email="timestamp-next-owner@example.invalid")
    original = Product.objects.get(id=product_id)
    actions = [
        ("", {"name": "Updated"}, client.patch),
        ("owner/", {"owner_user_id": str(next_owner.id)}, client.post),
        ("archive/", {}, client.post),
        ("restore/", {}, client.post),
    ]
    for index, (suffix, payload, call) in enumerate(actions, start=1):
        instant = original.updated_at + timedelta(minutes=index)
        monkeypatch.setattr("django.utils.timezone.now", lambda instant=instant: instant)
        result = call(
            _product_url(product_id, suffix),
            payload,
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v{index}"',
            HTTP_IDEMPOTENCY_KEY=f"timestamp-change-{index}",
        )
        assert result.status_code == 200
        current = Product.objects.get(id=product_id)
        assert current.created_at == original.created_at
        assert current.updated_at == instant
        assert current.schema_version == original.schema_version == "1.0"
        assert current.version == index + 1


@pytest.mark.parametrize("action", ["unchanged", "stale", "denied", "replay"])
def test_no_effect_commands_preserve_timestamps_and_history(product_context, action):
    workspace, _, client, product_id = product_context
    original_headers = {
        "HTTP_IF_MATCH": f'"curve-product:{product_id}:v1"',
        "HTTP_IDEMPOTENCY_KEY": "timestamp-original-change",
    }
    assert (
        client.patch(_product_url(product_id), {"name": "Updated"}, format="json", **original_headers).status_code
        == 200
    )
    before = authoritative_snapshot(product_id)
    if action == "replay":
        result = client.patch(_product_url(product_id), {"name": "Updated"}, format="json", **original_headers)
        assert result.status_code == 200
    else:
        if action == "denied":
            member = _add_member(workspace, email="timestamp-non-owner@example.invalid")
            client = _client(member)
        result = client.patch(
            _product_url(product_id),
            {"name": "Updated" if action == "unchanged" else "Different"},
            format="json",
            HTTP_IF_MATCH=f'"curve-product:{product_id}:v{1 if action == "stale" else 2}"',
            HTTP_IDEMPOTENCY_KEY="timestamp-no-effect-" + action,
        )
        assert result.status_code == {"unchanged": 422, "stale": 412, "denied": 403}[action]
    assert authoritative_snapshot(product_id) == before


def test_failure_after_event_and_outbox_append_rolls_back_product_timestamps(product_context, monkeypatch):
    _, _, client, product_id = product_context
    before = authoritative_snapshot(product_id)
    append = product_services._append_product_event

    def fail_after_append(**kwargs):
        append(**kwargs)
        raise RuntimeError("synthetic failure after event and outbox")

    monkeypatch.setattr(product_services, "_append_product_event", fail_after_append)
    response = client.patch(
        _product_url(product_id),
        {"name": "Uncommitted"},
        format="json",
        HTTP_IF_MATCH=f'"curve-product:{product_id}:v1"',
        HTTP_IDEMPOTENCY_KEY="timestamp-rollback",
    )
    assert response.status_code == 500
    assert authoritative_snapshot(product_id) == before
