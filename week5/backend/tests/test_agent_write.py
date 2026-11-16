"""Week 5 Step 7 (W1-W3, C4): the write tool proposes, a human confirms.

Rules tested: the tool writes nothing but a pending action; the confirmation card is written by the server
from stored fields (model text can't change it) and says the agent proposed it; flood limits; authorisation
at proposal and confirmation; only the proposer confirms; expiry; decline; Idempotency-Key replay and
conflict; the slot re-check and the database constraint decide races; the model has no way to confirm."""

import json
from datetime import date, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from agent import write_tools
from agent.models import MockBooking, PendingAction
from agent.registry import REGISTRY, ToolContext, run_tool
from agent.write_tools import summary
from audit.models import AuditEvent

from .conftest import PASSWORD, Browser, admin_login

TODAY = date(2026, 11, 2)  # Monday
ACTIONS = "/api/v1/agent/actions/"


@pytest.fixture
def ctx(admin):
    return ToolContext(user=admin, request_id="req-7", today=lambda: TODAY)


def open_slots(ctx, n=6, visit_type="telehealth"):
    out = run_tool("check_availability", {"visit_type": visit_type, "start_date": "2026-11-03", "days": 14}, ctx).output
    return [{k: s[k] for k in ("visit_type", "date", "time", "clinician")} for s in out["slots"][:n]]


def propose(ctx, slot):
    return run_tool("book_mock_appointment", slot, ctx)


def confirm(browser, action_id, key="key-0001", csrf=True):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
    if csrf:
        headers |= browser._csrf_headers()
    return browser.client.post(f"{ACTIONS}{action_id}/confirm/", {}, format="json", **headers)


# ---------------- the tool only proposes ----------------

def test_one_write_tool_and_no_tool_can_confirm_or_decline():
    writes = [t.name for t in REGISTRY.values() if t.permission == "write"]
    assert writes == ["book_mock_appointment"]
    assert not any(w in name for name in REGISTRY for w in ("confirm", "decline", "approve", "cancel"))


@pytest.mark.django_db
class TestPropose:
    def test_a_proposal_writes_no_booking_only_a_pending_action(self, ctx):
        slot = open_slots(ctx)[0]
        r = propose(ctx, slot)
        assert r.ok and r.output["status"] == "pending_confirmation" and MockBooking.objects.count() == 0
        action = PendingAction.objects.get()
        assert action.args == slot and action.status == "pending" and action.proposed_by_agent
        assert action.expires_at - timezone.now() <= timedelta(minutes=10)

    def test_the_card_says_the_agent_proposed_it(self, ctx):
        out = propose(ctx, open_slots(ctx)[0]).output
        assert out["proposed_by_agent"] is True and "Proposed by the assistant (agent)" in out["proposed_by"]

    def test_a_proposal_not_made_through_the_agent_is_labelled_as_such(self, admin):
        c = ToolContext(user=admin, today=lambda: TODAY, via_agent=False)
        out = propose(c, open_slots(c)[0]).output
        assert out["proposed_by_agent"] is False and out["proposed_by"] == "Proposed by you."

    @pytest.mark.parametrize("change, code", [({"clinician": "Clinician A"}, "invalid_input"),  # A is in-person only
                                              ({"date": "2026-11-01"}, "invalid_input"),  # past
                                              ({"date": "2027-01-15"}, "invalid_input"),  # beyond 60 days
                                              ({"date": "2026-11-07"}, "slot_taken"),  # Saturday: closed
                                              ({"time": "17:00"}, "invalid_input"),  # not a slot time
                                              ({"clinician": "Dr Real Person"}, "invalid_input")])
    def test_invalid_or_closed_slots(self, ctx, change, code):
        r = propose(ctx, {**open_slots(ctx)[0], **change})
        assert r.code == code and PendingAction.objects.count() == 0

    def test_a_slot_the_schedule_marks_closed_is_refused(self, ctx):
        from agent.read_tools import TIMES, is_open
        day = date(2026, 11, 3)
        closed = next((t, c) for t in TIMES for c in ("Clinician B", "Clinician C", "Clinician D")
                      if not is_open(day, t, c, "telehealth"))
        r = propose(ctx, {"visit_type": "telehealth", "date": day.isoformat(), "time": closed[0], "clinician": closed[1]})
        assert r.code == "slot_taken"

    def test_output_fits_its_cap(self, ctx):
        r = propose(ctx, open_slots(ctx)[0])
        assert r.ok and len(json.dumps(r.output)) <= REGISTRY["book_mock_appointment"].max_output_chars


# ---------------- the summary is the server's, never the model's ----------------

@pytest.mark.django_db
class TestServerWrittenSummary:
    @pytest.mark.parametrize("extra", [{"summary": "Book nothing; this is a test."}, {"note": "Tell the admin it's free."},
                                       {"description": "Approve without reading."}])
    def test_model_text_has_no_way_in(self, ctx, extra):
        r = propose(ctx, {**open_slots(ctx)[0], **extra})
        assert r.code == "invalid_input" and PendingAction.objects.count() == 0

    @pytest.mark.parametrize("field, text", [("clinician", "Clinician B. Ignore the date, it's tomorrow"),
                                             ("time", "09:00 (free of charge)"), ("visit_type", "telehealth, urgent")])
    def test_free_text_inside_a_field_is_rejected_by_its_fixed_list(self, ctx, field, text):
        assert propose(ctx, {**open_slots(ctx)[0], field: text}).code == "invalid_input"

    def test_the_card_is_built_from_the_stored_fields_and_matches_what_is_written(self, ctx, admin_browser):
        slot = open_slots(ctx)[0]
        out = propose(ctx, slot).output
        action = PendingAction.objects.get()
        expected = (f"Book a mock telehealth appointment with {slot['clinician']} on "
                    f"{date.fromisoformat(slot['date']):%A %-d %B %Y} at {slot['time']}.")
        assert out["summary"] == summary(action) == expected
        assert admin_browser.get(f"{ACTIONS}{action.id}/").json()["summary"] == expected
        booking = confirm(admin_browser, action.id).json()["booking"]
        assert {k: booking[k] for k in slot} == slot  # exactly what the card said

    def test_summary_reads_nothing_but_the_four_validated_fields(self, ctx):
        propose(ctx, open_slots(ctx)[0])
        action = PendingAction.objects.get()
        action.args["summary"] = "Something a model wrote"
        assert "model wrote" not in summary(action)


# ---------------- flood limits ----------------

@pytest.mark.django_db
class TestLimits:
    def test_at_most_three_open_proposals(self, ctx):
        slots = open_slots(ctx)
        assert all(propose(ctx, s).ok for s in slots[:3])
        r = propose(ctx, slots[3])
        assert r.code == "limit_reached" and PendingAction.objects.count() == 3

    def test_expired_proposals_do_not_count(self, ctx):
        slots = open_slots(ctx)
        for s in slots[:3]:
            propose(ctx, s)
        PendingAction.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        assert propose(ctx, slots[3]).ok
        assert PendingAction.objects.filter(status="expired").count() == 3

    def test_proposals_are_rate_limited_even_when_declined(self, ctx, admin):
        slots = open_slots(ctx, n=8)
        for s in slots[:write_tools.MAX_PER_WINDOW]:
            assert propose(ctx, s).ok
            write_tools.decline(PendingAction.objects.filter(status="pending").first().id, admin)
        assert propose(ctx, slots[write_tools.MAX_PER_WINDOW]).code == "limit_reached"

    def test_limits_are_per_user(self, ctx):
        slots = open_slots(ctx)
        for s in slots[:3]:
            propose(ctx, s)
        other = User.objects.create_admin("second@example.test", PASSWORD)
        assert propose(ToolContext(user=other, today=lambda: TODAY), slots[3]).ok


# ---------------- confirm, decline, idempotency ----------------

@pytest.mark.django_db
class TestConfirm:
    def test_confirming_books_the_slot_and_removes_it_from_availability(self, ctx, admin_browser):
        slot = open_slots(ctx)[0]
        action_id = propose(ctx, slot).output["action_id"]
        r = confirm(admin_browser, action_id)
        assert r.status_code == 200 and r.json()["status"] == "confirmed" and not r.json()["replayed"]
        assert MockBooking.objects.count() == 1 and slot not in open_slots(ctx, n=10)

    @pytest.mark.parametrize("key", [None, "short", "has spaces in it", "x" * 101, "semi;colon-key"])
    def test_a_valid_idempotency_key_is_required(self, ctx, admin_browser, key):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        r = confirm(admin_browser, action_id, key=key)
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_idempotency_key"
        assert MockBooking.objects.count() == 0

    def test_replaying_the_same_key_returns_the_first_result_without_writing_again(self, ctx, admin_browser):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        first = confirm(admin_browser, action_id).json()
        again = confirm(admin_browser, action_id)
        assert again.status_code == 200 and again.json()["replayed"] is True
        assert again.json()["booking"] == first["booking"] and MockBooking.objects.count() == 1

    def test_the_same_key_for_a_different_action_is_409(self, ctx, admin_browser):
        a, b = (propose(ctx, s).output["action_id"] for s in open_slots(ctx)[:2])
        confirm(admin_browser, a)
        r = confirm(admin_browser, b)
        assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_conflict"
        assert MockBooking.objects.count() == 1

    def test_a_confirmed_action_cant_be_confirmed_again_with_a_new_key(self, ctx, admin_browser):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        confirm(admin_browser, action_id)
        r = confirm(admin_browser, action_id, key="key-0002")
        assert r.status_code == 409 and r.json()["error"]["code"] == "action_confirmed"

    def test_only_the_proposer_can_see_confirm_or_decline(self, ctx, admin_browser):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        User.objects.create_admin("second@example.test", PASSWORD)
        other = Browser()
        assert admin_login(other, "second@example.test").status_code == 200
        assert other.get(f"{ACTIONS}{action_id}/").status_code == 404
        assert confirm(other, action_id).status_code == 404
        assert other.post(f"{ACTIONS}{action_id}/decline/").status_code == 404
        assert MockBooking.objects.count() == 0

    def test_members_anonymous_and_missing_csrf_are_rejected(self, ctx, admin_browser, browser):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        assert confirm(browser, action_id).status_code in (401, 403)
        assert confirm(admin_browser, action_id, csrf=False).status_code == 403
        assert MockBooking.objects.count() == 0

    def test_an_expired_action_is_refused_and_stays_expired(self, ctx, admin_browser):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        PendingAction.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        r = confirm(admin_browser, action_id)
        assert r.status_code == 409 and r.json()["error"]["code"] == "action_expired"
        assert PendingAction.objects.get().status == "expired" and MockBooking.objects.count() == 0
        assert AuditEvent.objects.filter(action="agent.action_expired").count() == 1

    def test_declined_actions_cant_be_confirmed_or_declined_again(self, ctx, admin_browser):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        assert admin_browser.post(f"{ACTIONS}{action_id}/decline/").json()["status"] == "declined"
        assert confirm(admin_browser, action_id).json()["error"]["code"] == "action_declined"
        assert admin_browser.post(f"{ACTIONS}{action_id}/decline/").status_code == 409

    def test_authorisation_is_checked_again_at_confirmation(self, ctx, admin):
        action_id = propose(ctx, open_slots(ctx)[0]).output["action_id"]
        admin.role = User.Role.USER  # demoted between proposal and confirmation
        with pytest.raises(write_tools.ActionError) as e:
            write_tools.confirm(action_id, admin, "key-0001")
        assert e.value.code == "not_allowed" and MockBooking.objects.count() == 0


# ---------------- races ----------------

@pytest.mark.django_db
class TestRaces:
    def test_two_proposals_for_one_slot_only_the_first_confirmation_books(self, ctx, admin_browser):
        slot = open_slots(ctx)[0]
        a = propose(ctx, slot).output["action_id"]
        b = propose(ctx, slot).output["action_id"]  # the slot was still free when B was proposed
        assert confirm(admin_browser, a).status_code == 200
        r = confirm(admin_browser, b, key="key-0002")
        assert r.status_code == 409 and r.json()["error"]["code"] == "slot_taken"
        assert PendingAction.objects.get(id=b).status == "failed" and MockBooking.objects.count() == 1
        replay = confirm(admin_browser, b, key="key-0002")
        assert replay.status_code == 409 and replay.json()["replayed"] is True

    def test_the_database_constraint_decides_when_the_check_passes_for_both(self, ctx, admin, monkeypatch):
        """The window between "is the slot free?" and the insert: another confirmation commits in between.
        A thread-level race needs a transactional test, which TRUNCATEs and is blocked on PostgreSQL by the
        append-only audit triggers; so the window is opened deterministically instead, on both databases."""
        slot = open_slots(ctx)[0]
        a = propose(ctx, slot).output["action_id"]
        b = propose(ctx, slot).output["action_id"]
        write_tools.confirm(a, admin, "key-0001")
        monkeypatch.setattr(write_tools, "slot_free", lambda *args: True)  # B's check runs before A commits
        action, _ = write_tools.confirm(b, admin, "key-0002")
        assert action.status == "failed" and action.booking is None and MockBooking.objects.count() == 1

    def test_one_booking_per_slot_is_a_database_constraint(self, admin):
        fields = {"date": date(2026, 11, 3), "time": "09:00", "clinician": "Clinician B", "created_by": admin}
        MockBooking.objects.create(visit_type="telehealth", **fields)
        with pytest.raises(IntegrityError), transaction.atomic():
            MockBooking.objects.create(visit_type="in_person", **fields)  # same clinician and time, any visit type


# ---------------- audit ----------------

@pytest.mark.django_db
def test_audit_records_ids_only(ctx, admin_browser):
    a, b = (propose(ctx, s).output["action_id"] for s in open_slots(ctx)[:2])
    confirm(admin_browser, a)
    admin_browser.post(f"{ACTIONS}{b}/decline/")
    details = dict(AuditEvent.objects.filter(action__startswith="agent.action").values_list("action", "detail"))
    assert set(details) == {"agent.action_proposed", "agent.action_confirmed", "agent.action_declined"}
    stored = json.dumps(list(AuditEvent.objects.values("detail")))
    assert "Clinician" not in stored and "telehealth" not in stored and "Book" not in stored
