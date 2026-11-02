"""Human confirmation of proposed writes (Week 5 Step 7). Admin session with CSRF; these are endpoints, never
tools, so the model can't reach them. Only the admin who proposed an action can see, confirm or decline it;
anyone else gets 404, the same as a missing action."""

import re

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from audit.models import AuditEvent
from audit.services import record_event
from predictions.views import AdminOnlyAPIView, SmallJSONParser

from .models import AgentRun, PendingAction
from .write_tools import ActionError, card, confirm, decline, expire_stale

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def error(code: str, http: int) -> Response:
    messages = {
        "not_found": "No such action.",
        "not_allowed": "You are not allowed to do this.",
        "idempotency_conflict": "This Idempotency-Key was already used for a different action.",
        "invalid_idempotency_key": "Send an Idempotency-Key header of 8-100 letters, digits, '-' or '_'.",
    }
    message = messages.get(code, "This action can no longer be confirmed or declined.")
    return Response({"error": {"code": code, "message": message}}, status=http)


def outcome(action: PendingAction, replayed: bool = False) -> dict:
    body = {**card(action), "replayed": replayed}
    if action.booking:
        b = action.booking
        body["booking"] = {
            "id": b.id,
            "date": b.date.isoformat(),
            "time": b.time,
            "clinician": b.clinician,
            "visit_type": b.visit_type,
        }
    return body


class ActionBase(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agent_actions"


class ActionView(ActionBase):
    @extend_schema(
        summary="A proposed write: the server-written confirmation card",
        responses={200: OpenApiResponse(description="The card"), 404: OpenApiResponse(description="No such action")},
    )
    def get(self, request, action_id):
        expire_stale(request.user)
        action = PendingAction.objects.filter(id=action_id, user=request.user).first()
        return Response(outcome(action)) if action else error("not_found", 404)


class ActionConfirmView(ActionBase):
    @extend_schema(
        summary="Confirm a proposed write (the only way anything is written)",
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        responses={
            200: OpenApiResponse(description="Confirmed (or a replay of the same key)"),
            400: OpenApiResponse(description="Missing or malformed Idempotency-Key"),
            404: OpenApiResponse(description="No such action"),
            409: OpenApiResponse(description="Not pending, expired, slot taken, or key used for another action"),
        },
    )
    def post(self, request, action_id):
        key = request.headers.get("Idempotency-Key", "")
        if not IDEMPOTENCY_KEY.match(key):
            return error("invalid_idempotency_key", 400)
        try:
            action, replayed = confirm(action_id, request.user, key, getattr(request, "request_id", ""))
        except ActionError as exc:
            return error(exc.code, exc.http)
        if action.status == PendingAction.Status.FAILED:
            return Response(
                {
                    **outcome(action, replayed),
                    "error": {"code": "slot_taken", "message": "That slot is no longer available."},
                },
                status=409,
            )
        return Response(outcome(action, replayed))


class ActionDeclineView(ActionBase):
    @extend_schema(
        summary="Decline a proposed write",
        responses={
            200: OpenApiResponse(description="Declined"),
            404: OpenApiResponse(description="No such action"),
            409: OpenApiResponse(description="Not pending"),
        },
    )
    def post(self, request, action_id):
        try:
            return Response(outcome(decline(action_id, request.user, getattr(request, "request_id", ""))))
        except ActionError as exc:
            return error(exc.code, exc.http)


class AgentRunView(AdminOnlyAPIView):
    """POST /api/v1/agent/run/ (Week 5 Step 8): the only way into the tools. One message, one fresh run."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agent"
    parser_classes = [SmallJSONParser]

    @extend_schema(
        summary="Run the agent on one message",
        description=(
            "Plans and calls the typed tools (search policies, availability, no-show estimate, cluster "
            "summaries, and propose a mock booking when the message asks to book). Tool results are "
            "rendered by the server; policy answers are verified against cited passages. A proposed "
            "booking is returned as a card; nothing is booked until confirmed at "
            "/api/v1/agent/actions/<id>/confirm/."
        ),
        responses={
            200: OpenApiResponse(description="done, stopped, failed or refused"),
            400: OpenApiResponse(description="Invalid message"),
            429: OpenApiResponse(description="Rate limit"),
        },
    )
    def post(self, request):
        from assistant.embeddings import get_embedder
        from assistant.llm import get_llm
        from assistant.service import QuestionInvalid
        from assistant.tuning import load_tuned
        from assistant.views import DISCLAIMER

        from .registry import ToolContext
        from .runner import run_agent

        data = request.data if isinstance(request.data, dict) else {}
        if set(data) != {"message"}:
            return Response({"error": {"code": "invalid_request", "message": "Send only 'message'."}}, status=400)
        llm = get_llm()
        ctx = ToolContext(
            user=request.user,
            request_id=getattr(request, "request_id", ""),
            embedder=get_embedder,
            llm=lambda: llm,
            via_agent=True,
        )
        try:
            r = run_agent(data["message"], ctx, llm, groundedness_threshold=load_tuned()["groundedness_threshold"])
        except QuestionInvalid as exc:
            return Response({"error": {"code": "invalid_message", "message": str(exc)}}, status=400)
        action = PendingAction.objects.filter(id=r.pending_action["action_id"]).first() if r.pending_action else None
        run = AgentRun.objects.create(
            user=request.user,
            status=r.status,
            stopped_reason=r.stopped_reason,
            kind=r.kind,
            offered=r.offered,
            steps=r.steps,
            tool_calls=r.tool_calls,
            model_calls=r.model_calls,
            tokens=r.tokens,
            seconds=r.seconds,
            model=llm.model,
            pending_action=action,
        )
        record_event(request, AuditEvent.Action.AGENT_RUN, detail=f"{run.id}:{r.status}")
        return Response(
            {
                "run_id": str(run.id),
                "status": r.status,
                "kind": r.kind,
                "answer": r.answer,
                "citations": r.citations,
                "results": r.results,
                "pending_action": r.pending_action,
                "stopped_reason": r.stopped_reason or None,
                "steps": r.steps,
                "tool_calls": r.tool_calls,
                "tokens": r.tokens,
                "model": llm.model,
                "disclaimer": DISCLAIMER,
            }
        )
