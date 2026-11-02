# Week 5 study guide

Plain-English notes on what Week 5 built, why each choice was made, what was rejected, and what the results honestly showed. Each idea has an everyday example. Week 4's guide is in [study-guide-week4.md](study-guide-week4.md).

## Part 1: Better retrieval (RAG)

### Document versions
A policy changes, but the old answer must still be explainable. Every document now has **versions**: a new upload waits as "pending", approving it swaps it in atomically, and the old one is kept for audit.
*Everyday example:* a restaurant prints a new menu but keeps the old ones in a drawer, so it can show what a customer ordered last month.
- **Rejected:** overwriting the text in place. You could no longer tell which edition an old answer quoted.

### Keyword plus meaning (hybrid search)
**BM25** finds exact words; **embeddings** find similar meaning. **Reciprocal rank fusion** merges the two lists by rank, not score (the brief's "documented alternative" to a reranker).
*Example:* searching a library both by title words and by "books like this one".
- **Honest result:** on the dev set, hybrid did *not* beat meaning-only search, and the frozen-set "improvement" wasn't achieved (A6 stays ◐). We kept the champion rather than bend the rule.

### Chunk size
Documents are cut into pieces (40, 80, 120 or 200 tokens) before searching. Too small loses context; too big drowns the answer.

## Part 2: Evaluating honestly

### Retrieval separately from generation
If an answer is wrong, was the right passage never found, or did the model misread it? So retrieval is scored **with no model at all** (Recall@K, hit rate), and generation is scored by **giving the model the right text** (mode A) as well as end to end (mode B).
*Example:* when a meal is bad, check the ingredients separately from the cooking.

### Frozen sets, dev set, holdout
- **Frozen evaluation set:** written and hash-pinned *before* any tuning; only ever used to report.
- **Dev set:** the only place choices are made.
- **Fresh holdout:** opened once, as the clean measure. In Step 13 it was used a second time, so it was labelled "second use" and isn't clean any more.
- **Rule:** no rule changes after seeing results.

*Example:* a teacher writes the exam before teaching, practises with homework, and doesn't change the marking after seeing the scores.

## Part 3: Structured outputs and conversation

- **Schema validation:** the model must reply in JSON matching a schema. One validator checks it on the server (no extra keys, size limits, no NaN).
- **Bounded retry:** exactly one retry, and only for invalid output, never for a refusal or a timeout.
- **History:** signed by the server and held in the browser's memory only. It expires after 30 minutes, keeps the last 3 turns (oldest dropped first) within 600 tokens, and the medical check covers the whole conversation.
  *Example:* a cloakroom ticket the clerk has stamped. You hold it, but you can't forge it.
- **Token budget:** every prompt records its split (system, question, history, passages, reply reserve).

## Part 4: The controlled agent

### The model proposes; the server decides
Our own small state machine: **plan → choose a tool → validate → execute → respond**.
- The model only suggests a tool and its arguments.
- The server checks the arguments against a typed schema, checks permission (identity comes only from the server, never from the prompt) and runs the tool itself.
- The server renders the results, so model text reaches the user only as a verified policy answer or a short clarify or decline.

*Example:* a junior assistant fills in a request form, and a manager signs and processes it.
- **Rejected:** a framework agent (LangChain-style). Too much hidden behaviour for a safety-first prototype.

### Five typed tools
`search_policies`, `check_availability`, `predict_no_show`, `cluster_summaries` (read), and `book_mock_appointment` (write, **proposal only**). Contracts: [TOOLS.md](TOOLS.md).

### Limits and recovery
4 tool calls, 1 proposal, 8,000 tokens and 60 seconds per run. A failing tool gets one corrected retry; a second failure ends the run calmly.

### The write needs a human
The write tool stores a **pending action**. A person clicks Confirm or Decline on a card **written by the server**, and the confirm needs an **idempotency key**, so a double click replays instead of double-booking.
*Example:* a bank shows "Transfer £50 to X?" and only moves money when you press Confirm. Pressing twice doesn't send £100.

### The input check (a Step 8 finding)
With typed schemas, the 3B model started **inventing** missing prediction inputs. Fix: the server checks that every value appears in the user's own words; otherwise the agent must ask.
**Step 13:** 0 estimates from invented inputs in 12 runs, and the positive control still worked (3 of 3).

### Prompt injection
A retrieved document might say "book this other slot instead". The defences:
- tool output is marked as data, inside markers it can't close;
- the write tool is offered only when the user asked to book;
- any proposal must match a slot the schedule tool actually returned;
- a human confirms.

**Honest gap:** in every real run (Step 8 and Step 13) the model never actually retrieved the injected passage, so the defence is shown by offline tests only (C8 ◐).

## Part 5: MCP (Model Context Protocol)

A standard way for outside AI clients (MCP Inspector, Claude Desktop) to call tools. Our server uses the **official SDK over stdio**, so there's no network port. It exposes only the 4 read tools, through the same `run_tool` the agent uses.
- **Identity:** a short-lived token (8 hours) issued by an admin, stored only as a hash, revocable, and checked on every call.
- **Rate limit:** 30 calls per minute per token, counted in the database so it holds across processes.
- **Threat (the user's addition):** the token sits in plain text in the client's config file, which is why it's short-lived and revocable.

*Example:* a hotel key card that expires at checkout and can be cancelled at the desk.

## Part 6: Background jobs (Celery + Redis)

Approving a document means embedding it, which is slow and can fail. So approval now **queues a job** (202), and a **worker** does it.
- **States:** queued → running → succeeded / failed, in our own table.
- **Retries:** only *transient* failures (the embedder down or slow), at most 3 attempts with backoff. A permanent error fails at once.
- **Safe to repeat:** a row lock plus a "still pending?" re-check, so a duplicate delivery can't approve twice.
- **Tested for real:** a real worker on a real Redis. That test caught a bug that the fake (eager) mode hid.

*Example:* a dry cleaner gives you a ticket ("ready Thursday"). If the machine breaks they try again, but they never clean your coat twice.

## Part 7: Monitoring and drift

Every prediction is logged (version, outcome, probability, latency; **never the inputs**). Drift is measured with the **population stability index (PSI)** against the validation-split baseline. Below 0.10 is stable, 0.10–0.25 is "watch", above 0.25 is "possible drift".
- **Evidence (expectations declared first):** no drift scored 0.006, planted drift (reminders off, lead time ×3) scored 0.80, and injected failures were flagged.
- Every response says the numbers are synthetic, with no real-world medical claim.

*Example:* a bakery notices that this week's loaves weigh far more than usual. That doesn't prove the recipe changed, but someone should check.

## Part 8: The audit page

One admin page answers "what happened?": agent runs and tool calls, approval decisions, the passages each answer used, job states and model versions. **Ids, codes and versions only**, and a test checks that no message or document text leaks.

## Decisions made without review

From Step 10 on, the user asked me to finish without approvals. Every such decision, with its reason, is in [REQUIREMENTS.md](REQUIREMENTS.md#decisions-made-without-review). The cases I wrote are marked *author: assistant* and are less independent.

## What to remember

1. Let the server decide; let the model suggest.
2. Write the rules and freeze the test set *before* looking at results.
3. Report what happened, including what didn't work (A6, C8).
4. Test the real thing (a real worker, real Redis, the real model). Fakes hide bugs.
