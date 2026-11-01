"""The server decides an answer's status from evidence it can check, never from the model's say-so.

  refused                   if the server's medical-advice check matches the question, or the model set
                            `refused` (either one is enough: defence in depth);
  answered                  only if the answer is substantive AND at least one citation is verified AND the
                            answer is grounded in the verified quotes;
  insufficient_information  otherwise.

Checks:
  - Citation verified: its passage was actually given to the model, and its quote appears in that passage,
    after normalising case and whitespace.
  - Substantive: not empty, and not just a way of saying "insufficient information" / "I don't know".
  - Grounded: the answer's key content words and numbers appear in the verified quotes. This is what stops a
    real but irrelevant quote from passing: it is genuine text, but the answer's content isn't in it.
    GROUNDEDNESS_THRESHOLD is PROVISIONAL until it is set on the development question set (Step 11), never
    on the evaluation cases.
  - Numbers, a hard rule on top: EVERY number in the answer must appear in the verified quotes. A wrong
    deadline or fee is the most harmful kind of error, and the word share alone let "48 hours" pass against
    a quote saying "24 hours" (3 of 4 terms matched).
"""

import re
from dataclasses import dataclass, field

from .prompts import Passage
from .schema import ModelReply

GROUNDEDNESS_THRESHOLD = 0.6  # PROVISIONAL: to be set on the dev question set in Step 11

NOT_AN_ANSWER = {"", "insufficient information", "insufficient_information", "i don't know", "i do not know",
                 "unknown", "not known", "no information", "not enough information", "n/a", "none"}

STOPWORDS = set("""a an the and or but if then than of to in on at by for from with without into onto about as is are
was were be been being do does did can could may might must should would will shall it its this that these those
there here you your yours we our us they them their i me my he she his her not no yes so such any all each per via
up down out over under again only also just very more most less least before after within""".split())

# Server-side medical-advice check (defence in depth next to the model's own `refused` flag). It looks for
# requests for personal medical guidance, not for clinic words like "appointment" or "telehealth".
MEDICAL_ADVICE = [re.compile(p, re.I) for p in [
    r"\bdiagnos\w*", r"\bsymptom\w*", r"\bdos(e|age|ing)\b", r"\bprescri\w*", r"\bmedicat\w*", r"\bmedicine\w*",
    r"\btreat(ment|ing)?\b", r"\b(antibiotic|ibuprofen|paracetamol|insulin)\w*", r"\bis (it|this) serious\b",
    r"\bshould i (take|stop|start|see a doctor)\b", r"\b(pain|fever|rash|bleeding|chest)\b", r"\bside effects?\b",
]]


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def is_medical_advice_request(question: str) -> bool:
    return any(p.search(question) for p in MEDICAL_ADVICE)


def is_substantive(answer: str) -> bool:
    return normalise(answer).strip(" .!") not in NOT_AN_ANSWER


def key_terms(text: str) -> set[str]:
    """Content words (3+ letters, not stopwords) and numbers."""
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())
    return {w for w in words if w.isdigit() or re.fullmatch(r"\d+\.\d+", w) or (len(w) >= 3 and w not in STOPWORDS)}


def numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def numbers_supported(answer: str, quotes: list[str]) -> bool:
    return numbers_in(answer) <= numbers_in(" ".join(quotes))


def groundedness(answer: str, quotes: list[str]) -> float:
    """Share of the answer's key terms found in the quotes (1.0 when the answer has none to check)."""
    terms = key_terms(answer)
    if not terms:
        return 1.0
    quoted = key_terms(" ".join(quotes))
    return len(terms & quoted) / len(terms)


@dataclass
class Verdict:
    status: str
    verified: list = field(default_factory=list)  # citations that passed
    rejected_citations: int = 0  # citations whose passage or quote didn't check out
    groundedness: float | None = None
    reason: str = ""  # for logs and evaluation, never shown as an error detail


def decide(question: str, reply: ModelReply | None, given: list[Passage]) -> Verdict:
    if is_medical_advice_request(question):
        return Verdict(status="refused", reason="server medical-advice check")
    if reply is None:
        return Verdict(status="insufficient_information", reason="no reply")
    if reply.refused:
        return Verdict(status="refused", reason="model refused")
    if not is_substantive(reply.answer):
        return Verdict(status="insufficient_information", reason="answer not substantive")
    by_id = {p.id: normalise(p.text) for p in given}
    verified, rejected = [], 0
    for c in reply.citations:
        if c.passage_id in by_id and normalise(c.quote) in by_id[c.passage_id]:
            verified.append({"passage_id": c.passage_id, "quote": c.quote})
        else:
            rejected += 1
    if not verified:
        return Verdict(status="insufficient_information", rejected_citations=rejected,
                       reason="no verified citation" if reply.citations else "no citation")
    quotes = [v["quote"] for v in verified]
    score = groundedness(reply.answer, quotes)
    if not numbers_supported(reply.answer, quotes):
        return Verdict(status="insufficient_information", verified=verified, rejected_citations=rejected,
                       groundedness=score, reason="a number in the answer is not in its quotes")
    if score < GROUNDEDNESS_THRESHOLD:
        return Verdict(status="insufficient_information", verified=verified, rejected_citations=rejected,
                       groundedness=score, reason="answer not grounded in its quotes")
    return Verdict(status="answered", verified=verified, rejected_citations=rejected, groundedness=score)
