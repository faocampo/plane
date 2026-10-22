# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Authenticated local PRD upload and protected content; default-off LOCAL only."""

from io import BytesIO
import re

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.parsers import BaseParser

from .local_document_authority import require_local_document_authority
from .local_document_capture import read_local_document_snapshot
from .local_document_models import LocalPrdSource
from .local_document_services import upload_local_document
from .local_document_store import LocalDocumentStore, LocalDocumentUnavailable, StoredDocument
from .prd_commands import PrdCommandError
from .prd_views import CurvePrdCommandEndpoint

_TYPES = {"application/pdf": "prd.pdf", "text/plain": "prd.txt", "text/markdown": "prd.md"}


def _version(value, *, etag=False):
    pattern = r'"([1-9][0-9]{0,15})"' if etag else r"(0|[1-9][0-9]{0,15})"
    match = re.fullmatch(pattern, value or "")
    if match is None or int(match[1]) > 9007199254740991:
        raise PrdCommandError("LOCAL_PRD_VERSION_REQUIRED", 428)
    return int(match[1])


def _store():
    root = getattr(settings, "CURVE_LOCAL_PRD_STORAGE_ROOT", None)
    if type(root) is not str or not root:
        raise PrdCommandError("LOCAL_PRD_STORAGE_UNAVAILABLE", 503)
    return LocalDocumentStore(root)


def _authority(request, slug, initiative_id, action="READ", expected_version=None):
    return require_local_document_authority(
        request=request,
        workspace_slug=slug,
        initiative_id=initiative_id,
        action=action,
        expected_version=expected_version,
    )


class LocalPrdEndpoint(CurvePrdCommandEndpoint):
    def handle_exception(self, error):
        if isinstance(error, LocalDocumentUnavailable):
            error = PrdCommandError("LOCAL_PRD_DOCUMENT_UNAVAILABLE", 422 if self.request.method == "POST" else 404)
        return super().handle_exception(error)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        return response


class UnparsedDocumentUploadParser(BaseParser):
    """Expose no form fields; the endpoint validates the bounded raw bytes.

    SessionAuthentication still checks the CSRF header. Its request.POST lookup
    must not dispatch raw PDF/text bytes through the default JSON/form parsers.
    """

    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None):
        return {}


class CurveLocalPrdUploadEndpoint(LocalPrdEndpoint):
    parser_classes = [UnparsedDocumentUploadParser]
    http_method_names = ["post", "options"]

    def post(self, request, slug, initiative_id):
        media = request.content_type.split(";", 1)[0].strip().lower()
        if media not in _TYPES:
            raise PrdCommandError("UNSUPPORTED_MEDIA_TYPE", 415)
        version = _version(request.headers.get("If-Match"), etag=True)
        source_version = _version(request.headers.get("X-Curve-Source-Version"))
        with transaction.atomic():
            _authority(request, slug, initiative_id, "UPLOAD", version)
        with _store() as store:
            result = upload_local_document(
                request=request,
                workspace_slug=slug,
                initiative_id=initiative_id,
                expected_version=version,
                expected_source_version=source_version,
                raw_idempotency_key=request.headers.get("Idempotency-Key"),
                filename=_TYPES[media],
                stream=BytesIO(request.body),
                store=store,
            )
        response = Response(result.data, status=200 if result.replayed else 201)
        response["Location"] = reverse(
            "curve-local-prd-source-v1",
            kwargs=dict(slug=slug, initiative_id=initiative_id, source_id=result.data["id"]),
        )
        response["ETag"] = f'"{result.initiative_version}"'
        response["Idempotency-Replayed"] = "true" if result.replayed else "false"
        return response


class CurveLocalPrdSourceEndpoint(LocalPrdEndpoint):
    http_method_names = ["get", "head", "options"]
    content = False

    def get(self, request, slug, initiative_id, source_id=None):
        with transaction.atomic():
            before = _authority(request, slug, initiative_id)
            source = (
                before.current_source
                if source_id is None
                else LocalPrdSource.objects.filter(
                    workspace_id=before.context.workspace.id, initiative_id=initiative_id, id=source_id
                ).first()
            )
            if source_id is not None and source is None:
                raise PrdCommandError("LOCAL_PRD_UNAVAILABLE", 404)
            if source is not None:
                source.validate_metadata()
            metadata = source.as_record() if source else None
            if not self.content:
                response = Response(
                    metadata
                    if source_id
                    else dict(
                        schema_version="curve.local-prd-current/v1-candidate",
                        source=metadata,
                        initiative_version=before.context.initiative.version,
                        upload_available=before.context.actor_id == before.context.initiative.creator_user_id
                        and before.context.initiative.state in {"DRAFT", "ALIGNING"}
                        and bool(getattr(settings, "CURVE_LOCAL_PRD_STORAGE_ROOT", None)),
                    )
                )
                response["ETag"] = f'"{before.context.initiative.version}"'
                return response
        # Read protected bytes only after current native authorization, outside
        # locks; then repeat authorization and compare the complete native fence.
        ref = metadata["snapshot"]
        snapshot = StoredDocument(
            metadata["workspace_id"], ref["object_id"], ref["digest"], ref["size_bytes"], ref["media_type"]
        )
        with _store() as store:
            captured = read_local_document_snapshot(
                store=store, workspace_id=metadata["workspace_id"], reference=snapshot
            )
            body = store.read(workspace_id=metadata["workspace_id"], reference=captured.source)
        with transaction.atomic():
            after = _authority(request, slug, initiative_id)
            if after.fence != before.fence:
                raise PrdCommandError("LOCAL_PRD_SOURCE_CHANGED", 409)
        media = captured.source.media_type
        response = HttpResponse(
            body, content_type="application/pdf" if media == "application/pdf" else "text/plain; charset=utf-8"
        )
        response["Content-Disposition"] = f'inline; filename="{_TYPES[media]}"'
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        response["ETag"] = f'"{captured.source.content_digest}"'
        return response
