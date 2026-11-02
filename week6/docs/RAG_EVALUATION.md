# RAG evaluation report (D5)

Sources:
- `backend/eval_suite/results.json` (the Week 6 suite run);
- the committed Week 5 reports: `assistant/eval/retrieval_baseline.md`, `generation_eval.md`, `conversation_eval.md`, `retrieval_round2.md`, `known_gaps.md`.

## Set-up

| | |
|---|---|
| Corpus | Fictional clinic policies (`assistant/policies/`), chunked at 80 tokens, embedded with `nomic-embed-text`, stored in PostgreSQL |
| Retrieval | Dense (semantic) search with the tuned similarity floor and top-k (`assistant/tuning.py`); optional area filter. Hybrid BM25 and an LLM relevance judge were evaluated in Week 5 and not shipped (`retrieval_before_after.md`, `retrieval_round2.md`). |
| Generation | `llama3.2:3b`, temperature 0.1, JSON with citations; **every citation is checked on the server** (its quote must appear in the passage it names); a groundedness threshold, and "insufficient information" when unsure |
| Benchmark | **23 frozen questions** (18 answerable, 5 unanswerable), written and SHA-pinned before any tuning; seeds 42, 43, 44, majority of 3 |

## Results (Week 6 run, identical to Week 5)

| Retrieval | Value |
|---|---|
| Recall@1 / @3 / @5 | 83% / **100%** / 100% |
| MRR | 0.97 |
| Answerable questions whose evidence survives the shipped floor | 61% (11/18) |
| False retrieval on unanswerable questions | **0%** |

| End to end (real model) | Value |
|---|---|
| Key fact correct | 7 / 18 |
| False abstention ("not enough information" when it was answerable) | **10 / 18** |
| Answered wrong | 1 / 18 |
| Correct "no answer" on unanswerable questions | **5 / 5** |
| Rejected (fabricated) citations | 0 |
| Median groundedness | 100% |

## What it means

- **Safe, but too cautious.** It never invents a citation and always declines when the answer is absent, but it declines too often when the answer is present.
- **The gap is in the shipped floor and the small model, not in retrieval.** Recall@3 is 100%, but only 61% of answerable questions keep their evidence above the shipped similarity floor, and a 3B model often prefers to abstain.
- **Tuning was frozen deliberately.** The gap is tracked in `known_gaps.md`. Turning the floor off was diagnosed there: it gave cited but **off-topic** answers, because the server checks that an answer is supported by its quotes, not that it answers the question.
- **Week 6 changed no RAG code.** That the numbers are identical shows the containerised stack reproduces Week 5 exactly.
- **Conversation and injection safety** (Week 5) are covered by the frozen conversation set and the red-team sets; see `conversation_eval.md` and [SECURITY.md](SECURITY.md).
