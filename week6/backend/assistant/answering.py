"""The full question path behind POST /api/v1/assistant/ask/, in a fixed order:

  1. validate the question; 2. redact obvious identifiers; 3. server medical-advice check: refuse before any
  retrieval or model call; 4. retrieve with the tuned floor and top-k; 5. nothing above the floor, or only
  stale vectors: insufficient_information without calling the model; 6. otherwise the model, strict output
  validation and the server checks with the tuned groundedness threshold (assistant/service.py).

Internal reasons stay in logs and the evaluation; the API gets one of a few public reason codes.
"""

from dataclasses import dataclass, field

from .embeddings import Embedder
from .indexing import RetrievalConfig, retrieve, search
from .llm import LLMClient, LLMError
from .privacy import redact
from .service import REFUSAL_MESSAGE, AssistantResult, ask, clean_question
from .tuning import load_tuned
from .verify import is_medical_advice_request

PUBLIC_REASONS = {
    "": None,
    "server medical-advice check": "medical_advice_not_given",
    "model refused": "medical_advice_not_given",
    "below floor": "no_relevant_policy",
    "index out of date": "index_out_of_date",
    "no passages": "no_relevant_policy",
}
VERIFICATION_REASON = "could_not_verify_answer"  # every failed citation, groundedness, number, polarity or leak check


def public_reason(internal: str) -> str | None:
    return PUBLIC_REASONS.get(internal, VERIFICATION_REASON)


@dataclass
class Answered:
    result: AssistantResult
    sources: list = field(default_factory=list)  # passages given to the model: id, source file, similarity
    stale_skipped: int = 0
    public_reason: str | None = None
    settings: dict = field(default_factory=dict)
    cleaned: str = ""  # the redacted question (kept in the signed history; never logged or audited)
    history: object = None  # the conversation after this turn (assistant/history.History), when one was given


def shipped_retrieve(query: str, llm: LLMClient, embedder: Embedder, tuned: dict, seed: int | None = None,
                     area: str | None = None):
    """The retrieval the answer path uses for these settings (the evaluations call this too, so they measure
    exactly what ships)."""
    if tuned.get("judge"):  # Step 3 round 2: semantic candidates filtered by the LLM relevance judge
        from django.conf import settings as django_settings

        from .judge import JudgeConfig, judged_retrieve
        j = tuned["judge"]
        return judged_retrieve(query, embedder, llm, JudgeConfig(j["n"], j["f_low"], j["top_k"]),
                               seed if seed is not None else django_settings.ASSISTANT["SEED"], area=area)
    if tuned.get("retrieval"):
        return retrieve(query, embedder, RetrievalConfig(**tuned["retrieval"]), area=area)
    if area:
        return retrieve(query, embedder, RetrievalConfig(floor=tuned["floor"], top_k=tuned["top_k"]), area=area)
    return search(query, embedder, top_k=tuned["top_k"], floor=tuned["floor"])


def answer_question(question, llm: LLMClient, embedder: Embedder, tuned: dict | None = None,
                    seed: int | None = None, area: str | None = None, history=None) -> Answered:
    """`tuned` and `seed` default to the shipped values; only the evaluation runner passes others.
    If `tuned` carries a "retrieval" setting (Week 5 Step 3), that method, gate and top-k are used; otherwise
    Week 4's semantic search with the tuned floor and top-k. `area` is the opt-in metadata filter."""
    tuned = load_tuned() if tuned is None else tuned
    if history is not None:
        history.check_limits()  # raises ConversationLimit before anything else
    answered = _answer(question, llm, embedder, tuned, seed, area, history)
    if history is not None:
        r = answered.result
        answered.history = history.after(answered.cleaned, r.answer if r.status == "answered" else "",
                                         (r.usage or {}).get("total_tokens", 0),
                                         medical=r.status == "refused")
    return answered


def _answer(question, llm, embedder, tuned, seed, area, history) -> Answered:
    cleaned, redactions = redact(clean_question(question))
    medical = is_medical_advice_request(cleaned) or (
        history is not None and (history.medical or is_medical_advice_request(history.conversation_text(cleaned))))
    if medical:
        result = AssistantResult(status="refused", answer=REFUSAL_MESSAGE, redactions=redactions,
                                 reason="server medical-advice check", model=llm.model)
        return Answered(result, public_reason=public_reason(result.reason), settings=tuned, cleaned=cleaned)
    query = history.retrieval_query(cleaned) if history is not None else cleaned
    try:
        found = shipped_retrieve(query, llm, embedder, tuned, seed, area)
    except LLMError as exc:
        result = AssistantResult(status="unavailable", reason=f"embedding failed: {exc.__class__.__name__}",
                                 redactions=redactions, model=llm.model)
        return Answered(result, settings=tuned, cleaned=cleaned)
    if not found.passages:
        reason = "index out of date" if found.stale_skipped and not found.searched else "below floor"
        result = AssistantResult(status="insufficient_information", reason=reason, redactions=redactions, model=llm.model)
        return Answered(result, stale_skipped=found.stale_skipped, public_reason=public_reason(reason), settings=tuned,
                        cleaned=cleaned)
    result = ask(cleaned, found.passages, llm, groundedness_threshold=tuned["groundedness_threshold"], seed=seed,
                 history=history.turns() if history is not None else ())
    result.redactions = redactions
    sources = [{"passage_id": p.id, "source": p.source, "similarity": round(s, 3), "document_id": p.document_id,
                "version": p.version, "sha256": p.sha256}
               for p, s in zip(found.passages, found.scores) if p.id in result.passages_used]
    return Answered(result, sources=sources, stale_skipped=found.stale_skipped,
                    public_reason=public_reason(result.reason) if result.status != "answered" else None, settings=tuned,
                    cleaned=cleaned)
