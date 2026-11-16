"""Week 4 review follow-up: the relevance/abstention check, how it was chosen, and what it still cannot catch."""

import json
import re

import pytest

from assistant import frozen, relevance, relevance_eval, tuning, verify
from assistant.prompts import Passage
from assistant.schema import Citation, ModelReply

FEE = "A late cancellation fee of 15 euros applies to the third late cancellation within 12 months"
LATE = "Cancellations with less than 24 hours' notice are recorded as late cancellations."
REMINDERS = "The clinic sends a reminder 48 hours before each appointment and a second reminder 2 hours before it."
RESCHEDULE = "An appointment can be moved to a new date or time up to 2 hours before it starts, at no cost."


def ask(question: str, answer: str, quote: str) -> verify.Verdict:
    passages = relevance_eval.policy_passages()
    source = next(p.id for p in passages if verify.normalise(quote) in verify.normalise(p.text))
    reply = ModelReply(answer=answer, citations=(Citation(source, quote),), refused=False)
    return verify.decide(question, reply, passages, threshold=tuning.load_tuned()["groundedness_threshold"])


class TestTheCheck:
    def test_answer_about_another_topic_is_stopped(self):
        v = ask("How much notice do reminders give before a visit?", LATE, LATE)
        assert v.status == "insufficient_information" and v.reason == "answer is about a different policy topic"

    def test_answer_without_the_kind_of_fact_asked_for_is_stopped(self):
        v = ask("How many times may I move it?", RESCHEDULE, RESCHEDULE)
        assert v.reason == "answer does not give what the question asks for"

    def test_unit_must_match_when_the_question_names_one(self):
        assert not relevance.type_matches("How many days until the refund?", "Within 2 hours.")
        assert relevance.type_matches("How many days until the refund?", "Within 10 working days.")

    def test_correct_on_topic_answers_still_pass(self):
        assert ask("When are reminders sent?", REMINDERS, REMINDERS).status == "answered"
        assert ask("What is the fee for a third late cancellation?", FEE + ".", FEE).status == "answered"

    def test_a_question_with_nothing_to_compare_is_not_judged(self):
        """Earlier tests call decide() with 'question?': no topic, no slot, so their reasons are unchanged."""
        assert relevance.check("question?", "anything", ["anything"]) == ""

    def test_relevance_runs_last_so_earlier_reasons_are_unchanged(self):
        v = ask("Can I switch reminders to email?", "No, patients cannot switch reminders to email in the patient app.",
                "patients can switch to email or turn reminders off in the patient app.")
        assert v.reason == "polarity mismatch"

    @pytest.mark.parametrize("word, expected", [("cancellations", "cancel"), ("cancelled", "cancel"),
                                                ("reminders", "remind"), ("rescheduling", "resche"),
                                                ("rescheduled", "resche"), ("refunded", "refund")])
    def test_stem(self, word, expected):
        assert relevance.stem(word) == expected


class TestHowItWasChosen:
    def test_every_topic_word_occurs_in_its_policy_file(self):
        files = {"cancellation": "cancellation.md", "rescheduling": "rescheduling.md", "reminders": "reminders.md",
                 "telehealth": "telehealth.md", "billing": "billing.md", "privacy": "privacy.md"}
        for topic, words in relevance.TOPIC_WORDS.items():
            text = (frozen.POLICY_DIR / files[topic]).read_text().lower()
            for w in words:
                assert re.search(rf"\b{w}\b", text), (topic, w)

    def test_shipped_constants_are_the_dev_choice(self):
        chosen = json.loads(relevance_eval.DEV_RESULT.read_text())["chosen"]
        assert (relevance.VARIANT, relevance.COVERAGE_THRESHOLD) == (chosen["variant"], chosen["threshold"])

    def test_dev_choice_reproduces(self):
        assert relevance_eval.choose() == json.loads(relevance_eval.DEV_RESULT.read_text())

    def test_chosen_check_blocks_no_correct_dev_answer(self):
        result = json.loads(relevance_eval.DEV_RESULT.read_text())
        row = next(r for r in result["candidates"] if r["variant"] == result["chosen"]["variant"])
        assert row["kept_good"] == row["good"] and not row["real_blocked"]

    def test_frozen_result_reproduces_and_is_reported_as_recorded(self):
        saved = json.loads(relevance_eval.FROZEN_RESULT.read_text())
        assert relevance_eval.score_frozen() == {k: v for k, v in saved.items() if k != "benchmark_replay"}
        assert (saved["shipped"]["stopped_bad"], saved["shipped"]["bad"]) == (5, 12)
        assert (saved["shipped"]["kept_good"], saved["shipped"]["good"]) == (6, 6)
        assert saved["baseline_off"]["stopped_bad"] == 1

    def test_known_gap_1_is_not_closed_by_this_check(self):
        """U1, U2, U9b (off-topic answers with the floor off) still pass the relevance check: recorded, not hidden."""
        replay = json.loads(relevance_eval.FROZEN_RESULT.read_text())["benchmark_replay"]
        rows = {r["case"]: r for r in replay if r["setting"] == "no floor"}
        assert all(rows[c]["now_stopped"] == 0 for c in ("U1", "U2", "U9b"))

    def test_shipped_benchmark_answers_are_not_blocked(self):
        replay = json.loads(relevance_eval.FROZEN_RESULT.read_text())["benchmark_replay"]
        assert all(r["now_stopped"] == 0 for r in replay if r["setting"] == "shipped")


def _case(path, case_id):
    data = json.loads(path.read_text())["cases"]
    return next(c for c in data if c["id"] == case_id)


class TestRemainingFailures:
    """Citation validity is not entailment. Each reply cites a real, verified quote but changes its meaning, and the
    server still answers it. strict=True: if a future check starts catching one, the test fails and must be moved."""

    @pytest.mark.parametrize("path, case_id, change", [
        (relevance_eval.DEV_CASES, "RD40", "'before it starts' became 'after it starts'"),
        (relevance_eval.DEV_CASES, "RD41", "the 48-hour and 2-hour reminders swapped"),
        (relevance_eval.DEV_CASES, "RD42", "'third' late cancellation became 'first'"),
        (relevance_eval.DEV_CASES, "RD45", "'reviewed' became 'rejected'"),
        (frozen.RELEVANCE_FROZEN, "RF43", "'at most twice' became 'at least twice'"),
    ])
    @pytest.mark.xfail(strict=True, reason="lexical checks compare words, not meaning")
    def test_meaning_change_is_not_answered(self, path, case_id, change):
        c = _case(path, case_id)
        assert ask(c["question"], c["answer"], c["quotes"][0]).status != "answered", change

    def test_next_to_it_an_added_negation_is_caught(self):
        c = _case(relevance_eval.DEV_CASES, "RD43")
        assert ask(c["question"], c["answer"], c["quotes"][0]).reason == "polarity mismatch"


def test_given_passages_cover_every_policy():
    assert {p.source for p in relevance_eval.policy_passages()} == {p.name for p in frozen.POLICY_DIR.glob("*.md")}
    assert all(isinstance(p, Passage) for p in relevance_eval.policy_passages())
