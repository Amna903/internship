"""One question in, one safe result out: check, redact, build the prompt, call the model, validate, verify.

Every outcome is one of a few statuses. The model never labels its own answer: the status is derived by
assistant/verify.py from evidence the server can check. Errors never carry details to the user; the reason
goes to the server log, without the question text. Retrieval arrives in Step 10; this function takes the
ranked passages as input.
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings

from .costs import cost_report
from .llm import LLMClient, LLMTimeout, LLMUnavailable
from .privacy import redact
from .prompts import Passage, build_prompt
from .schema import ANSWER_SCHEMA, InvalidAnswer, parse_reply
from .verify import GROUNDEDNESS_THRESHOLD, decide, is_medical_advice_request

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
MAX_RETRIES = 1  # Week 5 Step 5: bounded, and only for invalid output
RETRY_NOTE = ("Your previous reply did not match the required JSON format. Reply again with JSON only, "
              "matching the given schema: answer, citations, refused.")
REFUSAL_MESSAGE = ("This assistant only answers questions about the fictional clinic's policies. It can't give "
                   "medical advice; please contact a qualified professional.")


class QuestionInvalid(ValueError):
    pass


@dataclass
class AssistantResult:
    # answered | insufficient_information | refused | invalid_output | timeout | unavailable
    status: str
    answer: str = ""
    citations: list = field(default_factory=list)
    passages_used: list = field(default_factory=list)
    passages_dropped: list = field(default_factory=list)
    redactions: int = 0
    rejected_citations: int = 0
    groundedness: float | None = None
    reason: str = ""  # for logs and the evaluation only
    usage: dict | None = None
    model: str = ""
    model_called: bool = False
    retries: int = 0  # Week 5 Step 5: 1 when the first reply was invalid and was asked for again
    budget: dict | None = None  # the prompt's explicit token split


def clean_question(question) -> str:
    if not isinstance(question, str) or not question.strip():
        raise QuestionInvalid("Ask a question as non-empty text.")
    if len(question) > MAX_QUESTION_CHARS:
        raise QuestionInvalid(f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    return " ".join(question.split())


def ask(question: str, ranked: list[Passage], llm: LLMClient,
        groundedness_threshold: float = GROUNDEDNESS_THRESHOLD, seed: int | None = None,
        history=()) -> AssistantResult:
    """`history`: earlier turns for the prompt (assistant/history.py); empty gives the Week 4 prompt exactly.

    Bounded retry (Week 5 Step 5): if the reply breaks the schema (or was cut off, which breaks it too), the
    model is asked once more, with a new seed and a short note. Never when it declines (that would be fishing
    for an answer) and never after a timeout or an unavailable model. Tokens from both attempts are counted."""
    cfg = settings.ASSISTANT
    question, redactions = redact(clean_question(question))
    if is_medical_advice_request(question):
        # Refused before any model call: nothing about a medical question reaches the model.
        return AssistantResult(status="refused", answer=REFUSAL_MESSAGE, redactions=redactions,
                               reason="server medical-advice check", model=llm.model)
    prompt = build_prompt(question, ranked, cfg["CONTEXT_TOKENS"], cfg["MAX_OUTPUT_TOKENS"], history=history)
    base = {"passages_used": prompt.included, "passages_dropped": prompt.dropped, "redactions": redactions,
            "model": llm.model, "model_called": True, "budget": prompt.budget}
    retry_seed = (cfg["SEED"] if seed is None else seed) + 1
    prompt_tokens = output_tokens = retries = 0
    messages = prompt.messages
    while True:
        try:
            reply = llm.chat(messages, ANSWER_SCHEMA, seed=retry_seed if retries else seed)
        except LLMTimeout as exc:
            logger.warning("assistant: model timeout (%s)", exc.reason)
            return AssistantResult(status="timeout", reason="timeout", retries=retries,
                                   usage=cost_report(prompt_tokens, output_tokens) if retries else None, **base)
        except LLMUnavailable as exc:
            logger.error("assistant: model unavailable (%s)", exc.reason)
            return AssistantResult(status="unavailable", reason="unavailable", retries=retries,
                                   usage=cost_report(prompt_tokens, output_tokens) if retries else None, **base)
        prompt_tokens, output_tokens = prompt_tokens + reply.prompt_tokens, output_tokens + reply.output_tokens
        try:
            parsed = parse_reply(reply.text)
            break
        except InvalidAnswer as exc:
            logger.warning("assistant: invalid model output (%s), attempt %d", exc.reason, retries + 1)
            if retries >= MAX_RETRIES:
                return AssistantResult(status="invalid_output", reason=exc.reason, retries=retries,
                                       usage=cost_report(prompt_tokens, output_tokens), **base)
            retries += 1
            messages = prompt.messages + [{"role": "user", "content": RETRY_NOTE}]
    usage = cost_report(prompt_tokens, output_tokens)
    given = [p for p in ranked if p.id in prompt.included]
    verdict = decide(question, parsed, given, threshold=groundedness_threshold)
    if verdict.rejected_citations:
        logger.info("assistant: %d citation(s) rejected", verdict.rejected_citations)
    answer = {"answered": parsed.answer, "refused": REFUSAL_MESSAGE}.get(verdict.status, "")
    return AssistantResult(status=verdict.status, answer=answer, citations=verdict.verified, usage=usage,
                           rejected_citations=verdict.rejected_citations, groundedness=verdict.groundedness,
                           reason=verdict.reason, retries=retries, **base)
