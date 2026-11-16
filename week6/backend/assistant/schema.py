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

from .validation import SchemaError, strict, validate

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


# The server-side check, derived from the schema sent to the model (assistant/validation.py): no extra keys,
# every key required, and the size limits. A field must contain more than whitespace where noted.
NON_BLANK = r"\S"
SERVER_ANSWER_SCHEMA = strict(
    ANSWER_SCHEMA,
    {
        "$.answer": {"maxLength": MAX_ANSWER_CHARS},
        "$.citations": {"maxItems": MAX_CITATIONS},
        "$.citations[].passage_id": {"pattern": NON_BLANK},
        "$.citations[].quote": {"pattern": NON_BLANK, "maxLength": MAX_QUOTE_CHARS},
    },
)


def parse_reply(text: str) -> ModelReply:
    """Strict: exact keys, exact types and size limits. Says nothing about whether the answer is right."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise InvalidAnswer("output is not JSON") from None
    try:
        validate(SERVER_ANSWER_SCHEMA, data)
    except SchemaError as exc:
        raise InvalidAnswer(str(exc)) from None
    citations = tuple(Citation(c["passage_id"].strip(), c["quote"].strip()) for c in data["citations"])
    return ModelReply(answer=data["answer"].strip(), citations=citations, refused=data["refused"])
