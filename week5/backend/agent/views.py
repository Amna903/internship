"""Human confirmation of proposed writes (Week 5 Step 7). Admin session with CSRF; these are endpoints, never
tools, so the model can't reach them. Only the admin who proposed an action can see, confirm or decline it;
anyone else gets 404, the same as a missing action."""

import re

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from predictions.views import AdminOnlyAPIView

from .models import PendingAction
from .write_tools import ActionError, card, confirm, decline, expire_stale

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def error(code: str, http: int) -> Response:
    messages = {"not_found": "No such action.", "not_allowed": "You are not allowed to do this.",
                "idempotency_conflict": "This Idempotency-Key was already used for a different action.",
                "invalid_idempotency_key": "Send an Idempotency-Key header of 8-100 letters, digits, '-' or '_'."}
    message = messages.get(code, "This action can no longer be confirmed or declined.")
    return Response({"error": {"code": code, "message": message}}, status=http)


def outcome(action: PendingAction, replayed: bool = False) -> dict:
    body = {**card(action), "replayed": replayed}
    if action.booking:
        b = action.booking
        body["booking"] = {"id": b.id, "date": b.date.isoformat(), "time": b.time, "clinician": b.clinician,
                           "visit_type": b.visit_type}
    return body


class ActionBase(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agent_actions"


class ActionView(ActionBase):
    @extend_schema(summary="A proposed write: the server-written confirmation card",
                   responses={200: OpenApiResponse(description="The card"), 404: OpenApiResponse(description="No such action")})
    def get(self, request, action_id):
        expire_stale(request.user)
        action = PendingAction.objects.filter(id=action_id, user=request.user).first()
        return Response(outcome(action)) if action else error("not_found", 404)


class ActionConfirmView(ActionBase):
    @extend_schema(
        summary="Confirm a proposed write (the only way anything is written)",
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        responses={200: OpenApiResponse(description="Confirmed (or a replay of the same key)"),
                   400: OpenApiResponse(description="Missing or malformed Idempotency-Key"),
                   404: OpenApiResponse(description="No such action"),
                   409: OpenApiResponse(description="Not pending, expired, slot taken, or key used for another action")})
    def post(self, request, action_id):
        key = request.headers.get("Idempotency-Key", "")
        if not IDEMPOTENCY_KEY.match(key):
            return error("invalid_idempotency_key", 400)
        try:
            action, replayed = confirm(action_id, request.user, key, getattr(request, "request_id", ""))
        except ActionError as exc:
            return error(exc.code, exc.http)
        if action.status == PendingAction.Status.FAILED:
            return Response({**outcome(action, replayed),
                             "error": {"code": "slot_taken", "message": "That slot is no longer available."}}, status=409)
        return Response(outcome(action, replayed))


class ActionDeclineView(ActionBase):
    @extend_schema(summary="Decline a proposed write", responses={200: OpenApiResponse(description="Declined"),
                                                                  404: OpenApiResponse(description="No such action"),
                                                                  409: OpenApiResponse(description="Not pending")})
    def post(self, request, action_id):
        try:
            return Response(outcome(decline(action_id, request.user, getattr(request, "request_id", ""))))
        except ActionError as exc:
            return error(exc.code, exc.http)
