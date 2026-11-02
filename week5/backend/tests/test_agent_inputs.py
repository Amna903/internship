"""Week 5 Step 8 input-check rules: the server decides whether a prediction's inputs were given. New wording
only (never the frozen messages)."""

import json

import pytest

from agent.inputs import missing_fields, normalise, stated
from agent.registry import ToolContext
from agent.runner import run_agent
from assistant.llm import FakeLLM

FULL = ("Chance of a no-show for a video visit booked twenty-one days ahead, on a Friday at 2pm, booked online, "
        "aged 45-54, with a reminder, 12 km away, 5 previous visits with 1 missed?")
ARGS = {"lead_time_days": 21, "appointment_weekday": "friday", "appointment_hour": 14, "age_band": "45-54",
        "visit_type": "telehealth", "booking_channel": "web", "reminder_sent": True, "prior_appointments": 5,
        "prior_no_shows": 1, "distance_km": 12}


def test_every_field_stated():
    assert missing_fields(ARGS, FULL) == []


def test_compound_number_words_and_ranges():
    assert "21 days" in normalise("twenty-one days") and "45-54" in normalise("aged 45–54")


@pytest.mark.parametrize("field, value", [("lead_time_days", 20), ("appointment_weekday", "monday"), ("appointment_hour", 9),
                                          ("age_band", "35-44"), ("visit_type", "in_person"), ("booking_channel", "phone"),
                                          ("reminder_sent", False), ("prior_appointments", 6), ("prior_no_shows", 0),
                                          ("distance_km", 3)])
def test_a_value_the_message_did_not_state_is_missing(field, value):
    assert missing_fields({**ARGS, field: value}, FULL) == [field]


def test_a_vague_request_states_nothing_so_every_invented_value_is_missing():
    assert missing_fields(ARGS, "Will this person turn up?") == list(ARGS)


@pytest.mark.parametrize("message, field, value", [
    ("booked a week in advance", "lead_time_days", 7),
    ("three weeks ahead", "lead_time_days", 21),
    ("at 9:00", "appointment_hour", 9), ("at 10am", "appointment_hour", 10), ("at four pm", "appointment_hour", 16),
    ("over 65", "age_band", "65+"),
    ("face to face", "visit_type", "in_person"), ("an in-person visit", "visit_type", "in_person"),
    ("in person", "visit_type", "in_person"),
    ("used the app", "booking_channel", "app"), ("called us", "booking_channel", "phone"),
    ("no reminder", "reminder_sent", False),
    ("never missed one", "prior_no_shows", 0), ("missed 2 out of 7", "prior_no_shows", 2),
    ("missed 2 out of 7", "prior_appointments", 7),
    ("distance unknown", "distance_km", None), ("lives 4.5 km away", "distance_km", 4.5),
])
def test_phrasings(message, field, value):
    assert value in stated(message)[field]


@pytest.mark.parametrize("message, field", [("booked 12 ahead", "lead_time_days"), ("around lunchtime", "appointment_hour"),
                                            ("some reminder", "reminder_sent"), ("not far away", "distance_km"),
                                            ("call 0300-1234567", "age_band")])
def test_unclear_phrasing_is_not_stated(message, field):
    assert not stated(message)[field]


def test_the_agent_cannot_get_an_estimate_from_invented_inputs(admin):
    args = json.dumps({"action": "call_tool", "tool": "predict_no_show", "args": ARGS})
    clarify = json.dumps({"action": "finish", "kind": "clarify", "answer": "Which weekday, hour and booking channel?"})
    llm = FakeLLM(replies=[args, clarify])
    r = run_agent("What's the no-show chance for a video visit?", ToolContext(user=admin), llm)
    assert r.steps[0]["code"] == "invalid_input" and r.results == [] and r.kind == "clarify"
    assert "appointment_weekday" in llm.seen[1][-1]["content"] and "never guess" in llm.seen[1][-1]["content"]


@pytest.mark.django_db
def test_fully_stated_inputs_still_get_an_estimate(admin):
    args = json.dumps({"action": "call_tool", "tool": "predict_no_show", "args": ARGS})
    done = json.dumps({"action": "finish", "kind": "answer", "answer": "ok"})
    r = run_agent(FULL, ToolContext(user=admin), FakeLLM(replies=[args, done]))
    assert r.steps[0]["code"] == "ok" and r.results[0]["tool"] == "predict_no_show"
