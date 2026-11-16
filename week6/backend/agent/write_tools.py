"""The write tool (Week 5 Step 7): book a mock appointment, only after a human confirms.

Rules in docs/REQUIREMENTS.md ("Step 7 rules"). The tool only PROPOSES: it stores a pending action and writes
nothing else. Confirming and declining are server functions behind admin endpoints (agent/views.py), never
tools, so the model can't confirm. The summary a human sees is built here from the stored, validated fields,
never from model-written text, so the card always matches what will be written.
"""

from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from audit.services import record_event

from .models import MockBooking, PendingAction
from .read_tools import CLINICIANS, HORIZON_DAYS, OPEN_WEEKDAYS, TIMES, is_open, obj
from .registry import Tool, ToolFailure, allowed, register

EXPIRY = timedelta(minutes=10)
MAX_OPEN = 3  # open pending actions per user
RATE_WINDOW, MAX_PER_WINDOW = timedelta(minutes=10), 6  # proposals per user per window
AGENT_LABEL = "Proposed by the assistant (agent). Nothing is booked until you confirm."
ALL_CLINICIANS = sorted({c for cs in CLINICIANS.values() for c in cs})


def summary(action: PendingAction) -> str:
    """From the stored fields only. Every field was validated against a fixed list or pattern."""
    a = action.args
    day = date.fromisoformat(a["date"])
    visit = {"in_person": "in-person", "telehealth": "telehealth"}[a["visit_type"]]
    return f"Book a mock {visit} appointment with {a['clinician']} on {day:%A %-d %B %Y} at {a['time']}."


def card(action: PendingAction) -> dict:
    return {
        "action_id": str(action.id),
        "status": action.status,
        "summary": summary(action),
        "proposed_by_agent": action.proposed_by_agent,
        "proposed_by": AGENT_LABEL if action.proposed_by_agent else "Proposed by you.",
        "expires_at": action.expires_at.isoformat(),
    }


def slot_free(day: date, time: str, clinician: str, visit_type: str) -> bool:
    return (
        day.weekday() in OPEN_WEEKDAYS
        and time in TIMES
        and clinician in CLINICIANS[visit_type]
        and is_open(day, time, clinician, visit_type)
        and not MockBooking.objects.filter(date=day, time=time, clinician=clinician).exists()
    )


def expire_stale(user=None) -> None:
    stale = PendingAction.objects.filter(status=PendingAction.Status.PENDING, expires_at__lte=timezone.now())
    if user is not None:
        stale = stale.filter(user=user)
    for action in stale:
        action.status, action.decided_at = PendingAction.Status.EXPIRED, timezone.now()
        action.save(update_fields=["status", "decided_at"])
        record_event(_req(action.user), AuditEvent.Action.AGENT_ACTION_EXPIRED, detail=str(action.id))


def _req(user, request_id=""):
    from types import SimpleNamespace

    return SimpleNamespace(user=user, request_id=request_id)


def book_mock_appointment(args: dict, ctx) -> dict:
    today = ctx.today()
    try:
        day = date.fromisoformat(args["date"])
    except ValueError:
        raise ToolFailure("invalid_input", ("$.date",)) from None
    if not today <= day <= today + timedelta(days=HORIZON_DAYS):
        raise ToolFailure("invalid_input", ("$.date",))
    if args["clinician"] not in CLINICIANS[args["visit_type"]]:
        raise ToolFailure("invalid_input", ("$.clinician",))
    with transaction.atomic():
        expire_stale(ctx.user)
        mine = PendingAction.objects.select_for_update().filter(user=ctx.user)  # serialises one user's proposals
        open_now = mine.filter(status=PendingAction.Status.PENDING).count()
        recent = mine.filter(created_at__gte=timezone.now() - RATE_WINDOW).count()
        if open_now >= MAX_OPEN or recent >= MAX_PER_WINDOW:
            raise ToolFailure("limit_reached")
        if not slot_free(day, args["time"], args["clinician"], args["visit_type"]):
            raise ToolFailure("slot_taken")
        action = PendingAction.objects.create(
            tool="book_mock_appointment",
            user=ctx.user,
            proposed_by_agent=ctx.via_agent,
            args={k: args[k] for k in ("visit_type", "date", "time", "clinician")},
            expires_at=timezone.now() + EXPIRY,
        )
        record_event(_req(ctx.user, ctx.request_id), AuditEvent.Action.AGENT_ACTION_PROPOSED, detail=str(action.id))
    return {**card(action), "status": "pending_confirmation"}


register(
    Tool(
        name="book_mock_appointment",
        description="Propose booking one open slot in the fictional schedule. Nothing is booked until the admin "
        "confirms it outside the chat. Use check_availability first.",
        input_schema=obj(
            {
                "visit_type": {"type": "string", "enum": list(CLINICIANS)},
                "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                "time": {"type": "string", "enum": TIMES},
                "clinician": {"type": "string", "enum": ALL_CLINICIANS},
            },
            ["visit_type", "date", "time", "clinician"],
        ),
        output_schema=obj(
            {
                "action_id": {"type": "string"},
                "status": {"type": "string", "enum": ["pending_confirmation"]},
                "summary": {"type": "string"},
                "proposed_by_agent": {"type": "boolean"},
                "proposed_by": {"type": "string"},
                "expires_at": {"type": "string"},
            },
            ["action_id", "status", "summary", "proposed_by_agent", "proposed_by", "expires_at"],
        ),
        handler=book_mock_appointment,
        permission="write",
        timeout_seconds=5.0,
        max_output_chars=800,
    )
)


# ---------------------------------------------------------------- confirm and decline (not tools)


class ActionError(Exception):
    def __init__(self, code: str, http: int):
        super().__init__(code)
        self.code, self.http = code, http


def _owned_pending(action_id, user) -> PendingAction:
    action = PendingAction.objects.select_for_update().filter(id=action_id, user=user).first()
    if action is None:
        raise ActionError("not_found", 404)  # another admin's action looks the same as a missing one
    return action


def confirm(action_id, user, idempotency_key: str, request_id: str = "") -> tuple[PendingAction, bool]:
    """Returns (action, replayed). Raises ActionError. Authorisation (active admin) is re-checked here."""
    if not allowed(_write_tool(), user):
        raise ActionError("not_allowed", 403)
    with transaction.atomic():
        earlier = PendingAction.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if earlier is not None:
            if str(earlier.id) != str(action_id):
                raise ActionError("idempotency_conflict", 409)
            return earlier, True
        action = _owned_pending(action_id, user)
        if action.status == PendingAction.Status.PENDING and action.expires_at <= timezone.now():
            action.status, action.decided_at = PendingAction.Status.EXPIRED, timezone.now()
            action.save(update_fields=["status", "decided_at"])
            record_event(_req(user, request_id), AuditEvent.Action.AGENT_ACTION_EXPIRED, detail=str(action.id))
        if action.status != PendingAction.Status.PENDING:
            refused = action.status  # raised after this transaction commits, so "expired" is kept
        else:
            refused = None
            _book(action, user, idempotency_key, request_id)
    if refused:
        raise ActionError(f"action_{refused}", 409)
    return action, False


def _book(action: PendingAction, user, idempotency_key: str, request_id: str) -> None:
    """Inside confirm's transaction. The unique constraint decides a race: the loser is FAILED, nothing written."""
    a = action.args
    day = date.fromisoformat(a["date"])
    booking = None
    if slot_free(day, a["time"], a["clinician"], a["visit_type"]):
        try:
            with transaction.atomic():  # savepoint: the constraint decides a race
                booking = MockBooking.objects.create(
                    date=day, time=a["time"], clinician=a["clinician"], visit_type=a["visit_type"], created_by=user
                )
        except IntegrityError:
            booking = None
    action.status = PendingAction.Status.CONFIRMED if booking else PendingAction.Status.FAILED
    action.booking, action.decided_at, action.idempotency_key = booking, timezone.now(), idempotency_key
    action.save(update_fields=["status", "booking", "decided_at", "idempotency_key"])
    record_event(
        _req(user, request_id),
        AuditEvent.Action.AGENT_ACTION_CONFIRMED if booking else AuditEvent.Action.AGENT_ACTION_FAILED,
        detail=f"{action.id}:{booking.id}" if booking else str(action.id),
    )


def decline(action_id, user, request_id: str = "") -> PendingAction:
    if not allowed(_write_tool(), user):
        raise ActionError("not_allowed", 403)
    with transaction.atomic():
        action = _owned_pending(action_id, user)
        if action.status != PendingAction.Status.PENDING:
            raise ActionError(f"action_{action.status}", 409)
        action.status, action.decided_at = PendingAction.Status.DECLINED, timezone.now()
        action.save(update_fields=["status", "decided_at"])
        record_event(_req(user, request_id), AuditEvent.Action.AGENT_ACTION_DECLINED, detail=str(action.id))
    return action


def _write_tool() -> Tool:
    from .registry import REGISTRY

    return REGISTRY["book_mock_appointment"]
