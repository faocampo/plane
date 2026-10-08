# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import json
from copy import deepcopy

import pytest

from plane.curve.providers.google_docs_normalization import (
    AuthorizedImageCapture,
    GoogleDocumentCaptureError,
    normalize_google_document,
)

pytestmark = pytest.mark.unit


def paragraph(text):
    return {"paragraph": {"elements": [{"textRun": {"content": text}}]}}


@pytest.fixture
def document():
    return {
        "documentId": "synthetic-doc",
        "title": "Synthetic PRD",
        "revisionId": "synthetic-revision",
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
        "tabs": [
            {
                "tabProperties": {"tabId": "main", "title": "Problem", "index": 0},
                "documentTab": {
                    "body": {
                        "content": [
                            paragraph("Synthetic problem\n"),
                            {
                                "table": {
                                    "tableRows": [{"tableCells": [{"content": [paragraph("Synthetic acceptance\n")]}]}]
                                },
                            },
                            {"paragraph": {"elements": [{"footnoteReference": {"footnoteId": "fn"}}]}},
                        ]
                    },
                    "headers": {"h": {"content": [paragraph("Synthetic header")]}},
                    "footers": {"f": {"content": [paragraph("Synthetic footer")]}},
                    "footnotes": {"fn": {"content": [paragraph("Synthetic evidence")]}},
                },
                "childTabs": [
                    {
                        "tabProperties": {"tabId": "child", "parentTabId": "main", "title": "Acceptance"},
                        "documentTab": {
                            "body": {
                                "content": [
                                    {
                                        "paragraph": {
                                            "elements": [
                                                {
                                                    "textRun": {
                                                        "content": "Synthetic suggestion",
                                                        "suggestedInsertionIds": ["s1"],
                                                        "textStyle": {"bold": True},
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        },
                    }
                ],
            }
        ],
    }


def normalize(document, **kwargs):
    args = dict(
        response_bytes=json.dumps(document).encode(),
        expected_document_id="synthetic-doc",
        read_options={"includeTabsContent": True, "suggestionsViewMode": "SUGGESTIONS_INLINE"},
        image_captures={},
        max_document_bytes=1000000,
        max_image_bytes=10000,
    )
    args.update(kwargs)
    return normalize_google_document(**args)


def test_supported_content_is_preserved_and_detached(document):
    before = deepcopy(document)
    result = normalize(document)
    assert result.content == {
        "normalization_version": "curve.google-docs.normalized/v1-candidate",
        "complete": True,
        "unsupported_nodes": 0,
        "tabs": document["tabs"],
        "document_properties": {k: v for k, v in document.items() if k not in {"tabs", "revisionId"}},
    }
    assert result.revision_id == "synthetic-revision"
    result.content["tabs"][0]["documentTab"]["body"]["content"].clear()
    assert document == before and "Synthetic PRD" not in repr(result)


def test_revision_changes_are_separate_and_unknown_metadata_is_retained(document):
    first = normalize(document)
    document["revisionId"] = "synthetic-next"
    assert normalize(document).content == first.content
    document["tabs"][0]["documentTab"]["unknownMetadata"] = {"semantic": "synthetic-new"}
    assert normalize(document).content != first.content


def put(root, path, value):
    for part in path[:-1]:
        root = root[part]
    root[path[-1]] = value


TAB = ("tabs", 0)
BODY = (*TAB, "documentTab", "body", "content")


@pytest.mark.parametrize(
    "path,value,code",
    [
        (("documentId",), "synthetic-other", "INVALID_DOCUMENT"),
        (("title",), None, "INVALID_DOCUMENT"),
        (("tabs",), [], "MISSING_TABS"),
        (("suggestionsViewMode",), "PREVIEW_SUGGESTIONS_ACCEPTED", "INLINE_SUGGESTIONS_REQUIRED"),
        ((*TAB, "canvasTab"), {}, "UNSUPPORTED_TAB"),
        ((*TAB, "childTabs"), {}, "INVALID_TAB_HIERARCHY"),
        ((*TAB, "childTabs", 0, "tabProperties", "tabId"), "main", "INVALID_TAB_ID"),
        ((*TAB, "childTabs", 0, "tabProperties", "parentTabId"), "other", "INVALID_TAB_HIERARCHY"),
        ((*TAB, "childTabs", 0, "documentTab"), None, "MISSING_TAB_BODY"),
        ((*BODY, 0), {"canvas": {}}, "UNSUPPORTED_STRUCTURAL_ELEMENT"),
        ((*BODY, 0), {"paragraph": None}, "UNSUPPORTED_STRUCTURAL_ELEMENT"),
        ((*BODY, 0), {"paragraph": {}, "table": {}}, "UNSUPPORTED_STRUCTURAL_ELEMENT"),
        ((*BODY, 0, "paragraph", "elements"), [{"equation": {}}], "UNSUPPORTED_PARAGRAPH_ELEMENT"),
        ((*BODY, 0, "paragraph", "elements"), [{"textRun": None}], "UNSUPPORTED_PARAGRAPH_ELEMENT"),
        ((*BODY, 0, "paragraph", "elements"), [{"textRun": {}}], "MISSING_TEXT_CONTENT"),
        (
            (*BODY, 0, "paragraph", "elements"),
            [{"inlineObjectElement": {"inlineObjectId": "absent"}}],
            "MISSING_INLINE_OBJECT",
        ),
        ((*BODY, 0, "paragraph", "bullet"), {"listId": "absent"}, "MISSING_LIST"),
        ((*BODY, 0, "paragraph", "positionedObjectIds"), ["absent"], "MISSING_POSITIONED_OBJECT"),
        ((*BODY, 1, "table", "tableRows"), None, "MISSING_TABLE_ROWS"),
        ((*BODY, 1, "table", "tableRows", 0, "tableCells"), None, "MISSING_TABLE_CELLS"),
        ((*BODY, 1, "table", "tableRows", 0, "tableCells", 0, "content"), None, "INVALID_STRUCTURAL_CONTENT"),
        ((*TAB, "documentTab", "footnotes"), {}, "MISSING_FOOTNOTE"),
        (("body",), {"content": []}, "LEGACY_CONTENT_WITH_TABS"),
        (("contentUri",), "https://example.invalid/synthetic-secret", "UNEXPECTED_CONTENT_URI"),
        (("metadata",), {"embeddedDrawingProperties": {}}, "UNSUPPORTED_EMBEDDED_DRAWING"),
        (("metadata",), {"linkedContentReference": {}}, "UNSUPPORTED_LINKED_CONTENT"),
        (("metadata",), {"embeddedObject": {}}, "UNSUPPORTED_EMBEDDED_OBJECT"),
        (("metadata",), float("nan"), "INVALID_DOCUMENT_JSON"),
        (("metadata",), float("inf"), "INVALID_DOCUMENT_JSON"),
        (("metadata",), "\ud800", "INVALID_DOCUMENT_JSON"),
    ],
)
def test_malformed_or_unsupported_capture_is_rejected(document, path, value, code):
    put(document, path, value)
    with pytest.raises(GoogleDocumentCaptureError, match=f"^{code}$"):
        normalize(document)


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"includeTabsContent": False},
        {"includeTabsContent": True, "fields": "tabs", "suggestionsViewMode": "SUGGESTIONS_INLINE"},
        {"includeTabsContent": True, "suggestionsViewMode": "PREVIEW_WITHOUT_SUGGESTIONS"},
    ],
)
def test_full_inline_read_is_mandatory(document, options):
    with pytest.raises(GoogleDocumentCaptureError):
        normalize(document, read_options=options)


@pytest.mark.parametrize("raw", [b"{}secret", b'{"title":"first","title":"second"}', b"\xff", b"null", b"[]"])
def test_raw_parse_errors_are_fixed_and_content_free(document, raw):
    with pytest.raises(GoogleDocumentCaptureError) as error:
        normalize(document, response_bytes=raw)
    assert str(error.value) in {"INVALID_DOCUMENT_JSON", "INVALID_DOCUMENT"}
    assert "secret" not in repr(error.value) and error.value.__cause__ is None


def image(document, uri="https://example.invalid/synthetic-temporary-a"):
    properties = {"contentUri": uri, "cropProperties": {"offsetLeft": 0.1}}
    document["tabs"][0]["documentTab"]["inlineObjects"] = {
        "image": {
            "inlineObjectProperties": {"embeddedObject": {"imageProperties": properties}},
        }
    }
    document["tabs"][0]["documentTab"]["body"]["content"].append(
        {
            "paragraph": {"elements": [{"inlineObjectElement": {"inlineObjectId": "image"}}]},
        }
    )
    return properties


def test_image_url_rotation_preserves_content_and_bytes_are_bound(document):
    properties = image(document)
    capture = AuthorizedImageCapture(b"synthetic-image", True)
    first = normalize(document, image_captures={properties["contentUri"]: capture})
    serialized = json.dumps(first.content)
    assert "synthetic-temporary" not in serialized
    assert hashlib.sha256(capture.data).hexdigest() in serialized
    properties["contentUri"] = "https://example.invalid/synthetic-temporary-b"
    assert normalize(document, image_captures={properties["contentUri"]: capture}).content == first.content
    changed = normalize(document, image_captures={properties["contentUri"]: AuthorizedImageCapture(b"changed", True)})
    assert changed.content != first.content and "synthetic-image" not in repr(capture)


@pytest.mark.parametrize(
    "capture",
    [
        None,
        {"authorized": True, "data": b"synthetic"},
        AuthorizedImageCapture(b"", True),
        AuthorizedImageCapture(b"synthetic", False),
    ],
)
def test_images_require_typed_authorized_nonempty_bytes(document, capture):
    properties = image(document)
    with pytest.raises(GoogleDocumentCaptureError, match="IMAGE_CAPTURE_REQUIRED"):
        normalize(document, image_captures={properties["contentUri"]: capture})


def test_image_limit_and_capture_field_spoof_are_rejected(document):
    properties = image(document)
    captures = {properties["contentUri"]: AuthorizedImageCapture(b"1234", True)}
    with pytest.raises(GoogleDocumentCaptureError, match="IMAGE_LIMIT_EXCEEDED"):
        normalize(document, image_captures=captures, max_image_bytes=3)
    properties["capturedImage"] = {"digest": "synthetic-spoof"}
    with pytest.raises(GoogleDocumentCaptureError, match="UNEXPECTED_CAPTURE_FIELD"):
        normalize(document, image_captures=captures)


def test_document_byte_depth_and_node_limits(document):
    with pytest.raises(GoogleDocumentCaptureError, match="DOCUMENT_LIMIT_EXCEEDED"):
        normalize(document, max_document_bytes=1)
    for i in range(110):
        document = {"nested": document} if i else document
    # A valid root with deeply nested unknown metadata must also be bounded.
    root = {
        "documentId": "synthetic-doc",
        "title": "Synthetic",
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
        "tabs": [{"tabProperties": {"tabId": "main"}, "documentTab": {"body": {"content": []}}}],
        "metadata": document,
    }
    with pytest.raises(GoogleDocumentCaptureError, match="DOCUMENT_LIMIT_EXCEEDED"):
        normalize(root)
    root["metadata"] = [None] * 100001
    with pytest.raises(GoogleDocumentCaptureError, match="DOCUMENT_LIMIT_EXCEEDED"):
        normalize(root)


def test_empty_legacy_maps_and_missing_revision_are_supported(document):
    document["body"] = {}
    del document["revisionId"]
    result = normalize(document)
    assert "body" not in result.content["document_properties"] and result.revision_id is None


@pytest.mark.parametrize("record", [None, {}, {"inlineObjectProperties": {}}])
def test_referenced_empty_image_objects_cannot_claim_complete_capture(document, record):
    image(document)
    document["tabs"][0]["documentTab"]["inlineObjects"]["image"] = record
    with pytest.raises(GoogleDocumentCaptureError, match="MISSING_INLINE_OBJECT"):
        normalize(document)


def test_resolved_lists_and_positioned_images_are_retained(document):
    tab = document["tabs"][0]["documentTab"]
    tab["lists"] = {"list": {"listProperties": {"nestingLevels": [{"glyphType": "DECIMAL"}]}}}
    tab["body"]["content"][0]["paragraph"]["bullet"] = {"listId": "list"}
    tab["body"]["content"][0]["paragraph"]["positionedObjectIds"] = ["positioned"]
    uri = "https://example.invalid/synthetic-positioned"
    tab["positionedObjects"] = {
        "positioned": {
            "positionedObjectProperties": {
                "embeddedObject": {
                    "imageProperties": {"contentUri": uri},
                }
            }
        }
    }
    result = normalize(document, image_captures={uri: AuthorizedImageCapture(b"image", True)})
    assert result.content["tabs"][0]["documentTab"]["lists"] == tab["lists"]
    assert uri not in json.dumps(result.content)


def test_duplicate_nested_keys_invalid_limits_and_unsafe_integer_are_rejected(document):
    raw = json.dumps(document).replace('"index": 0', '"index": 0, "index": 1').encode()
    with pytest.raises(GoogleDocumentCaptureError, match="INVALID_DOCUMENT_JSON"):
        normalize(document, response_bytes=raw)
    for limit in (True, 0, -1, None):
        with pytest.raises(GoogleDocumentCaptureError, match="CAPTURE_LIMIT_REQUIRED"):
            normalize(document, max_document_bytes=limit)
    document["unknownNumber"] = 9007199254740992
    with pytest.raises(GoogleDocumentCaptureError, match="INVALID_DOCUMENT_JSON"):
        normalize(document)


def test_combined_image_budget_counts_distinct_retrievals(document):
    properties = image(document)
    first_uri = properties["contentUri"]
    objects = document["tabs"][0]["documentTab"]["inlineObjects"]
    objects["second"] = deepcopy(objects["image"])
    captures = {first_uri: AuthorizedImageCapture(b"12", True)}
    normalize(document, image_captures=captures, max_image_bytes=2)
    second_uri = "https://example.invalid/synthetic-second-image"
    objects["second"]["inlineObjectProperties"]["embeddedObject"]["imageProperties"]["contentUri"] = second_uri
    captures[second_uri] = AuthorizedImageCapture(b"34", True)
    with pytest.raises(GoogleDocumentCaptureError, match="IMAGE_LIMIT_EXCEEDED"):
        normalize(document, image_captures=captures, max_image_bytes=3)
    normalize(document, image_captures=captures, max_image_bytes=4)
