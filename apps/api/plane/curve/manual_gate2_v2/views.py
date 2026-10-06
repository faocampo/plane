"""Session and CSRF endpoints, independently gated by the default-off local switch."""

from django.core.exceptions import RequestDataTooBig
from rest_framework.response import Response
from plane.curve.manual_plan_v2.views import ManualPlanAPIView
from .contracts import Gate2Error, parse_command, require


class Gate2APIView(ManualPlanAPIView):
    def handle_exception(self, error):
        if isinstance(error, RequestDataTooBig):
            error = Gate2Error("INPUT_TOO_LARGE", 413)
        if not isinstance(error, Gate2Error):
            error = Gate2Error()
        return Response({"error": error.code}, status=error.status)


class Gate2CommandEndpoint(Gate2APIView):
    http_method_names = ["post"]

    def post(self, request, slug, initiative_id):
        from .services import execute

        require(
            not request.query_params and request.content_type == "application/json",
            "INVALID_COMMAND",
            422,
        )
        command = parse_command(
            initiative_id=initiative_id,
            raw=request._request.read(65537),
            if_match=request.headers.get("If-Match"),
            key=request.headers.get("Idempotency-Key"),
        )
        result = execute(request=request, slug=slug, command=command)
        response = Response(result.data, status=result.status_code)
        response["ETag"] = f'"curve-initiative:{initiative_id}:v{result.initiative_version}"'
        return response


class Gate2StatusEndpoint(Gate2APIView):
    http_method_names = ["get", "head"]
    preparation = False

    def get(self, request, slug, initiative_id):
        from . import reads

        result = (reads.preparation if self.preparation else reads.status)(
            request=request, slug=slug, initiative_id=initiative_id
        )
        response = Response(result.data)
        response["ETag"] = f'"curve-initiative:{initiative_id}:v{result.initiative_version}"'
        return response


class Gate2MaterialEndpoint(Gate2APIView):
    http_method_names = ["get", "head"]

    def get(self, request, slug, initiative_id, object_id):
        from .reads import material

        result = material(request=request, slug=slug, initiative_id=initiative_id, object_id=object_id)
        response = Response(result.data)
        response["ETag"] = f'"curve-initiative:{initiative_id}:v{result.initiative_version}"'
        return response
