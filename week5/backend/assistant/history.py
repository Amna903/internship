"""Conversation history, held by the browser and signed by the server (Week 5 Step 5).

The server stores no conversation. Each answer returns a signed blob (Django signing, compressed) that the
browser keeps in memory and sends back with the next question. The signature ties it to the user's id and
expires it after 30 minutes, so a tampered, expired or another user's blob is rejected (`HistoryInvalid`),
with no detail and before any model call.

What the blob holds, all already redacted (assistant/privacy.py runs before anything is stored):
- every earlier question, for the whole-conversation medical check (never sent to the model in full);
- the answers to the last MAX_TURNS_KEPT turns, which with their questions are the history the prompt sees,
  trimmed to HISTORY_TOKENS, oldest first (truncation, not summarisation: the 3B model could get a summary
  wrong or carry an injection into it);
- the turn count, the model tokens used, and a sticky flag once any turn was refused as medical.

Limits: after MAX_TURNS turns or CONVERSATION_TOKENS model tokens, `ConversationLimit` asks for a new
conversation, before any model call. History is never written to the audit log, AnswerRecord or logs.
"""

from dataclasses import dataclass, replace

from django.core import signing

from .prompts import approx_tokens

SALT = "assistant.history.v1"
MAX_AGE_SECONDS = 30 * 60
MAX_TURNS = 12
MAX_TURNS_KEPT = 3
HISTORY_TOKENS = 600
CONVERSATION_TOKENS = 20_000
MAX_BLOB_CHARS = 24_000


class HistoryInvalid(Exception):
    """Tampered, expired, malformed or another user's history. Never says which."""


class ConversationLimit(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason  # "turns" or "tokens"


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str  # "" when the turn wasn't answered


@dataclass(frozen=True)
class History:
    user_id: int
    questions: tuple = ()  # every earlier question (redacted), oldest first
    answers: tuple = ()  # answers to the last MAX_TURNS_KEPT turns, aligned with questions[-len(answers):]
    tokens_used: int = 0
    medical: bool = False

    @property
    def turn_count(self) -> int:
        return len(self.questions)

    def turns(self) -> list[Turn]:
        """The history the prompt may see: the last turns, oldest dropped first to fit HISTORY_TOKENS."""
        recent = [Turn(q, a) for q, a in zip(self.questions[-len(self.answers):] if self.answers else (), self.answers)]
        while recent and sum(turn_tokens(t) for t in recent) > HISTORY_TOKENS:
            recent.pop(0)
        return recent

    def retrieval_query(self, question: str) -> str:
        """Follow-up retrieval: the previous question plus the new one (no model rewrite)."""
        return f"{self.questions[-1]} {question}" if self.questions else question

    def conversation_text(self, question: str) -> str:
        """Every question in the conversation, for the medical check."""
        return " ".join((*self.questions, question))

    def check_limits(self) -> None:
        if self.turn_count >= MAX_TURNS:
            raise ConversationLimit("turns")
        if self.tokens_used >= CONVERSATION_TOKENS:
            raise ConversationLimit("tokens")

    def after(self, question: str, answer: str, tokens: int, medical: bool) -> "History":
        return replace(self, questions=(*self.questions, question),
                       answers=(*self.answers, answer)[-MAX_TURNS_KEPT:], tokens_used=self.tokens_used + tokens,
                       medical=self.medical or medical)


def turn_tokens(t: Turn) -> int:
    return approx_tokens(t.question) + approx_tokens(t.answer) + 4  # labels and line breaks


def empty(user_id: int) -> History:
    return History(user_id=user_id)


def dump(h: History) -> str:
    payload = {"u": h.user_id, "q": list(h.questions), "a": list(h.answers), "t": h.tokens_used, "m": h.medical}
    return signing.dumps(payload, salt=SALT, compress=True)


def load(blob, user_id: int) -> History:
    """None or "" starts a new conversation; anything else must be a valid, fresh blob for this user."""
    if blob in (None, ""):
        return empty(user_id)
    if not isinstance(blob, str) or len(blob) > MAX_BLOB_CHARS:
        raise HistoryInvalid()
    try:
        p = signing.loads(blob, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:  # also covers SignatureExpired
        raise HistoryInvalid() from None
    ok = (isinstance(p, dict) and set(p) == {"u", "q", "a", "t", "m"} and p["u"] == user_id
          and isinstance(p["q"], list) and all(isinstance(x, str) for x in p["q"])
          and isinstance(p["a"], list) and all(isinstance(x, str) for x in p["a"])
          and len(p["a"]) <= min(MAX_TURNS_KEPT, len(p["q"])) and isinstance(p["t"], int) and isinstance(p["m"], bool))
    if not ok:
        raise HistoryInvalid()
    return History(user_id=user_id, questions=tuple(p["q"]), answers=tuple(p["a"]), tokens_used=p["t"], medical=p["m"])
