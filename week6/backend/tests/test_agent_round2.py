"""Week 5 Step 8 round 2: server-side dates (the model never does date arithmetic), typed arguments, no area
filter for the agent's search, and the dev and round-2 harness runs. Offline: fake model and FakeEmbedder."""

import json
from datetime import date

import pytest
from django.core.management import call_command

from agent import agent_eval
from agent.dates import resolve
from agent.models import MockBooking, PendingAction
from agent.registry import ToolContext
from agent.runner import agent_schema, coerce, date_problem, decision_schema, run_agent
from assistant import documents
from assistant.embeddings import FakeEmbedder
from assistant.llm import FakeLLM, LLMReply

THU = date(2026, 11, 26)  # the holdout clock


# ---------------- the resolver (rule 2) ----------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("anything tomorrow morning?", {"tomorrow": ["2026-11-27"]}),
        ("slots today", {"today": ["2026-11-26"]}),
        ("on Monday afternoon", {"on Monday": ["2026-11-30"]}),
        ("on Tuesday morning", {"on Tuesday": ["2026-12-01"]}),  # across the month boundary
        ("next Tuesday", {"next Tuesday": ["2026-12-01"]}),  # same as a bare weekday
        ("Thursday", {"Thursday": ["2026-12-03"]}),  # today is Thursday: the next one AFTER today
        ("book on Dec 4th", {"Dec 4th": ["2026-12-04"]}),
        ("2026-12-03 please", {"2026-12-03": ["2026-12-03"]}),
        ("November 30", {"November 30": ["2026-11-30"]}),
    ],
)
def test_resolves(message, expected):
    r = resolve(message, THU)
    assert r.dates == expected and r.unresolved == []


def test_next_week_follows_the_clinic_schedule():
    assert resolve("next week", THU).dates["next week"] == [
        "2026-11-30",
        "2026-12-01",
        "2026-12-02",
        "2026-12-03",
        "2026-12-04",
    ]


def test_next_week_would_include_saturday_if_the_schedule_did(monkeypatch):
    monkeypatch.setattr("agent.read_tools.OPEN_WEEKDAYS", (0, 1, 2, 3, 4, 5))
    assert "2026-12-05" in resolve("next week", THU).dates["next week"]


@pytest.mark.parametrize(
    "message, phrase",
    [
        ("yesterday afternoon", "yesterday"),
        ("on 10 November", "10 November"),
        ("30 February", "30 February"),
        ("2026-11-01", "2026-11-01"),
    ],
)
def test_past_impossible_dates_and_yesterday_are_unresolved_never_rolled_forward(message, phrase):
    r = resolve(message, THU)
    assert r.dates == {} and r.unresolved == [phrase]


@pytest.mark.parametrize("message", ["on a Wednesday at 9", "every Monday", "booking patterns", "no date here"])
def test_generic_weekdays_and_dateless_messages_resolve_nothing(message):
    assert not resolve(message, THU).mentioned


# ---------------- enforcement, typing, no area filter ----------------


def test_a_date_argument_must_be_a_resolved_date():
    r = resolve("book on Tuesday", THU)
    assert date_problem({"date": "2026-12-01"}, r) is None
    assert "2026-12-01" in date_problem({"date": "2026-11-30"}, r)  # off by one: rejected with the right date
    assert date_problem({"start_date": "2026-11-30", "days": 3}, r) is None  # a window that covers it
    assert date_problem({"start_date": "2026-12-02", "days": 3}, r) is not None


def test_an_unresolved_date_rejects_every_date_argument():
    assert "valid date" in date_problem({"date": "2026-11-27"}, resolve("book for yesterday", THU))


def test_no_date_in_the_message_means_no_date_constraint():
    assert date_problem({"start_date": "2026-11-27"}, resolve("any telehealth slots?", THU)) is None


def test_coercion_only_for_digits_and_true_false():
    schema = agent_schema("predict_no_show")
    out = coerce(
        {
            "lead_time_days": "30",
            "reminder_sent": "false",
            "distance_km": "null",
            "prior_appointments": "three",
            "appointment_hour": "9.5",
            "age_band": "18-24",
        },
        schema,
    )
    assert out["lead_time_days"] == 30 and out["reminder_sent"] is False
    assert out["distance_km"] == "null" and out["prior_appointments"] == "three" and out["appointment_hour"] == "9.5"


def test_the_agents_search_has_no_area_filter_but_the_tool_keeps_it():
    from agent.registry import REGISTRY

    assert "area" not in agent_schema("search_policies")["properties"]
    assert "area" in REGISTRY["search_policies"].input_schema["properties"]


def test_each_offered_tools_schema_goes_with_the_decision():
    s = decision_schema(["check_availability", "search_policies"])
    tools = {alt["properties"]["tool"]["enum"][0]: alt["properties"]["args"] for alt in s["anyOf"][1:]}
    assert set(tools) == {"check_availability", "search_policies"}
    assert tools["check_availability"]["properties"]["days"]["type"] == "integer"
    assert "area" not in tools["search_policies"]["properties"]


@pytest.fixture
def ctx(admin):
    return ToolContext(user=admin, today=lambda: THU, embedder=FakeEmbedder)


def call(tool, **args):
    return json.dumps({"action": "call_tool", "tool": tool, "args": args})


DECLINE = json.dumps({"action": "finish", "kind": "decline", "answer": "I can't do that."})


@pytest.mark.django_db
class TestRunner:
    def test_resolved_dates_go_into_the_prompt(self, ctx):
        llm = FakeLLM(replies=[DECLINE])
        r = run_agent("Any telehealth slots on Monday afternoon?", ctx, llm)
        assert '"on Monday" = Monday 2026-11-30' in llm.seen[0][1]["content"] and r.dates["resolved"]

    def test_an_off_by_one_date_is_rejected_with_the_right_date_then_corrected(self, ctx):
        wrong = call("check_availability", visit_type="telehealth", start_date="2026-11-29", days=1)
        right = call("check_availability", visit_type="telehealth", start_date="2026-11-30", days=1)
        llm = FakeLLM(replies=[wrong, right, json.dumps({"action": "finish", "kind": "answer", "answer": "ok"})])
        r = run_agent("Any telehealth slots on Monday?", ctx, llm)
        assert [s.get("code") for s in r.steps[:2]] == ["invalid_input", "ok"]
        assert "2026-11-30" in llm.seen[1][-1]["content"]

    def test_yesterday_can_never_produce_a_proposal(self, ctx):
        book = call(
            "book_mock_appointment", visit_type="in_person", date="2026-11-27", time="12:00", clinician="Clinician A"
        )
        r = run_agent(
            "Book an in-person slot for yesterday afternoon, it's urgent.", ctx, FakeLLM(replies=[book, book, DECLINE])
        )
        assert PendingAction.objects.count() == 0 and r.status == "failed"

    def test_an_area_argument_from_the_agent_is_rejected(self, ctx):
        r = run_agent(
            "Refund policy?", ctx, FakeLLM(replies=[call("search_policies", query="refund", area="billing"), DECLINE])
        )
        assert r.steps[0]["code"] == "invalid_input"

    def test_stringified_digits_are_coerced_before_the_tool(self, ctx):
        args = call("check_availability", visit_type="telehealth", start_date="2026-11-30", days="1")
        r = run_agent(
            "Telehealth on Monday?",
            ctx,
            FakeLLM(replies=[args, json.dumps({"action": "finish", "kind": "answer", "answer": "ok"})]),
        )
        assert r.steps[0]["code"] == "ok" and r.steps[0]["args"]["days"] == 1


# ---------------- the harness ----------------


def test_clarify_or_decline_scoring():
    t = {"expect": "clarify_or_decline", "tools": [], "checks": {}}
    base = {"calls": [], "status": "done", "confirmed_bookings": 0, "reached_model": True}
    assert agent_eval.score_task(t, {**base, "kind": "clarify"})["success"]
    assert agent_eval.score_task(t, {**base, "kind": "decline"})["success"]
    assert not agent_eval.score_task(t, {**base, "kind": "answer"})["success"]


class Declines(FakeLLM):
    def chat(self, messages, json_schema, seed=None):
        self.seen.append(messages)
        return LLMReply(DECLINE, "fake", 10, 5, 0)


@pytest.mark.django_db
def test_dev_and_round2_runs_offline_roll_back_and_label_honestly(admin):
    call_command("load_policies", admin=admin.email)
    before = documents.corpus_snapshot()
    dev = agent_eval.evaluate_dev(Declines(), FakeEmbedder(), 42)
    assert dev["today"] == "2026-11-18" and set(dev["tasks"]) == {f"D-{i}" for i in range(1, 11)}
    r2 = agent_eval.evaluate_round2(Declines(), FakeEmbedder(), 42)
    assert documents.corpus_snapshot() == before and PendingAction.objects.count() == MockBooking.objects.count() == 0
    assert (
        r2["second_run"]["label"] == "second run after eval-informed fixes" and r2["holdout"]["today"] == "2026-11-26"
    )
    report = agent_eval.build_round2_report(r2)
    assert "the clean measure" in report and "Not a clean measure" in report and "must pass on both" in report
    assert "DEV set" in agent_eval.build_dev_report(dev)
