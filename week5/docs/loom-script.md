# Loom script: Week 5 (about 9 minutes)

Covers the brief's list: the working demo, code architecture, actual AI prompts and refinements, context management, blast-radius controls, and debugging and verification. Read the bold lines; the rest is what to show. The one-word cue list at the end is for glancing at while recording.

Before recording:
- start Redis, Ollama, Django (`runserver`), the Celery worker and Next.js (`npm start`);
- sign in as the admin;
- open the Agent, Assistant and Audit tabs, the GitHub PR, and `docs/REQUIREMENTS.md`.

## 1. Intro (0:00–0:30)
**"Week 5 adds advanced retrieval, a controlled agent with five typed tools, an MCP server, background jobs, drift monitoring and an audit page. All data is synthetic and the clinic is fictional. The rule throughout: the model suggests, the server decides."**

## 2. Demo: the Agent tab (0:30–2:30)
- Ask: "Please book the first telehealth slot on Thursday morning."
  - Show the trace: `check_availability → ok`, `book_mock_appointment → ok`.
  - Show the card: **"Proposed by the agent"**, its summary written by the server.
- Click **Decline**: the status says declined and nothing is booked. Ask again and click **Confirm**: the booking appears.
  - Point out the `Idempotency-Key` in the network tab: a double click replays, never double-books.
- **"A member gets 401 on this API, and the write tool isn't even offered unless you asked to book."**
- Show a trace with its limits: at most 4 tool calls, 60 seconds and 8,000 tokens.

## 3. Demo: re-indexing and a failing job (2:30–3:45)
- Upload a v2 of a policy and approve it: the API returns **202** with a job. Show it going queued → succeeded.
- **"Now a worker whose embedder is unreachable."** The job is retried, then fails after 3 of 3 attempts; the version stays pending and the old edition stays live. With a healthy worker it succeeds.
- Ask the assistant: the citation names `@v2`.

## 4. Demo: the Audit page and monitoring (3:45–4:30)
- Walk the sections: agent runs, approval decisions, retrieval sources, jobs (the failed 3/3), model versions, and drift (PSI).
- **"Ids, codes and versions only: a test checks that no message or document text leaks here."**

## 5. Code architecture (4:30–5:30)
- Open the diagram in `ARCHITECTURE.md`. Then:
  - `agent/registry.py`: `run_tool` (authorisation, validation, deadline, output cap, audit);
  - `agent/runner.py`: the state machine;
  - `agent/mcp_server.py`: the same registry over stdio;
  - `assistant/jobs.py`: the worker;
  - `monitoring/drift.py`: PSI.
- **"One tool layer for the agent and MCP, so security lives in one place."**

## 6. Actual prompts and refinements (5:30–7:00)
- Show the agent's system prompt in `runner.py`: one JSON decision per turn, tool results are data, and "first call check_availability".
- **Refinement 1 (Step 8 round 1):** the model got dates wrong (11 of 20 tasks had bad arguments). Fix: the **server** resolves "next Tuesday" and sends typed schemas.
- **Refinement 2 (round 2):** typed schemas made the 3B model **invent** prediction inputs. Fix: a server-side input check. **Step 13: 0 invented estimates in 12 runs.**
- **What didn't work, said plainly:** hybrid search didn't beat the champion (A6 ◐), and the injected passage was never retrieved in any real run (C8 ◐).

## 7. Context management (7:00–7:30)
- Signed history in browser memory only; the last 3 turns within 600 tokens; 12 turns or 20,000 tokens per conversation; the token split recorded with every answer.

## 8. Blast-radius controls (7:30–8:15)
- Writes are proposals only, with a human confirm plus an idempotency key, and limits of 3 open and 6 per 10 minutes.
- MCP: read-only, 8-hour hashed tokens, 30 calls per minute. Show `THREATS.md`.
- Jobs retry transient failures only, and repeats are harmless.

## 9. Debugging and verification (8:15–9:00)
- **"The real-worker test caught a bug that the fake mode hid: the test settings were forcing the normal embedder, so failures were never injected."**
- **"Rules and frozen sets were committed before every run; the git history proves the order."**
- CI is path-filtered, with a Redis service. The Step 13 gate passed. Show the PR.
- **"Thanks: the study guide and full results are linked in the PR."**

## Cue list (one word per line)

Intro
Suggests
Book
Card
Decline
Confirm
Idempotency
Member
Limits
Upload
Job
Failure
Retry
Edition
Audit
Drift
Diagram
Registry
Runner
MCP
Worker
Prompt
Dates
Invented
Honest
History
Budget
Proposals
Tokens
Threats
Bug
Order
CI
Thanks
