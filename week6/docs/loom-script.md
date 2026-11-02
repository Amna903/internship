# Loom script: Week 6 (about 8 minutes)

This walkthrough covers the capstone requirements: working application, architecture, AI controls, context and blast-radius controls, debugging and verification. It uses synthetic data only; no output is medical advice.

Before recording:

- Run `make up` (and have Ollama running) or `make prod` for the HTTPS section.
- Open the app, `/admin/audit`, `/admin/agent`, `/admin/assistant`, the PR, and `docs/REQUIREMENTS.md`.
- Keep `docs/ARCHITECTURE.md`, `docs/EVALUATION.md`, `docs/SECURITY.md` and `docs/LOADTEST.md` ready.

## 1. Intro and reproducible stack (0:00–0:45)

**"Week 6 packages the earlier synthetic HealthProfile prototype into a reproducible local stack. One `make up` starts the frontend, Django API, PostgreSQL, Redis and Celery worker. A fresh clone smoke test passed 6 of 6."**

- Show the README quick start and `/ready/`.
- Mention that host Ollama is the Mac default; the container profile is optional.

## 2. End-to-end flow (0:45–2:30)

- Create a member, complete the profile, then sign in as admin.
- Show a prediction and its disclaimer, then the clusters visualization.
- Ask the assistant a policy question and point out its citation.
- On Agent, request a fictional booking. Show the typed trace and server-built proposal card.
- Confirm it, then show the booking and audit trail.

**"The final browser demo covers signup through approval and audit; it passed 8 of 8 checks."**

## 3. Architecture and AI safety (2:30–3:45)

- Open `ARCHITECTURE.md`.
- Explain: the browser talks to Next.js; Next.js proxies to Django; Django owns permissions, validation and audit; Celery performs queued indexing.
- Show `agent/runner.py` and `agent/registry.py`.

**"The model suggests a typed tool call. The server validates it, authorizes it and executes it. A write is only a proposal until a human confirms it."**

- Mention signed history is browser-held, bounded and never logged; server checks protect the model rather than trusting prompts.

## 4. Operations and privacy (3:45–4:35)

- Show the Operations and Audit sections.
- Explain request IDs, route latency/error metrics and token totals.

**"We log the route pattern and timing, never question text, answer text, password, email or request body."**

## 5. Resilience and debugging (4:35–5:35)

- Open `docs/regression.md` and show the 10/10 resilience rehearsal.
- Explain LLM, database, vector-store and worker outages return controlled errors and remain visible in operations.

**"The first database-outage rehearsal returned a 500 because session middleware read the database after the error handler. The full-stack rehearsal found that; a regression test now prevents it."**

## 6. Evaluation, performance and security (5:35–7:10)

- Show `EVALUATION.md`: reproducible release, clustering, 23 RAG questions and 31 frozen agent cases; red-team gate 11/11.
- Show `SECURITY.md`: authorization matrix, secret scan and high-risk regression group.
- Show `LOADTEST.md`.

**"We tried one worker-count optimization. p95 worsened from 27 to 51 milliseconds, so we reverted it. The load test is complete, but there is no claimed performance improvement."**

- State the other honest gap: tool-output injection was tested offline, but not demonstrated end to end because the model did not retrieve the injected passage.

## 7. Verification and close (7:10–8:00)

- Show PR #3 and its latest Actions run.
- Show the requirement checklist and study guide.

**"Rules were written before results, frozen cases were not tuned on, and the PR records both the passing evidence and the remaining limits. The release tag is created only after the latest CI run is green."**

## Cue list

Stack
Ready
Profile
Prediction
Clusters
Citation
Proposal
Confirm
Audit
Diagram
Server
History
Logs
Privacy
Outage
Bug
Evaluation
Security
Load
Honesty
CI
Close
