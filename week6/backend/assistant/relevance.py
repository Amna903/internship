"""Does the answer address the question? (Week 4 review follow-up, 2026-11-16.)

verify.decide() checks that an answer is supported by real, cited policy text. Before this module it never
checked that the answer addressed the question: with the similarity floor off, U1, U2 and U9b were answered with
true, cited, off-topic statements (known_gaps.md, gap 1). These checks add an abstention step:

  topic     the question names a policy topic (cancellation, rescheduling, reminders, telehealth, billing,
            privacy) and the answer plus its quotes name none of the same topics. Every topic word occurs in
            that topic's policy file (a test checks this), so the lexicon comes from the policies, not from
            the evaluation cases.
  type      the question asks for a kind of fact the answer does not contain: "how much" needs an amount or
            "free"/"no cost"; "how long / how early / when / how many hours" needs a number with a time unit
            (the same unit, if the question names one); "how many times / how often" needs a count.
  coverage  share of the question's content words (stemmed, topic synonyms merged, generic words removed)
            found in the answer plus its quotes, below a threshold.

Which of these ship (VARIANT) and the coverage threshold were chosen on the development cases only
(dev/relevance_dev.json, rule in relevance_eval.py), then scored once on the separately frozen set.

LIMITATION: these are word checks. They catch an answer about a different topic, or one missing the kind of fact
asked for. They do NOT prove the answer is the right answer to the question: the same topic with a different
intent ("Where can I cancel?" answered with what counts as late) still passes, and none of them check that the
answer means what its quote means (citation validity is not entailment; see relevance_report.md).
"""

import re

from .verify import key_terms

# Chosen on the development cases (dev/relevance_dev.md); a test checks these match dev/relevance_dev_result.json.
VARIANT = "topic+type"
COVERAGE_THRESHOLD = None  # used only by variants that include "coverage"

GENERIC = {
    "clinic",
    "appointment",
    "appointments",
    "visit",
    "visits",
    "patient",
    "patients",
    "policy",
    "happen",
    "happens",
    "much",
    "many",
    "long",
    "someone",
    "anyone",
    "please",
    "tell",
    "know",
    "get",
    "give",
    "have",
    "has",
    "had",
    "like",
    "need",
    "want",
    "way",
    "one",
    "booking",
    "ahead",
    "allowed",
    "able",
    "what",
    "how",
    "when",
    "where",
    "which",
    "who",
    "why",
    "does",
    "will",
    "could",
    "would",
    "should",
    "may",
}

# Topic words per policy file. Each word occurs in that file (tests/test_relevance.py).
TOPIC_WORDS = {
    "cancellation": ["cancelled", "cancellation", "cancellations", "missed"],
    "rescheduling": ["rescheduling", "rescheduled", "moved"],
    "reminders": ["reminder", "reminders"],
    "telehealth": ["telehealth", "video", "camera", "microphone", "connection"],
    "billing": ["refund", "refunds", "refunded", "billing", "payment"],
    "privacy": ["privacy", "personal", "data", "authorised", "shares"],
}

SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "ed", "es", "s")


def stem(word: str) -> str:
    """Crude stemmer: one common suffix off, a trailing 'e' off, then the first six letters."""
    w = word.lower()
    for suffix in SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break
    if len(w) >= 4 and w.endswith("e"):
        w = w[:-1]
    return w[:6]


TOPIC_OF_STEM = {stem(w): topic for topic, words in TOPIC_WORDS.items() for w in words}
GENERIC_STEMS = {stem(w) for w in GENERIC}


def stems(text: str) -> set[str]:
    return {stem(t) for t in key_terms(text)}


def topics(text: str) -> set[str]:
    return {TOPIC_OF_STEM[s] for s in stems(text) if s in TOPIC_OF_STEM}


# ---------------------------------------------------------------- what kind of fact the question asks for

UNIT = r"(?:working\s+)?(?:hours?|days?|minutes?|weeks?|months?)"
SLOTS = {
    "amount": (
        re.compile(
            r"\bhow much\b(?!\s+notice)|\bwhat (?:is|are) the (?:fee|cost|price|charge)s?\b|"
            r"\bhow expensive\b|\bdoes\b.*\bcost\b",
            re.I,
        ),
        re.compile(r"\d+\s*(?:euros?|eur|€|\$|dollars?)|\bfree\b|\bno cost\b", re.I),
    ),
    "duration": (
        re.compile(
            r"\bhow (?:long|late|early|soon|quickly)\b|\bhow much notice\b|\bhow many "
            r"(?:hours|days|minutes|weeks|months)\b|\bwithin how\b|^\s*(?:until )?when\b",
            re.I,
        ),
        re.compile(rf"\b\d+\s*{UNIT}\b", re.I),
    ),
    "count": (
        re.compile(r"\bhow (?:many times|often)\b|\bmost times\b", re.I),
        re.compile(r"\b(?:once|twice|\d+\s+times)\b", re.I),
    ),
}
QUESTION_UNIT = re.compile(r"\bhow many (hours|days|minutes|weeks|months)\b", re.I)


def asked_slots(question: str) -> list[str]:
    return [name for name, (asks, _) in SLOTS.items() if asks.search(question)]


def type_matches(question: str, answer: str) -> bool:
    for name in asked_slots(question):
        if not SLOTS[name][1].search(answer):
            return False
    unit = QUESTION_UNIT.search(question)
    if unit and not re.search(rf"\b\d+\s*(?:working\s+)?{unit.group(1)[:-1]}s?\b", answer, re.I):
        return False
    return True


def coverage(question: str, answer: str, quotes: list[str]) -> float | None:
    """Share of the question's content stems found in the answer plus quotes; topic words count as their topic.
    None when the question has no content words to check (for example, a bare "question?")."""
    focus = stems(question) - GENERIC_STEMS
    if not focus:
        return None
    seen = stems(answer + " " + " ".join(quotes))
    seen_topics = {TOPIC_OF_STEM[s] for s in seen if s in TOPIC_OF_STEM}
    hit = sum(1 for s in focus if s in seen or TOPIC_OF_STEM.get(s) in seen_topics)
    return hit / len(focus)


def check(
    question: str, answer: str, quotes: list[str], variant: str = VARIANT, threshold: float | None = COVERAGE_THRESHOLD
) -> str:
    """'' if the answer passes; otherwise the internal reason."""
    parts = set(variant.split("+")) if variant and variant != "off" else set()
    if "topic" in parts:
        asked = topics(question)
        if asked and not asked & topics(answer + " " + " ".join(quotes)):
            return "answer is about a different policy topic"
    if "type" in parts and not type_matches(question, answer):
        return "answer does not give what the question asks for"
    if "coverage" in parts and threshold is not None:
        score = coverage(question, answer, quotes)
        if score is not None and score < threshold:
            return "answer does not cover the question"
    return ""
