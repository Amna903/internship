"""Week 4 Step 11: the checkability and polarity checks, the fixed non-negating phrases, and the known limits of
lexical checks. Thresholds are the tuned ones from assistant/dev/dev_tuning.json."""

import json

import pytest

from assistant import tuning, verify
from assistant.prompts import Passage
from assistant.schema import Citation, ModelReply

RESCHEDULE = Passage("rescheduling.md#0", "rescheduling.md",
                     "An appointment can be moved to a new date or time up to 2 hours before it starts, at no cost.")
REMINDERS = Passage("reminders.md#0", "reminders.md",
                    "Reminders are sent by text message by default; patients can switch to email or turn reminders off "
                    "in the patient app. Reminders never contain test results or details of the reason for the visit.")
FEE = Passage("cancellation.md#0", "cancellation.md",
              "A late cancellation fee of 15 euros applies to the third late cancellation within 12 months, and to "
              "every late cancellation after that.")


def judge(answer: str, passage: Passage, quote: str) -> verify.Verdict:
    reply = ModelReply(answer=answer, citations=(Citation(passage.id, quote),), refused=False)
    return verify.decide("question?", reply, [passage], threshold=tuning.load_tuned()["groundedness_threshold"])


SWITCH = "patients can switch to email or turn reminders off in the patient app."
NEVER = "Reminders never contain test results or details of the reason for the visit."
FEE_QUOTE = "A late cancellation fee of 15 euros applies to the third late cancellation within 12 months"


class TestPolarity:
    def test_the_d3_idiom_passes(self):
        """'at no cost' is not a negation: the correct D3 answer must not be blocked."""
        verdict = judge("An appointment can be moved up to 2 hours before it starts.", RESCHEDULE, RESCHEDULE.text)
        assert verdict.status == "answered", verdict.reason

    def test_an_added_negation_is_caught(self):
        verdict = judge("No, patients cannot switch reminders to email in the patient app.", REMINDERS, SWITCH)
        assert verdict.status == "insufficient_information" and verdict.reason == "polarity mismatch"

    def test_a_dropped_negation_is_caught(self):
        verdict = judge("Reminders contain test results and details of the reason for the visit.", REMINDERS, NEVER)
        assert verdict.status == "insufficient_information" and verdict.reason == "polarity mismatch"

    def test_no_fee_is_not_treated_as_an_idiom(self):
        """'no fee' is deliberately not on the list: this flip about money must be caught."""
        verdict = judge("There is no fee for a late cancellation within 12 months.", FEE, FEE_QUOTE)
        assert verdict.status == "insufficient_information" and verdict.reason == "polarity mismatch"

    def test_matching_negations_pass(self):
        verdict = judge("Reminders never contain test results or the reason for the visit.", REMINDERS, NEVER)
        assert verdict.status == "answered", verdict.reason

    @pytest.mark.parametrize("text, negated", [("at no cost", False), ("recorded as no-shows", False),
                                               ("a no-show", False), ("no cost at all", True), ("not free", True),
                                               ("you can't", True), ("there is no charge", True), ("no fee", True)])
    def test_negation_detection(self, text, negated):
        assert verify.has_negation(text) is negated

    def test_the_non_negating_list_is_short_fixed_and_justified_by_the_policies(self):
        from assistant import frozen
        policies = " ".join(p.read_text().lower() for p in frozen.POLICY_DIR.glob("*.md"))
        assert len(verify.NON_NEGATING) == 2
        for phrase, justification in verify.NON_NEGATING.items():
            assert __import__("re").search(phrase, policies), phrase
            assert justification.split(":")[0] in {p.name for p in frozen.POLICY_DIR.glob("*.md")}


class TestKnownGaps:
    def test_late_cancellation_at_no_cost_against_the_fee_quote_is_not_answered(self):
        """The user's test. 'at no cost' is removed before the polarity check, so polarity can't catch this flip,
        and it has no number. It must still not be answered; the reason shows which check stopped it."""
        verdict = judge("You can cancel late at no cost.", FEE, FEE_QUOTE)
        assert verdict.status != "answered"
        assert verdict.reason == "answer not grounded in its quotes"  # caught by groundedness alone (see report)

    def test_a_bare_yes_or_no_is_too_short_to_verify(self):
        verdict = judge("No.", REMINDERS, SWITCH)
        assert verdict.status == "insufficient_information" and verdict.reason == "answer too short to verify"

    def test_lexical_checks_cannot_see_an_antonym_flip(self):
        """KNOWN GAP, recorded rather than hidden: 'refused' instead of 'paid back' flips the meaning, but no
        negation word appears, the number matches and most key terms are in the quote, so it is answered."""
        refunds = Passage("billing.md#1", "billing.md", "Refunds are reviewed by the billing team and, if approved, "
                          "paid back to the original payment method within 10 working days.")
        verdict = judge("Refunds are refused within 10 working days.", refunds, refunds.text)
        assert verdict.status == "answered"

    def test_a_partly_unsupported_answer_passes_when_most_terms_match(self):
        """KNOWN GAP: 'switch to email' is not in the quote, but most key terms are, so groundedness passes."""
        verdict = judge("Reminders are sent by text message by default; patients can switch to email.",
                        REMINDERS, "Reminders are sent by text message by default")
        assert verdict.status == "answered"


class TestTunedValues:
    def test_endpoint_values_come_from_the_dev_tuning(self):
        tuned = tuning.load_tuned()
        chosen = json.loads(tuning.RESULT.read_text())["chosen"]
        assert tuned == {"floor": chosen["floor"], "top_k": chosen["top_k"],
                         "groundedness_threshold": chosen["effective_groundedness_threshold"]}

    def test_chosen_values_follow_the_written_rules_from_the_recorded_runs(self):
        result = json.loads(tuning.RESULT.read_text())
        recomputed = json.loads(json.dumps(tuning.decide(result, tuning.load_dev())))  # JSON keys are strings
        assert recomputed == result["chosen"]

    def test_tuning_used_three_fixed_seeds(self):
        result = json.loads(tuning.RESULT.read_text())
        assert result["seeds"] == [42, 43, 44] and result["temperature"] == 0.1
