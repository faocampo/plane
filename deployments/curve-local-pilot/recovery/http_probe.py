"""Plan reads and optional fault checks against an isolated restored application.

Executed only inside the disposable recovery container. Optional pilot controls
mutate this copy's flags, objects and membership, and send denied commands.
Credentials are read
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


def pilot_controls(request, access, plan, path, reference):
    """Inject faults only in this disposable copy; keep business history intact."""
    from django.conf import settings
    from plane.db.models import WorkspaceMember
    from plane.curve.models import Initiative
    from plane.curve.manual_gate2_v2.models import (
        ManualGate2ControlV2,
        ManualGate2RecordV2,
        ManualTaskClaimV2,
        ManualTaskClaimHistoryV2,
    )
    from plane.curve.manual_plan_v2.models import (
        ManualPlanDraftV2,
        ManualPlanRevisionV2,
    )
    from plane.curve.manual_gate2_v2.contracts import parse_command

    def graph():
        values = {
            "initiative": list(
                Initiative.objects.filter(id=plan["initiative_id"]).values()
            )
        }
        for model in (
            ManualGate2ControlV2,
            ManualGate2RecordV2,
            ManualTaskClaimV2,
            ManualTaskClaimHistoryV2,
            ManualPlanDraftV2,
            ManualPlanRevisionV2,
        ):
            values[model.__name__] = list(
                model.objects.filter(initiative_id=plan["initiative_id"])
                .order_by("id")
                .values()
            )
        return hashlib.sha256(
            json.dumps(values, sort_keys=True, default=str).encode()
        ).hexdigest()

    before = graph()
    cases = []
    missing_path = path.replace(plan["initiative_id"], str(uuid.uuid4())) + "status/"
    denied_status, denied_headers, denied_body = request(missing_path)
    require(
        denied_status == 404 and "ETag" not in denied_headers,
        "Unknown resource did not fail closed",
    )

    def denied(route, session=None, **kwargs):
        status, headers, body = request(route, session=session, **kwargs)
        require(
            status == denied_status and body == denied_body and "ETag" not in headers,
            "Protected denial leaked or differed from unknown resource",
        )

    def session_for(role, password=None):
        client = build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())
        status, _, body = request("/auth/get-csrf-token/", session=client)
        require(status == 200, "Role CSRF endpoint unavailable")
        token = json.loads(body)["csrf_token"]
        status, _, _ = request(
            "/auth/sign-in/",
            session=client,
            data={
                "email": access[role],
                "password": access["password"] if password is None else password,
                "csrfmiddlewaretoken": token,
            },
        )
        require(status == 302, "Role login did not complete")
        return client

    anonymous = build_opener(HTTPCookieProcessor(CookieJar()), NoRedirect())
    denied(path + "status/", anonymous)
    cases.append("anonymous_plan_read_denied")
    invalid = session_for("approver", "incorrect-synthetic-password")
    require(
        request("/api/users/me/", session=invalid)[0] == 401,
        "Invalid password authenticated",
    )
    denied(path + "status/", invalid)
    cases.append("invalid_password_did_not_create_authenticated_session")
    rationale = next(
        x["reference"] for x in plan["rationales"] if x["intent"] == "APPROVE"
    )
    payload = {
        "schema_version": "curve.manual-gate2.command/v2-candidate",
        "action": "APPROVE",
        "draft_revision_id": plan["draft_revision_id"],
        "subject_ref": plan["subject_ref"],
        "rationale_ref": rationale,
        "claims": [],
        "reconciliation_ref": None,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    etag = f'"curve-initiative:{plan["initiative_id"]}:v{plan["initiative_version"]}"'
    for role in ("owner", "code_reviewer"):
        actor = session_for(role)
        status, _, body = request("/api/users/me/", session=actor)
        require(
            status == 200 and json.loads(body)["email"] == access[role],
            "Role identity mismatch",
        )
        status, _, body = request(path + "status/", session=actor)
        require(
            status == 200 and "APPROVE" not in json.loads(body)["allowed_actions"],
            "Other role received technical approval authority",
        )
        status, _, body = request("/auth/get-csrf-token/", session=actor)
        require(status == 200, "Decision CSRF endpoint unavailable")
        key = str(uuid.uuid4())
        parse_command(
            initiative_id=uuid.UUID(plan["initiative_id"]),
            raw=raw,
            if_match=etag,
            key=key,
        )
        denied(
            path + "commands/",
            actor,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-CSRFTOKEN": json.loads(body)["csrf_token"],
                "If-Match": etag,
                "Idempotency-Key": key,
            },
        )
        cases.append(role + "_cannot_approve_technical_plan")
    status, _, body = request(path + "status/")
    require(
        status == 200 and "APPROVE" in json.loads(body)["allowed_actions"],
        "Assigned technical approver lost valid authority",
    )
    cases.append("assigned_technical_approver_retains_current_authority")
    workspace_path = path.replace(
        "/workspaces/" + path.split("/workspaces/", 1)[1].split("/", 1)[0] + "/",
        "/workspaces/unavailable-synthetic-workspace/",
    )
    denied(workspace_path + "status/")
    cases.append("wrong_workspace_has_uniform_denial")
    material_path = path + "materials/" + reference["object_id"] + "/"
    enabled = settings.CURVE_MANUAL_GATE2_V2_ENABLED
    try:
        settings.CURVE_MANUAL_GATE2_V2_ENABLED = False
        denied(path + "status/")
        denied(material_path)
    finally:
        settings.CURVE_MANUAL_GATE2_V2_ENABLED = enabled
    require(
        request(path + "status/")[0] == 200,
        "Read did not recover after restoring the local flag",
    )
    cases.append("operator_disable_fences_status_and_material_reads")
    body_path = Path("/demo-data/protected") / reference["object_id"]
    original = body_path.read_bytes()
    try:
        body_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        denied(material_path)
        denied(path + "status/")
    finally:
        body_path.write_bytes(original)
    require(
        request(material_path)[0] == 200,
        "Read did not recover after restoring exact protected bytes",
    )
    cases.append("corrupt_protected_object_is_not_served_or_used")
    membership = WorkspaceMember.objects.get(
        workspace_id=plan["workspace_id"],
        member__email=access["approver"],
        deleted_at__isnull=True,
    )
    was_active = membership.is_active
    require(was_active, "Technical actor was not an active workspace member")
    try:
        WorkspaceMember.objects.filter(id=membership.id).update(is_active=False)
        require(
            request("/api/users/me/")[0] == 200,
            "Revocation check lost the authenticated session",
        )
        denied(path + "status/")
        denied(material_path)
    finally:
        WorkspaceMember.objects.filter(id=membership.id).update(is_active=was_active)
    cases.append("membership_revocation_fences_existing_session")
    require(
        graph() == before, "Denied operations changed the controlling business graph"
    )
    cases.append("initiative_draft_control_history_and_claims_preserved")
    return {
        "result": "PILOT_CONTROL_CHECKS_PASSED",
        "cases": cases,
        "gate2_commands_sent": 2,
        "gate2_commands_allowed": 0,
        "operational_acceptance": False,
        "scope": "Synthetic copy only; role checks, revocation and injected local faults do not approve an operational pilot",
    }


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

    def request(path, data=None, *, session=None, headers=None):
        body = (
            data
            if isinstance(data, bytes)
            else None
            if data is None
            else urlencode(data).encode()
        )
        req = Request(
            base + path,
            data=body,
            headers={"Accept-Encoding": "identity", **(headers or {})},
        )
        try:
            response = (session or client).open(req, timeout=30)
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
        result = {
            "result": "RESTORED_HTTP_READ_PASSED",
            "login": "normal_session_http",
            "principal_verified": True,
            "manual_state": plan["state"],
            "initiative_version": plan["initiative_version"],
            "definition_digest_verified": True,
            "gate2_commands_sent": 0,
        }
        if "--pilot-controls" in sys.argv[2:]:
            result["pilot_controls"] = pilot_controls(
                request, access, plan, path, reference
            )
            result["gate2_commands_sent"] = result["pilot_controls"][
                "gate2_commands_sent"
            ]
        print(json.dumps(result), file=output)
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    probe()
