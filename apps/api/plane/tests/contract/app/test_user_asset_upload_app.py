# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract coverage for the two-step user-avatar upload boundary."""

from unittest import mock

import pytest
from rest_framework import status

from plane.db.models import FileAsset

S3_STORAGE_PATH = "plane.app.views.asset.v2.S3Storage"
METADATA_TASK_PATH = "plane.app.views.asset.v2.get_asset_object_metadata.delay"


@pytest.mark.contract
@pytest.mark.django_db
def test_user_avatar_asset_is_signed_then_committed(session_client, create_user):
    with mock.patch(S3_STORAGE_PATH) as storage:
        storage.return_value.generate_presigned_post.return_value = {
            "url": "http://test-minio:9000/uploads",
            "fields": {"key": "signed-avatar.png"},
        }
        create_response = session_client.post(
            "/api/assets/v2/user-assets/",
            {
                "name": "avatar.png",
                "type": "image/png",
                "size": 6,
                "entity_identifier": "",
                "entity_type": FileAsset.EntityTypeContext.USER_AVATAR,
            },
            format="json",
        )

    assert create_response.status_code == status.HTTP_200_OK
    assert create_response.data["upload_data"] == {
        "url": "http://test-minio:9000/uploads",
        "fields": {"key": "signed-avatar.png"},
    }
    asset = FileAsset.objects.get(id=create_response.data["asset_id"])
    assert asset.user_id == create_user.id
    assert asset.entity_type == FileAsset.EntityTypeContext.USER_AVATAR
    assert asset.is_uploaded is False

    with mock.patch(METADATA_TASK_PATH) as metadata_task:
        commit_response = session_client.patch(
            f"/api/assets/v2/user-assets/{asset.id}/",
            {},
            format="json",
        )

    assert commit_response.status_code == status.HTTP_204_NO_CONTENT
    asset.refresh_from_db()
    create_user.refresh_from_db()
    assert asset.is_uploaded is True
    assert create_user.avatar_asset_id == asset.id
    metadata_task.assert_called_once_with(asset_id=str(asset.id))


@pytest.mark.contract
@pytest.mark.django_db
def test_user_avatar_asset_rejects_an_unsupported_file_type(session_client):
    response = session_client.post(
        "/api/assets/v2/user-assets/",
        {
            "name": "avatar.svg",
            "type": "image/svg+xml",
            "size": 6,
            "entity_identifier": "",
            "entity_type": FileAsset.EntityTypeContext.USER_AVATAR,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "error": "Invalid file type. Only JPEG, PNG, WebP, JPG and GIF files are allowed.",
        "status": False,
    }
