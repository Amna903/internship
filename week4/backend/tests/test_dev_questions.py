"""The development questions used for tuning are separate from the frozen evaluation cases."""

import json
import re
from pathlib import Path

import pytest

from assistant import frozen

DEV = Path(frozen.__file__).resolve().parent / "dev" / "dev_questions.json"
MAX_WORD_OVERLAP = 0.5  # share of words two questions may have in common before they count as a copy


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


@pytest.fixture(scope="module")
def dev():
    return json.loads(DEV.read_text())["questions"]


@pytest.fixture(scope="module")
def evaluation():
    return json.loads(frozen.EVAL_CASES.read_text())["cases"]


def test_no_dev_question_repeats_or_closely_copies_an_evaluation_question(dev, evaluation):
    for d in dev:
        for e in evaluation:
            a, b = words(d["question"]), words(e["question"])
            assert len(a & b) / len(a | b) < MAX_WORD_OVERLAP, (d["id"], e["id"])


def test_the_step9_question_that_matches_a1_and_a6_is_not_in_the_dev_set(dev):
    assert "How late can I cancel without a charge?" not in {d["question"] for d in dev}


def test_dev_questions_cover_answerable_unanswerable_and_refused(dev):
    assert {d["expected_status"] for d in dev} == {"answered", "insufficient_information", "refused"}
    policies = {p.name for p in frozen.POLICY_DIR.glob("*.md")}
    assert all(d["expected_source"] in policies for d in dev if d["expected_status"] == "answered")
