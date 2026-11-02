# Week 6 requirement → evidence checklist

Source: **"WEEK 6 | Production-Ready AI/ML Platform and Final Capstone"** in *Elevate Engine Weeks 4–6*. Each row is one line of that brief, worded as in the brief and split so none can be ticked half-done. Week 5's finished checklist is in [REQUIREMENTS-week5.md](REQUIREMENTS-week5.md).

Status: ☐ not started · ◐ in progress · ☑ done and evidenced. The **Me** column is the date the user re-ran the check, left blank until then.

## Decisions (Step 0, approved by the user on 2026-11-02; then built without per-step review)

- **Git:** a `week6/` folder copied from `week5/`, on a `week6` branch made from `week5`. The PR targets `week5` (the reviewer sees only Week 6's changes) until the earlier PRs merge.
- **Deployment:** a fully reproducible deployment procedure: Docker Compose with a Caddy reverse proxy for automatic HTTPS, a prod-like local run, and rollback and backup steps. No hosted free tier, since it can't run Ollama and would break the "no data leaves the machine" rule.
- **Vector store:** embeddings stay in PostgreSQL. "Vector store unavailable" is shown as the embedding model being unavailable.
- **LLM:** **Ollama on the host machine by default on a Mac** (the user's addition), with an optional `ollama` container (a Compose profile).
- **Load testing:** Locust.
- **Agent tests:** reuse the Week 5 frozen agent red-team set and the Step 13 cases (more than 10), plus a few new workflow cases marked `author: assistant`.
- **The user's additions:**
  1. Check that a **fresh clone in a new folder starts with `make up` from the README alone**.
  2. **Docker build jobs run in CI only on PRs or manual runs**, to save minutes.
  3. Host Ollama is the default on a Mac; the container is optional.
- **Rules carried over:** rules and frozen sets committed before results; tuning on dev only; champion/challenger; no rule changes after seeing results; CI green before the next step; one push per step; honest reporting; a log of decisions made without review (below).
- **Disk safety (after the 2026-11-02 incident, when a 40 GB Colima disk filled the Mac):** the Docker VM disk is capped at 15 GB, and free space is checked before every image build.

- **Step 1 rules (committed before any Step 1 code):**
  1. **One command:** `make up`, run from `week6/`. It creates `backend/.env` with generated secrets if missing (`scripts/init_env.py`, standard-library Python only), then runs `docker compose up -d --build` and waits for `/ready`. `make down`, `make logs`, `make seed`, `make test` and `make clean` (which removes volumes, after a prompt) are also provided.
  2. **Services:**
     - `db` (postgres:16, named volume);
     - `redis` (redis:7);
     - `backend` (Django under gunicorn; on start: migrate, then `seed_demo`, then `load_policies`);
     - `worker` (Celery, same image);
     - `frontend` (Next.js production build, proxying `/api` to `backend`).

     Optional profiles: `ollama` (an Ollama container) and `prod` (Caddy for HTTPS, Step 3). Images pin exact versions. Every service has a healthcheck, and dependencies wait for health.
  3. **The LLM defaults to the host's Ollama** (`http://host.docker.internal:11434`), as the user chose for the Mac. `make up OLLAMA=container` uses the container. If Ollama isn't reachable, the stack still starts: loading the policies is retried by `make seed`, and the assistant answers "unavailable" calmly.
  4. **Secrets come only from `backend/.env`** (git-ignored, never baked into images). `.env.example` documents every variable. Containers run as a non-root user. Only the frontend (3000) and, optionally, the backend (8000) are published, both on 127.0.0.1.
  5. **Seed data is synthetic only:** the demo admin and members (`seed_demo`) and the frozen fictional policies.
  6. **Acceptance (the user's addition):** a **fresh `git clone` in a new folder** runs `make up` from the README alone. Admin login, a prediction, the clusters page, a cited assistant answer and an agent run all work, checked in a browser and recorded in `docs/regression.md`.
  7. **Disk safety:** check free space before building; images are slim (python:3.14-slim, node:20-alpine), and `.dockerignore` keeps out venvs, `node_modules`, databases and `.env`.

- **Step 2 rules (committed before any Step 2 code):**
  1. **Separate settings modules:** `config/settings.py` (the shared base, driven by environment variables), `config/settings_dev.py` (DEBUG on, localhost defaults) and `config/settings_prod.py`. **Prod refuses to start** unless:
     - DEBUG is off and cookies are secure;
     - SSL redirect is on and requests come through the TLS proxy (`X-Forwarded-Proto`);
     - HSTS is set (default 1 day, to be raised once HTTPS is verified);
     - secrets are real (at least 32 characters, the two keys differ);
     - hosts and origins are explicit (no `*`, no localhost);
     - API docs are off unless `ENABLE_API_DOCS` is set explicitly.
  2. **CORS: same-origin only.** The browser talks only to the Next.js origin, which proxies `/api`. No CORS headers are sent, so a foreign origin gets no `Access-Control-Allow-Origin`. A test checks this. No CORS package is added.
  3. **Cookies and CSRF:** HttpOnly auth cookies and SameSite=Lax (already in place). Prod requires the Secure flag. CSRF is enforced on every unsafe method, and trusted origins are explicit. Tests run these under the prod module.
  4. **Secrets:** only from the environment (a 600-mode `.env` locally, the host's secret store or env file in production); never in images, the repo or logs. The rotation procedure is documented in the deployment guide (Step 11). `.env.example` has placeholders only.
  5. **Tests:** prod-settings refusals (each invariant), security headers (HSTS, nosniff, frame deny, referrer), no CORS for a foreign origin, CSRF enforced, secure cookie flags under prod settings.

- **Step 3 rules (committed before any Step 3 code):**
  1. **Procedure:** `docker-compose.prod.yml` layered over the base file, started with `make prod`:
     - a **Caddy** reverse proxy is the only public entry (ports 80 and 443). It sends `/api/*`, `/health/` and `/ready/` to the backend and everything else to the frontend, and passes `X-Forwarded-Proto`.
     - the backend runs `config.settings_prod`: DEBUG off, secure cookies, SSL redirect (except `/health/` and `/ready/`, for internal probes), HSTS, API docs off;
     - neither the backend nor the frontend publishes a port.
  2. **TLS:** with a real domain, `SITE_ADDRESS=clinic.example.org` and `ACME_EMAIL=…` give automatic Let's Encrypt certificates. The local rehearsal uses `healthprofile.localhost` with Caddy's **internal CA** (`tls internal`), so HTTPS is real but the certificate is self-signed for the demo.
  3. **Rehearsal acceptance:**
     - `make prod` starts;
     - `https://healthprofile.localhost/ready/` is ready;
     - plain HTTP redirects to HTTPS;
     - responses carry HSTS, and cookies are `Secure; HttpOnly; SameSite=Lax`;
     - admin sign-in, a prediction and a cited answer work in a browser over HTTPS;
     - `/api/docs/` is 404.
  4. **No hosted deployment** (approved decision). Rollback (`make rollback TAG=…` from tagged images) and backup/restore (`make backup` / `make restore`: `pg_dump` to `backups/`, which is git-ignored) are scripted and rehearsed once. Costs and hosting choices are documented in the Step 11 guide.
  5. **Allowed fix to my Step 2 rule (before any Step 3 run):** the prod origin check matched "localhost" as a substring, which would refuse `https://healthprofile.localhost`. It now compares hostnames exactly, the same as the hosts check: `localhost` itself is still refused, an explicit `*.localhost` name is allowed.

## Decisions made without review

| Step | Decision | Options considered | Reason |
|---|---|---|---|
| 3 | Python's resolver can't resolve `*.localhost`, so the HTTPS smoke test resolves it through Chromium (`--host-resolver-rules`) | Edit /etc/hosts (needs sudo) | No system change is needed. |
| 1 | Local `make up` runs with **DEBUG on over HTTP** (bound to 127.0.0.1); production is the HTTPS `prod` profile with DEBUG off | DEBUG off with secure cookies on localhost; relax the cookie check | The settings rightly refuse insecure cookies with DEBUG off. Secure cookies on http://localhost work in Chrome but not Safari, and relaxing the check would weaken production. |

## Integration and containers

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| I1 | Integrate Weeks 1–5 into one application (auth and profile CRUD, prediction, segmentation, LLM assistant, advanced RAG, approval-gated agent) | 0, 12 | ☐ | | | | |
| I2 | Containerize frontend, backend, database, worker (and optional vector store) using Docker Compose | 1 | ☑ | `docker-compose.yml`: db, redis, backend (gunicorn), worker (Celery), frontend; optional `ollama` profile; healthchecks | Fresh-clone `make up`, [regression.md](regression.md) | | |
| I3 | Environment-variable examples | 1 | ☑ | `backend/.env.example` (every variable), generated by `scripts/init_env.py` | Fresh clone | | |
| I4 | Seed scripts | 1 | ☑ | The entrypoint runs `migrate`, `seed_demo` and `load_policies`; `make seed` re-runs them | Fresh clone (6 policies loaded) | | |
| I5 | One-command local startup | 1 | ☑ | `make up` (Makefile) waits for `/ready/` | Fresh clone, smoke test 6/6 | | |

## Deployment and production settings

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| P1 | Deploy frontend/backend where feasible (or a fully reproducible deployment procedure) | 3 | ☑ | Fully reproducible procedure: `docker-compose.prod.yml` + `deploy/Caddyfile`, `make prod`; with a real domain, set `SITE_HOST`/`TLS_MODE`/`ACME_EMAIL` for Let's Encrypt. No hosted deployment (approved decision: Ollama must stay local) | HTTPS rehearsal, smoke 6/6 ([regression.md](regression.md)) | | |
| P2 | HTTPS | 2, 3 | ☑ | Caddy terminates TLS (internal CA locally, ACME for a real domain); HTTP→HTTPS 308; HSTS; Django SSL redirect behind the proxy | [regression.md](regression.md), `tests/test_prod_settings.py` | | |
| P3 | CORS | 2 | ☑ | Same-origin only: the browser talks to the Next.js origin, which proxies `/api`; no CORS headers are sent | `tests/test_prod_settings.py` (`test_no_cors_for_a_foreign_origin`) | | |
| P4 | Secure session cookies | 2 | ☑ | HttpOnly and SameSite=Lax auth cookies; Secure is required by `config/settings_prod.py` | `tests/test_prod_settings.py` | | |
| P5 | CSRF protection | 2 | ☑ | Django CSRF on every unsafe method; explicit https trusted origins in prod | `tests/test_prod_settings.py` (`test_csrf_is_enforced…`) | | |
| P6 | Secret management | 2 | ◐ | Environment only (`.env` mode 600, never in images or the repo); prod rejects weak or shared keys; rotation is documented in Step 11 | `tests/test_prod_settings.py` | | |
| P7 | Separate development/production settings | 2 | ☑ | `config/settings_dev.py` and `config/settings_prod.py` over the env-driven base; prod refuses to start with any unsafe value | `tests/test_prod_settings.py` (10 refusals) | | |

## CI

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| CI1 | Lint/format | 5 | ☐ | | | | |
| CI2 | Unit tests | 5 | ☐ | | | | |
| CI3 | API integration tests | 5 | ☐ | | | | |
| CI4 | Model-pipeline smoke tests | 5 | ☐ | | | | |
| CI5 | RAG regression tests | 5 | ☐ | | | | |
| CI6 | Frontend build checks | 5 | ☐ | | | | |
| CI7 | Publish a passing run | 5 | ☐ | | | | |

## APIs and artifacts

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| E1 | Version model artifacts and preprocessing | 4 | ☐ | | | | |
| E2 | Expose /health and /ready | 4 | ☐ | | | | |
| E3 | Expose /api/v1/predict, /api/v1/clusters and assistant endpoints | 4 | ☐ | | | | |
| E4 | OpenAPI documentation with representative requests/responses | 4 | ☐ | | | | |

## Evaluation

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| V1 | Reproducible evaluation suite: supervised metrics | 9 | ☐ | | | | |
| V2 | Unsupervised clustering quality | 9 | ☐ | | | | |
| V3 | 20-question RAG benchmark | 9 | ☐ | | | | |
| V4 | At least 10 agent safety/workflow tests | 9 | ☐ | | | | |
| V5 | Document baseline versus final results | 9 | ☐ | | | | |

## Observability

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| O1 | Structured logs | 6 | ☐ | | | | |
| O2 | Correlation/request IDs | 6 | ☐ | | | | |
| O3 | API latency/error metrics | 6 | ☐ | | | | |
| O4 | Token usage and cost estimates | 6 | ☐ | | | | |
| O5 | Admin operational dashboard or documented monitoring view | 6 | ☐ | | | | |

## Load testing

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| L1 | Load test at least two core endpoints with a documented small synthetic workload | 8 | ☐ | | | | |
| L2 | Report p50/p95 latency, throughput, errors | 8 | ☐ | | | | |
| L3 | One measured optimization | 8 | ☐ | | | | |

## Resilience

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| R1 | LLM timeout/provider failure → safe, observable response | 7 | ☐ | | | | |
| R2 | Unavailable vector store → safe, observable response | 7 | ☐ | | | | |
| R3 | Database outage → safe, observable response | 7 | ☐ | | | | |
| R4 | Background worker failure → safe, observable response | 7 | ☐ | | | | |

## Security

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| S1 | Security checklist: authorization, input validation, rate limiting, upload restrictions, prompt injection, agent write approvals, secrets | 10 | ☐ | | | | |
| S2 | Automate high-risk regression tests | 10 | ☐ | | | | |

## Documentation

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| D1 | Final architecture diagram | 11 | ☐ | | | | |
| D2 | Data-flow diagram | 11 | ☐ | | | | |
| D3 | Model card for the supervised model | 11 | ☐ | | | | |
| D4 | Clustering limitations note | 11 | ☐ | | | | |
| D5 | RAG evaluation report | 11 | ☐ | | | | |
| D6 | Deployment/rollback/backup guide | 11 | ☐ | | | | |

## Demo, constraints and acceptance

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| X1 | Live end-to-end demo: signup → profile completion → prediction → cluster visualization → cited LLM answer → agent tool call → human approval → audit trail | 12 | ☐ | | | | |
| X2 | Synthetic data only; never present ML/LLM output as diagnosis or medical advice | all | ☐ | | | | |
| X3 | Enforce user ownership, admin permissions, tool-level authorization; protect secrets; logs without sensitive payloads | 10 | ☐ | | | | |
| X4 | Document reproducible builds, dependency versions, known limitations, model/data provenance, deployment costs, rollback steps | 11 | ☐ | | | | |
| X5 | A reviewer can start the full stack from README and run all core flows with sample data (user's addition: verified from a fresh clone with `make up`) | 1, 13 | ◐ | Verified from a fresh clone with `make up` from the README alone (smoke test 6/6); re-checked at Step 13 | [regression.md](regression.md) | | |
| X6 | CI and automated tests pass; cross-user access, unauthorized agent writes and invalid inputs are rejected | 5, 10 | ☐ | | | | |
| X7 | Supervised/unsupervised evaluation, RAG/agent safety results, load-test measurements with at least one improvement | 8, 9 | ☐ | | | | |
| X8 | Deployed application or fully reproducible deployment procedure, failure recovery and observability evidence | 3, 6, 7 | ☐ | | | | |

## Submission

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| F1 | Repository with final release tag, documented commit history and deployment configuration | 13 | ☐ | | | | |
| F2 | README with links, setup, tests, architecture, API docs, screenshots, dataset/model limitations and known issues | 13 | ☐ | | | | |
| F3 | 5–10 minute Loom (script and cue list prepared; the user records it) | 13 | ☐ | | | | |
| F4 | Share links in the team channel (the user does this) | 13 | ☐ | | | | |
| F5 | Keep all previous features working; regression-test evidence | 0, 13 | ◐ | Baseline: [regression.md](regression.md) (1543 passed, 2 skipped; frontend 62, build OK) | CI full regression on the PR | | |
| F6 | Study guide (the user's standing request) | 13 | ☐ | | | | |
