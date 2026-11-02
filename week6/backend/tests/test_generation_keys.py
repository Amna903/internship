"""Week 5 Step 4: the frozen generation answer key and the key-fact matcher (number words, whole words,
direct negation)."""

import hashlib
import json

import pytest

from assistant import frozen
from assistant.keyfacts import all_facts, has_fact, normalise

KEYS = json.loads(frozen.GENERATION_KEYS.read_text())["keys"]
CASES = {c["id"]: c for c in json.loads(frozen.RETRIEVAL_CASES.read_text())["cases"]}
U02 = KEYS["U02"][1]
U08 = KEYS["U08"][0]


def test_key_is_frozen():
    assert (
        hashlib.sha256(frozen.GENERATION_KEYS.read_bytes()).hexdigest()
        == frozen.WEEK5_FROZEN_SHA256["eval/generation_keys.json"]
    )


def test_every_answerable_question_has_a_key_and_only_those():
    assert set(KEYS) == {i for i, c in CASES.items() if c["answerable"]}


@pytest.mark.parametrize("cid", sorted(KEYS))
def test_every_key_fact_appears_un_negated_in_its_evidence(cid):
    quotes = " ".join(e["quote"] for e in CASES[cid]["evidence"])
    assert all_facts(quotes, KEYS[cid])


@pytest.mark.parametrize(
    "text, expected",
    [
        ("three hours", "3 hours"),
        ("Fifteen working days", "15 working days"),
        ("rescheduled twice", "rescheduled 2 times"),
        ("three-hour", "3 hour"),
        ("isn't free", "is not free"),
    ],
)
def test_normalise(text, expected):
    assert normalise(text) == expected


@pytest.mark.parametrize(
    "answer, facts, ok",
    [
        ("You can park for three hours.", ["3 hours"], True),
        ("Within 115 working days.", ["15 working days"], False),  # whole words only
        ("30 hours of parking", ["3 hours"], False),
        ("Guide dogs are not allowed.", U08, False),  # user-required negation case
        ("An interpreter is not free.", U02, False),  # user-required negation case
        ("Animals aren't welcome here.", U08, False),
        ("Dogs are no longer allowed.", U08, False),
        ("You can't bring a dog.", U08, False),
        ("Assistance animals are welcome in all areas.", U08, True),
        ("No, there is no interest.", ["no interest"], True),  # window of 2 words keeps this correct
        ("There is no charge for an interpreter.", U02, True),
        ("It is not available, but parking is free.", U02, True),  # one un-negated occurrence is enough
    ],
)
def test_key_fact_matching(answer, facts, ok):
    assert has_fact(answer, facts) is ok


def test_user_reviewed_changes_are_in_the_key():
    assert KEYS["U02"][0] == ["interpreter", "translator"]
    assert "3 months" not in KEYS["U03"][0] and {"3 instalments", "3 installments"} <= set(KEYS["U03"][0])
    assert KEYS["U07"] == [["in writing", "written authorisation", "written authorization"]]
