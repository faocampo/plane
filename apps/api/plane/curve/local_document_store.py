# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Private local document bytes; callers enforce current application authorization.

The root is trusted local configuration. No client filename becomes a disk path.
References must come from authorized server metadata, never directly from a request.
This storage primitive grants no read, submission, or approval authority.
"""

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
# JSON can expand one UTF-8 control byte to a six-byte escape.
MAX_SNAPSHOT_BYTES = 6 * MAX_DOCUMENT_BYTES + 4096
_MEDIA = {".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain"}


class LocalDocumentUnavailable(ValueError):
    def __init__(self):
        super().__init__("LOCAL_DOCUMENT_UNAVAILABLE")


def _require(condition):
    if not condition:
        raise LocalDocumentUnavailable


def _uuid(value):
    try:
        _require(type(value) is str and str(uuid.UUID(value)) == value)
    except (ValueError, TypeError, AttributeError):
        raise LocalDocumentUnavailable from None
    return value


@dataclass(frozen=True)
class StoredDocument:
    workspace_id: str
    object_id: str
    content_digest: str
    byte_length: int
    media_type: str


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private(info, *, directory=False, limit=MAX_DOCUMENT_BYTES):
    _require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)))
    _require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0)
    if not directory:
        _require(info.st_nlink == 1 and 0 < info.st_size <= limit)


def read_local_upload(*, filename, stream):
    """Bound and validate upload bytes before allocating protected objects."""
    _require(type(filename) is str and 0 < len(filename) <= 255)
    suffix = Path(filename).suffix.lower()
    _require(suffix in _MEDIA)
    body = bytearray()
    while len(body) <= MAX_DOCUMENT_BYTES:
        chunk = stream.read(min(65536, MAX_DOCUMENT_BYTES + 1 - len(body)))
        _require(type(chunk) is bytes)
        if not chunk:
            break
        body.extend(chunk)
    _require(0 < len(body) <= MAX_DOCUMENT_BYTES)
    if suffix == ".pdf":
        _require(body.startswith(b"%PDF-"))
    else:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            raise LocalDocumentUnavailable from None
        _require("\x00" not in text)
    return bytes(body), _MEDIA[suffix]


class LocalDocumentStore:
    def __init__(self, root):
        path = Path(root)
        _require(path.is_absolute() and ".." not in path.parts)
        self._fd = None
        current = None
        try:
            current = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            for part in path.parts[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                os.close(current)
                current = child
            _private(os.fstat(current), directory=True)
            self._fd, current = current, None
        except OSError:
            raise LocalDocumentUnavailable from None
        finally:
            if current is not None:
                os.close(current)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _root(self):
        _require(self._fd is not None)
        _private(os.fstat(self._fd), directory=True)
        return self._fd

    @staticmethod
    def _name(workspace_id, object_id):
        return _uuid(workspace_id) + "-" + _uuid(object_id)

    def put(self, *, workspace_id, filename, stream):
        """Consume at most 10 MiB + one byte, then durably create an opaque object."""
        body, media_type = read_local_upload(filename=filename, stream=stream)
        return self._put_bytes(workspace_id=workspace_id, body=body, media_type=media_type, limit=MAX_DOCUMENT_BYTES)

    def put_snapshot(self, *, workspace_id, source):
        """Store only a server-generated lossless snapshot of an existing upload."""
        from .local_document_capture import capture_local_document

        capture = capture_local_document(store=self, workspace_id=workspace_id, reference=source)
        return self._put_bytes(
            workspace_id=workspace_id,
            body=capture.normalized_bytes,
            media_type="application/json",
            limit=MAX_SNAPSHOT_BYTES,
        )

    def _put_bytes(self, *, workspace_id, body, media_type, limit):
        _uuid(workspace_id)
        _require(0 < len(body) <= limit)
        reference = StoredDocument(
            workspace_id, str(uuid.uuid4()), "sha256:" + hashlib.sha256(body).hexdigest(), len(body), media_type
        )
        name = self._name(workspace_id, reference.object_id)
        root = self._root()
        created = False
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
            created = True
            with os.fdopen(fd, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
                _private(os.fstat(output.fileno()), limit=limit)
            os.fsync(root)
        except (OSError, LocalDocumentUnavailable):
            if created:
                os.unlink(name, dir_fd=root)
            raise LocalDocumentUnavailable from None
        return reference

    def read(self, *, workspace_id, reference):
        _require(type(reference) is StoredDocument and reference.workspace_id == _uuid(workspace_id))
        _require(reference.media_type in {*_MEDIA.values(), "application/json"})
        limit = MAX_SNAPSHOT_BYTES if reference.media_type == "application/json" else MAX_DOCUMENT_BYTES
        _require(type(reference.byte_length) is int and 0 < reference.byte_length <= limit)
        name = self._name(workspace_id, reference.object_id)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._root())
            with os.fdopen(fd, "rb") as source:
                before = os.fstat(source.fileno())
                _private(before, limit=limit)
                _require(before.st_size == reference.byte_length)
                body = source.read(limit + 1)
                _require(_stamp(before) == _stamp(os.fstat(source.fileno())))
        except OSError:
            raise LocalDocumentUnavailable from None
        _require(len(body) == reference.byte_length)
        _require("sha256:" + hashlib.sha256(body).hexdigest() == reference.content_digest)
        return body
