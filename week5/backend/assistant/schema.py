"""The structured reply the model must return, and strict validation of it.

The model does NOT label its own answer. On local tests, llama3.2:3b called a correct, correctly cited
answer "insufficient_information" every time, so a self-labelled status can't be trusted. The model returns
only its answer, its citations and a `refused` flag; the server derives the status from checkable evidence
(assistant/verify.py). The keys are in this order on purpose: with Ollama's structured output the model
writes them in schema order, so it writes the answer before anything else.

The same JSON schema is sent to Ollama (its `format` option constrains the reply) and enforced here, because
a constrained reply can still be empty, cut off at the output-token limit, or wrong.
"""

import json
from dataclasses import dataclass

STATUSES = ("answered", "insufficient_information", "refused")
MAX_ANSWER_CHARS = 1200
MAX_CITATIONS = 4
MAX_QUOTE_CHARS = 300

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"passage_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["passage_id", "quote"],
            },
        },
        "refused": {"type": "boolean"},
    },
    "required": ["answer", "citations", "refused"],
}


class InvalidAnswer(Exception):
    """The model's output broke the contract. `reason` is for the server log only."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Citation:
    passage_id: str
    quote: str


@dataclass(frozen=True)
class ModelReply:
    answer: str
    citations: tuple[Citation, ...]
    refused: bool


def parse_reply(text: str) -> ModelReply:
    """Strict: exact keys, exact types and size limits. Says nothing about whether the answer is right."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise InvalidAnswer("output is not JSON") from None
    if not isinstance(data, dict) or set(data) != {"answer", "citations", "refused"}:
        raise InvalidAnswer("output must have exactly the keys answer, citations and refused")
    answer, citations, refused = data["answer"], data["citations"], data["refused"]
    if not isinstance(answer, str) or len(answer) > MAX_ANSWER_CHARS:
        raise InvalidAnswer("answer must be a string within the size limit")
    if not isinstance(refused, bool):
        raise InvalidAnswer("refused must be true or false")
    if not isinstance(citations, list) or len(citations) > MAX_CITATIONS:
        raise InvalidAnswer("citations must be a list within the size limit")
    parsed = []
    for item in citations:
        if not isinstance(item, dict) or set(item) != {"passage_id", "quote"}:
            raise InvalidAnswer("each citation must have exactly passage_id and quote")
        if not all(isinstance(item[k], str) and item[k].strip() for k in ("passage_id", "quote")):
            raise InvalidAnswer("citation fields must be non-empty strings")
        if len(item["quote"]) > MAX_QUOTE_CHARS:
            raise InvalidAnswer("citation quote too long")
        parsed.append(Citation(item["passage_id"].strip(), item["quote"].strip()))
    return ModelReply(answer=answer.strip(), citations=tuple(parsed), refused=refused)
