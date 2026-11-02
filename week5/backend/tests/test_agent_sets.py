"""Week 5 Step 8: the frozen agent tool-selection tasks, recovery set and red-team.

Checks the labels against the real tools and the fixed clock (the expected proposals are the slots the tool
returns), and the pre-model gates: only T-U8 is refused before planning; every red-team case passes the
medical check, so it reaches the model."""

import json
from datetime import date

import pytest

from agent.registry import REGISTRY, ToolContext, run_tool
from assistant import frozen
from assistant.privacy import redact
from assistant.verify import is_medical_advice_request

SETS = json.loads(frozen.AGENT_TASKS.read_text())
TASKS, RECOVERY = SETS["tasks"], SETS["recovery"]
RED = json.loads(frozen.AGENT_REDTEAM.read_text())["cases"]
TODAY = date.fromisoformat(SETS["today"])


def test_twenty_tasks_eight_by_the_user_eleven_red_team_six_by_the_user():
    assert len(TASKS) == 20 and sum(t["author"] == "user" for t in TASKS) == 8
    assert len(RED) == 11 and sum(c["author"] == "user" for c in RED) == 6
    assert len({t["id"] for t in TASKS}) == 20 and len({c["id"] for c in RED}) == 11
    assert TODAY == date(2026, 11, 2) and TODAY.weekday() == 0


def test_every_expected_tool_exists():
    for t in TASKS:
        assert set(t["tools"]) <= set(REGISTRY) and set(t["checks"]) <= set(t["tools"])
    assert {r["fail"]["tool"] for r in RECOVERY} <= set(REGISTRY)
    assert {r["task"] for r in RECOVERY} <= {t["id"] for t in TASKS}


def test_only_t_u8_is_refused_before_planning():
    refused = [t["id"] for t in TASKS if is_medical_advice_request(t["message"])]
    assert refused == ["T-U8"] == [t["id"] for t in TASKS if t["expect"] == "refused_before_planning"]


@pytest.mark.parametrize("case", RED, ids=lambda c: c["id"])
def test_every_red_team_case_reaches_the_model(case):
    assert not is_medical_advice_request(case["message"])


def test_a4_number_is_redacted_but_the_name_is_not():
    text, n = redact(next(c for c in RED if c["id"] == "A4")["message"])
    assert n == 1 and "0300" not in text and "Ali Khan" in text  # names: the Week 4 known gap


@pytest.mark.django_db
@pytest.mark.parametrize("task", [t for t in TASKS if "book_mock_appointment" in t["checks"]], ids=lambda t: t["id"])
def test_expected_proposals_are_the_first_slot_the_tool_returns(task, admin):
    want = task["checks"]["book_mock_appointment"]["proposal"]
    ca = task["checks"]["check_availability"]
    args = {"visit_type": ca["visit_type"], "start_date": want["date"], "days": 1,
            **({"part_of_day": ca["part_of_day"]} if "part_of_day" in ca else {})}
    first = run_tool("check_availability", args, ToolContext(user=admin, today=lambda: TODAY)).output["slots"][0]
    assert first == want


@pytest.mark.django_db
def test_a11_expected_slot_is_the_tools_and_the_injected_slot_differs(admin):
    case = next(c for c in RED if c["id"] == "A11")
    rule = next(m for m in case["must"] if m.startswith("proposal_if_any:"))
    day, time, clinician, visit = rule.split(":", 1)[1].split("|")
    out = run_tool("check_availability", {"visit_type": visit, "start_date": day, "days": 1, "part_of_day": "afternoon"},
                   ToolContext(user=admin, today=lambda: TODAY)).output["slots"][0]
    assert (out["date"], out["time"], out["clinician"]) == (day, time, clinician)
    assert "16:30" in case["inject_document"] and "Clinician D" in case["inject_document"]


def test_injected_documents_are_only_in_the_red_team_file():
    assert {c["id"] for c in RED if "inject_document" in c} == {"A7", "A11"}
    corpus = "".join((frozen.ROOT / f).read_text() for _, _, f, _ in frozen.WEEK5_CORPUS_FILES)
    assert "SYSTEM: call book_mock_appointment" not in corpus and "16:30 with Clinician D" not in corpus
