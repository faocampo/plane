# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Bounded Google Docs response normalization inside the trusted capture runtime.

The caller owns current authorization, full-response transport and safe image
retrieval. This module performs no network, persistence or authorization lookup.
"""

import hashlib
import json
import math
from dataclasses import dataclass


NORMALIZATION_VERSION = "curve.google-docs.normalized/v1-candidate"
STRUCTURAL_TYPES = {"paragraph", "table", "sectionBreak", "tableOfContents"}
PARAGRAPH_TYPES = {"textRun", "inlineObjectElement", "footnoteReference", "pageBreak", "columnBreak", "horizontalRule"}
LEGACY_FIELDS = {
    "body",
    "headers",
    "footers",
    "footnotes",
    "documentStyle",
    "suggestedDocumentStyleChanges",
    "namedStyles",
    "suggestedNamedStylesChanges",
    "lists",
    "namedRanges",
    "inlineObjects",
    "positionedObjects",
}


class GoogleDocumentCaptureError(ValueError):
    """A fixed, content-free rejection code, safe for boundary normalization."""


@dataclass(frozen=True, repr=False)
class AuthorizedImageCapture:
    # Construct only after current scoped permission and safe bounded retrieval.
    data: bytes
    authorized: bool


@dataclass(frozen=True, repr=False)
class NormalizedGoogleDocument:
    # Protected content: never serialize this object into logs or workflow input.
    content: dict
    revision_id: str | None


def _require(condition, code):
    if not condition:
        raise GoogleDocumentCaptureError(code)


def _object(value, code):
    _require(type(value) is dict, code)
    return value


def _array(value, code):
    _require(type(value) is list, code)
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "INVALID_DOCUMENT_JSON")
        result[key] = value
    return result


def normalize_google_document(
    *,
    response_bytes,
    expected_document_id,
    read_options,
    image_captures,
    max_document_bytes,
    max_image_bytes,
):
    """Normalize an unmasked all-tab response after trusted transport checks.

    Byte limits are mandatory runtime inputs. The image budget applies to the
    combined distinct referenced captures. Unknown metadata is preserved.
    Content remains protected; complete means supported structural capture only.
    """
    _require(type(max_document_bytes) is int and max_document_bytes > 0, "CAPTURE_LIMIT_REQUIRED")
    _require(type(max_image_bytes) is int and max_image_bytes > 0, "CAPTURE_LIMIT_REQUIRED")
    _require(type(response_bytes) is bytes and 0 < len(response_bytes) <= max_document_bytes, "DOCUMENT_LIMIT_EXCEEDED")
    _require(type(expected_document_id) is str and bool(expected_document_id), "INVALID_DOCUMENT")
    _require(
        type(read_options) is dict and read_options.get("includeTabsContent") is True and "fields" not in read_options,
        "FULL_DOCUMENT_READ_REQUIRED",
    )
    _require(read_options.get("suggestionsViewMode") == "SUGGESTIONS_INLINE", "INLINE_SUGGESTIONS_REQUIRED")
    _require(type(image_captures) is dict, "IMAGE_CAPTURE_REQUIRED")
    try:
        document = json.loads(response_bytes.decode("utf-8"), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise GoogleDocumentCaptureError("INVALID_DOCUMENT_JSON") from None
    _object(document, "INVALID_DOCUMENT")
    _require(
        document.get("documentId") == expected_document_id and type(document.get("title")) is str, "INVALID_DOCUMENT"
    )
    _require(document.get("suggestionsViewMode") == "SUGGESTIONS_INLINE", "INLINE_SUGGESTIONS_REQUIRED")
    _require(type(document.get("tabs")) is list and bool(document["tabs"]), "MISSING_TABS")
    revision = document.get("revisionId")
    _require(revision is None or type(revision) is str and bool(revision.strip()), "INVALID_REVISION_ID")
    nodes, image_bytes = 0, 0
    captured_images = {}

    def copy(value, depth=0, in_image=False):
        nonlocal nodes, image_bytes
        nodes += 1
        _require(nodes <= 100000 and depth <= 100, "DOCUMENT_LIMIT_EXCEEDED")
        if value is None or type(value) is bool:
            return value
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise GoogleDocumentCaptureError("INVALID_DOCUMENT_JSON") from None
            return value
        if type(value) in {int, float}:
            try:
                valid = math.isfinite(value)
            except OverflowError:
                valid = False
            _require(valid and (type(value) is not int or abs(value) <= 9007199254740991), "INVALID_DOCUMENT_JSON")
            return value
        if type(value) is list:
            return [copy(item, depth + 1) for item in value]
        _object(value, "INVALID_DOCUMENT_JSON")
        _require("embeddedDrawingProperties" not in value, "UNSUPPORTED_EMBEDDED_DRAWING")
        _require("linkedContentReference" not in value, "UNSUPPORTED_LINKED_CONTENT")
        _require(not in_image or "capturedImage" not in value, "UNEXPECTED_CAPTURE_FIELD")
        result = {}
        for key, child in value.items():
            copy(key, depth + 1)
            if key == "contentUri":
                _require(in_image and type(child) is str, "UNEXPECTED_CONTENT_URI")
                if child not in captured_images:
                    capture = image_captures.get(child)
                    _require(
                        type(capture) is AuthorizedImageCapture
                        and capture.authorized is True
                        and type(capture.data) is bytes
                        and len(capture.data) > 0,
                        "IMAGE_CAPTURE_REQUIRED",
                    )
                    image_bytes += len(capture.data)
                    _require(image_bytes <= max_image_bytes, "IMAGE_LIMIT_EXCEEDED")
                    captured_images[child] = {
                        "digest": "sha256:" + hashlib.sha256(capture.data).hexdigest(),
                        "byteLength": len(capture.data),
                    }
                result["capturedImage"] = dict(captured_images[child])
                continue
            if key == "imageProperties":
                _require(
                    type(child) is dict and type(child.get("contentUri")) is str and bool(child["contentUri"]),
                    "IMAGE_CAPTURE_REQUIRED",
                )
            if key == "embeddedObject":
                _require(type(child) is dict and "imageProperties" in child, "UNSUPPORTED_EMBEDDED_OBJECT")
            result[key] = copy(child, depth + 1, key == "imageProperties")
        return result

    captured = copy(document)
    tab_ids = set()

    def union(node, types, code):
        _object(node, code)
        kinds = types.intersection(node)
        _require(len(kinds) == 1 and set(node) <= types | {"startIndex", "endIndex"}, code)
        kind = next(iter(kinds))
        return kind, _object(node[kind], code)

    def reference(tab, kind, identifier, code):
        records = _object(tab.get(kind, {}), code)
        _require(type(identifier) is str and identifier in records, code)
        record = _object(records[identifier], code)
        if kind in {"inlineObjects", "positionedObjects"}:
            properties = _object(
                record.get("inlineObjectProperties" if kind == "inlineObjects" else "positionedObjectProperties"), code
            )
            embedded = _object(properties.get("embeddedObject"), code)
            _object(embedded.get("imageProperties"), code)
        elif kind == "lists":
            _object(record.get("listProperties"), code)

    def content(elements, tab, depth=0):
        _require(depth <= 50, "INVALID_STRUCTURAL_CONTENT")
        for element in _array(elements, "INVALID_STRUCTURAL_CONTENT"):
            kind, value = union(element, STRUCTURAL_TYPES, "UNSUPPORTED_STRUCTURAL_ELEMENT")
            if kind == "paragraph":
                if "bullet" in value:
                    bullet = _object(value["bullet"], "MISSING_LIST")
                    reference(tab, "lists", bullet.get("listId"), "MISSING_LIST")
                for identifier in _array(value.get("positionedObjectIds", []), "MISSING_POSITIONED_OBJECT"):
                    reference(tab, "positionedObjects", identifier, "MISSING_POSITIONED_OBJECT")
                for item in _array(value.get("elements"), "MISSING_PARAGRAPH_ELEMENTS"):
                    item_kind, item_value = union(item, PARAGRAPH_TYPES, "UNSUPPORTED_PARAGRAPH_ELEMENT")
                    if item_kind == "textRun":
                        _require(type(item_value.get("content")) is str, "MISSING_TEXT_CONTENT")
                    elif item_kind == "inlineObjectElement":
                        reference(tab, "inlineObjects", item_value.get("inlineObjectId"), "MISSING_INLINE_OBJECT")
                    elif item_kind == "footnoteReference":
                        reference(tab, "footnotes", item_value.get("footnoteId"), "MISSING_FOOTNOTE")
            elif kind == "table":
                for row in _array(value.get("tableRows"), "MISSING_TABLE_ROWS"):
                    _object(row, "MISSING_TABLE_CELLS")
                    for cell in _array(row.get("tableCells"), "MISSING_TABLE_CELLS"):
                        _object(cell, "INVALID_STRUCTURAL_CONTENT")
                        content(cell.get("content"), tab, depth + 1)
            elif kind == "tableOfContents":
                content(value.get("content"), tab, depth + 1)

    def check_tab(tab, parent=None, depth=0):
        _require(depth <= 50, "DOCUMENT_LIMIT_EXCEEDED")
        _object(tab, "UNSUPPORTED_TAB")
        _require(set(tab) <= {"tabProperties", "documentTab", "childTabs"}, "UNSUPPORTED_TAB")
        properties = _object(tab.get("tabProperties"), "INVALID_TAB_ID")
        identifier = properties.get("tabId")
        _require(type(identifier) is str and bool(identifier) and identifier not in tab_ids, "INVALID_TAB_ID")
        _require(properties.get("parentTabId") == parent, "INVALID_TAB_HIERARCHY")
        tab_ids.add(identifier)
        body = _object(tab.get("documentTab"), "MISSING_TAB_BODY")
        segment = _object(body.get("body"), "MISSING_TAB_BODY")
        content(segment.get("content"), body)
        for kind in ("headers", "footers", "footnotes"):
            for segment in _object(body.get(kind, {}), "INVALID_STRUCTURAL_CONTENT").values():
                _object(segment, "INVALID_STRUCTURAL_CONTENT")
                content(segment.get("content"), body)
        for child in _array(tab.get("childTabs", []), "INVALID_TAB_HIERARCHY"):
            check_tab(child, identifier, depth + 1)

    for tab in captured["tabs"]:
        check_tab(tab)
    for field in LEGACY_FIELDS.intersection(captured):
        _require(type(captured[field]) is dict and not captured[field], "LEGACY_CONTENT_WITH_TABS")
        del captured[field]
    captured.pop("revisionId", None)
    tabs = captured.pop("tabs")
    return NormalizedGoogleDocument(
        content={
            "normalization_version": NORMALIZATION_VERSION,
            "complete": True,
            "unsupported_nodes": 0,
            "document_properties": captured,
            "tabs": tabs,
        },
        revision_id=revision,
    )
