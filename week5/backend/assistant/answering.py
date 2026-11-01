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


def answer_question(question, llm: LLMClient, embedder: Embedder, tuned: dict | None = None,
                    seed: int | None = None, area: str | None = None) -> Answered:
    """`tuned` and `seed` default to the shipped values; only the evaluation runner passes others.
    If `tuned` carries a "retrieval" setting (Week 5 Step 3), that method, gate and top-k are used; otherwise
    Week 4's semantic search with the tuned floor and top-k. `area` is the opt-in metadata filter."""
    tuned = load_tuned() if tuned is None else tuned
    cleaned, redactions = redact(clean_question(question))
    if is_medical_advice_request(cleaned):
        result = AssistantResult(status="refused", answer=REFUSAL_MESSAGE, redactions=redactions,
                                 reason="server medical-advice check", model=llm.model)
        return Answered(result, public_reason=public_reason(result.reason), settings=tuned)
    try:
        if tuned.get("retrieval"):
            found = retrieve(cleaned, embedder, RetrievalConfig(**tuned["retrieval"]), area=area)
        elif area:
            found = retrieve(cleaned, embedder, RetrievalConfig(floor=tuned["floor"], top_k=tuned["top_k"]), area=area)
        else:
            found = search(cleaned, embedder, top_k=tuned["top_k"], floor=tuned["floor"])
    except LLMError as exc:
        result = AssistantResult(status="unavailable", reason=f"embedding failed: {exc.__class__.__name__}",
                                 redactions=redactions, model=llm.model)
        return Answered(result, settings=tuned)
    if not found.passages:
        reason = "index out of date" if found.stale_skipped and not found.searched else "below floor"
        result = AssistantResult(status="insufficient_information", reason=reason, redactions=redactions, model=llm.model)
        return Answered(result, stale_skipped=found.stale_skipped, public_reason=public_reason(reason), settings=tuned)
    result = ask(cleaned, found.passages, llm, groundedness_threshold=tuned["groundedness_threshold"], seed=seed)
    result.redactions = redactions
    sources = [{"passage_id": p.id, "source": p.source, "similarity": round(s, 3), "document_id": p.document_id,
                "version": p.version, "sha256": p.sha256}
               for p, s in zip(found.passages, found.scores) if p.id in result.passages_used]
    return Answered(result, sources=sources, stale_skipped=found.stale_skipped,
                    public_reason=public_reason(result.reason) if result.status != "answered" else None, settings=tuned)
