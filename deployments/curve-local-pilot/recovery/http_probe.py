"""Read-only plan acceptance against an isolated restored WSGI application.

Executed only inside the disposable recovery container. Credentials are read
from a private operator mount; only aggregate results are emitted on stdout.
"""

import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (
    build_opener,
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request,
)
import uuid
from wsgiref.simple_server import make_server, WSGIRequestHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def restore_objects(stream, expected_catalog):
    root = Path("/demo-data/protected")
    root.mkdir(mode=0o700)
    seen, total = set(), 0
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for item in archive:
            require(
                item.isfile()
                and (
                    item.name == "catalog.json"
                    or re.fullmatch(
                        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", item.name
                    )
                ),
                "Unsafe protected member",
            )
            require(
                item.name not in seen and len(seen) <= 512, "Repeated protected member"
            )
            total += item.size
            require(
                0 <= item.size <= 33554432 and total <= 128 * 1024 * 1024,
                "Protected archive bound",
            )
            seen.add(item.name)
            with (root / item.name).open("xb") as out:
                os.chmod(root / item.name, 0o600)
                out.write(archive.extractfile(item).read())
    require("catalog.json" in seen, "Missing catalog")
    require(
        "sha256:" + hashlib.sha256((root / "catalog.json").read_bytes()).hexdigest()
        == expected_catalog,
        "Catalog changed after backup verification",
    )


def probe():
    output = sys.stdout
    sys.stdout = sys.stderr  # Application diagnostics must not mix with the result.
    os.umask(0o077)
    restore_objects(sys.stdin.buffer, sys.argv[1])
    target = json.loads(Path("/inputs/target.json").read_text())
    access = json.loads(Path("/inputs/access.json").read_text())
    workspace = target["workspace"]
    initiative = str(uuid.UUID(target["initiative_id"]))
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{1,255}", workspace), "Invalid target workspace"
    )
    server = make_server("127.0.0.1", 0, None, handler_class=QuietHandler)
    base = f"http://127.0.0.1:{server.server_port}"
    os.environ["WEB_URL"] = base
    Path("/tmp/recovery_probe_settings.py").write_text(
        "from recovery_operator_settings import *\n"
        "CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}}\n"
        "CELERY_BROKER_URL='memory://'\nCELERY_RESULT_BACKEND='cache+memory://'\n"
        "CURVE_MANUAL_PLAN_V2_SYNTHETIC_ROOT='/demo-data/protected'\n"
        "SESSION_COOKIE_NAME='curve-recovery-probe-session'\n"
        "CSRF_COOKIE_NAME='curve-recovery-probe-csrf'\n"
    )
    import plane  # noqa: F401 -- initializes the application settings in its required order.
    import django

    django.setup()
    from django.core.wsgi import get_wsgi_application

    server.set_app(get_wsgi_application())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())

    def request(path, data=None):
        body = None if data is None else urlencode(data).encode()
        req = Request(base + path, data=body, headers={"Accept-Encoding": "identity"})
        try:
            response = client.open(req, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    try:
        status, _, body = request("/auth/get-csrf-token/")
        require(status == 200, "CSRF endpoint unavailable")
        token = json.loads(body)["csrf_token"]
        status, _, _ = request(
            "/auth/sign-in/",
            {
                "email": access["approver"],
                "password": access["password"],
                "csrfmiddlewaretoken": token,
            },
        )
        require(status == 302, "Restored session login failed")
        status, _, body = request("/api/users/me/")
        require(
            status == 200 and json.loads(body)["email"] == access["approver"],
            "Restored principal mismatch",
        )
        path = f"/api/v1/workspaces/{workspace}/curve/initiatives/{initiative}/manual-gate2/v2/"
        status, headers, body = request(path + "status/")
        require(status == 200, "Restored manual plan unavailable")
        plan = json.loads(body)
        require(
            plan["initiative_id"] == initiative and plan["state"] == target["state"],
            "Restored plan state mismatch",
        )
        require(
            headers["ETag"]
            == f'"curve-initiative:{initiative}:v{plan["initiative_version"]}"',
            "Restored version ETag mismatch",
        )
        reference = plan["definition_ref"]
        status, _, body = request(
            path + "materials/" + str(uuid.UUID(reference["object_id"])) + "/"
        )
        require(status == 200, "Restored definition unavailable")
        material = json.loads(body)
        raw = material["content"].encode()
        require(
            material["reference"] == reference
            and len(raw) == reference["size_bytes"]
            and "sha256:" + hashlib.sha256(raw).hexdigest() == reference["digest"],
            "Restored definition mismatch",
        )
        print(
            json.dumps(
                {
                    "result": "RESTORED_HTTP_READ_PASSED",
                    "login": "normal_session_http",
                    "principal_verified": True,
                    "manual_state": plan["state"],
                    "initiative_version": plan["initiative_version"],
                    "definition_digest_verified": True,
                    "gate2_commands_sent": 0,
                }
            ),
            file=output,
        )
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    probe()
