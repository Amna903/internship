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

- **Step 4 rules (committed before any Step 4 code):**
  1. **The brief's paths:** `POST /api/v1/predict/` serves the same view as `/api/v1/predictions/no-show/` (both kept), `GET /api/v1/clusters/` already exists, and the assistant endpoints (`/api/v1/assistant/ask/`, documents, jobs) and agent endpoints are unchanged. `/health/` and `/ready/` (Step 1) are documented in OpenAPI.
  2. **Versioned artifacts:** the served model is `no-show-1.0.0`. Its **preprocessing is inside the same scikit-learn pipeline file**, so model and preprocessing are versioned and SHA-256-pinned together, and loading refuses a mismatch (Week 3). The model endpoint now also reports the preprocessing steps (read from the loaded pipeline, never stored separately) and the artifact's SHA-256. The artifact files aren't changed: `verify_release` still checks them byte for byte.
  3. **OpenAPI:** every core endpoint has a summary and **representative request and response examples** (predict, clusters, the model card, ask, agent run, confirm, jobs, monitoring, health, ready), generated by drf-spectacular. A test generates the schema, requires those examples, and fails on schema warnings for these views. `docs/API.md` links to `/api/docs/` (dev) and keeps the curl examples.

- **Step 5 rules (committed before any Step 5 code):**
  1. **Lint and format, Week 6 only:**
     - backend: **ruff** (`ruff check` with pyflakes, pycodestyle errors, import order and bugbear; `ruff format --check`, line length 120);
     - frontend: **ESLint** (`eslint-config-next`) and **Prettier** (`--check`).

     The existing code is formatted once in a **separate mechanical commit** (formatting only), verified by the full test suite before and after. Earlier weeks' folders are not touched.
  2. **Named test groups for Week 6** (one pytest run split by markers, so nothing runs twice):
     - unit and API integration tests (DRF test client, real database: SQLite and PostgreSQL legs);
     - **RAG regression** (the frozen retrieval, generation and conversation harnesses with the fake model, plus the frozen-set hash checks);
     - **model-pipeline smoke** (the ML tests, plus the existing ML reproducibility job that rebuilds the release byte for byte).

     Markers come from file names in `conftest.py`, and a test fails if any test file belongs to no group.
  3. **Frontend build check:** the existing typecheck, tests and `next build`, plus lint and format.
  4. **Docker job (the user's addition: only on PRs or manual runs):** builds both images and starts the stack with the fake LLM and embedder. It then runs API integration checks against the running containers: `/ready/`, admin sign-in plus CSRF, prediction, clusters, an assistant answer, and member access refused. It runs on `workflow_dispatch` and on `pull_request` events, but **only when container-related files changed** (Dockerfiles, compose, Makefile, requirements, package files, `deploy/`) or when the PR is opened, reopened or marked ready. Never on plain branch pushes.
  5. **Published run:** the PR's passing run is linked in the README and PR (CI7).

- **Step 6 rules (committed before any Step 6 code):**
  1. **Structured logs:** one JSON object per line on stdout (time, level, logger, message, `request_id`, plus fields). One access line per API request: method, route **pattern** (not the raw path), status, `duration_ms`, `user_id`. Never question text, answers, request bodies, query strings, emails or passwords; a test checks a request carrying a secret-looking body and question leaves no trace in the logs.
  2. **Request ids:** the existing `X-Request-ID` middleware sets a context variable, so every log line during a request (and the audit row) carries the same id. Celery tasks log the job id.
  3. **Latency and error metrics:** each API request (not `/health/` or `/ready/`) is stored as one `RequestSample` row (route pattern, method, status, ms, time; no user, no path values), pruned after 7 days. Reported per route: count, p50, p95, 4xx and 5xx rates over a chosen window. Stored in PostgreSQL so all gunicorn workers share it; the write overhead is measured in Step 8.
  4. **Tokens and cost:** `AnswerRecord` gains `prompt_tokens` and `output_tokens` (agent runs already store tokens). The ops view totals tokens per day for the assistant and the agent, with the local cost (0) and the existing **illustrative** hosted-equivalent price, labelled as illustrative.
  5. **Ops view:** admin-only `GET /api/v1/ops/?hours=` (1–168) and an **Operations** section on the admin page. Members get 403/401.

- **Step 7 rules (committed before any Step 7 code):** each failure gives a **safe JSON response** (the standard error envelope, no traceback or internal detail), a **JSON log line** with the request id and a stable `event` code, and shows up in the ops view (5xx rate, or the job counts). Each is proven by an automated test that injects the failure, and once by a live rehearsal on the Compose stack recorded in `docs/regression.md`.
  1. **LLM timeout or provider failure (R1):** keep the existing `504 assistant_timeout` and `503 assistant_unavailable`; add the log event `llm_timeout` or `llm_unavailable`. Live: point the stack at an unreachable Ollama URL.
  2. **Vector store unavailable (R2):** embeddings live in PostgreSQL. An embedder failure already gives `503 assistant_unavailable`; a database error while reading passages now gives `503 retrieval_unavailable` (log event `retrieval_unavailable`), not a 500.
  3. **Database outage (R3):** any `DatabaseError` reaching the API gives `503 service_unavailable` with `Retry-After: 30` (log event `database_unavailable`), never a 500 page; `/ready/` already returns 503. Metrics writes never break a request (Step 6). Live: stop the `db` container, call the API, start it again.
  4. **Worker failure (R4):** the broker being down already gives `503 queue_unavailable` with nothing changed. A **dead worker** with the broker up leaves jobs queued; the ops view now reports `jobs.queued_over_5_min`, and the job finishes once a worker returns (tasks are acknowledged late, so a crash mid-task is redelivered). Live: stop the `worker`, approve a document, see the stuck count, start the worker, see the job finish.

- **Step 8 rules (committed before any Step 8 code or measurement):**
  1. **Tool and target:** Locust (pinned in `loadtest/requirements.txt`, not in the app's requirements), headless, against the local Compose stack's backend on `127.0.0.1:8000` (gunicorn, 3 workers, PostgreSQL), signed in as the seeded admin.
  2. **Workload (synthetic, fixed):** 10 users, spawn rate 2/s, 60 s per run, no think time beyond 0.1–0.5 s. Tasks: `POST /api/v1/predict/` (weight 3, one fixed synthetic appointment) and `GET /api/v1/clusters/` (weight 1). For the test only, the two endpoints' rate limits are raised by an overlay (`loadtest/docker-compose.loadtest.yml`); the app's defaults don't change.
  3. **Reported:** p50, p95, requests per second and error count per endpoint, from Locust's CSV. Each configuration gets one 15 s warm-up and **3 measured runs**, and the median run is reported. All runs are kept in `loadtest/results/`.
  4. **One optimisation:** picked from the baseline profile (the slower endpoint's p95), changed once, and re-measured with the identical workload. It is kept only if the median p95 improves by at least 10% with no new errors; otherwise it is reverted and reported as a negative result.
  5. **Honesty:** numbers come from a laptop running Docker in a VM, with DEBUG on (the local profile), so they show **relative** change, not capacity. This is stated in the report.

- **Step 9 rules (committed before any Step 9 code or run):**
  1. **One command:** `make eval`, which runs `manage.py evaluate_suite`. It writes **only** to `backend/eval_suite/` (`results.json`, `report.md`); the committed Week 3–5 result files are never overwritten. A summary goes into `docs/EVALUATION.md`.
  2. **Supervised (V1):** `python -m ml.verify_release` must exit 0 (rebuilds the data, model and reports from scratch and compares). The reported metrics are the release's **already recorded** test metrics; the test set is **not** scored again (Week 3 rule: it is used once). Baseline: the Week 3 reference model recorded in `ml/reports/metrics.md`.
  3. **Clustering (V2):** silhouette by k, the planted-control recovery (ARI) and the real-data verdict, read from the committed results that `verify_release` has just reproduced.
  4. **RAG benchmark (V3):** the **frozen Week 5 retrieval set** (23 questions ≥ 20, file and SHA checked), in two parts:
     - retrieval with the shipped settings: hit@k, MRR and correct "no answer";
     - end to end with the real local model (`llama3.2:3b`), seeds 42, 43 and 44, majority of 3: right status and verified citations.
     Baseline: the Week 5 first measurement (`retrieval_baseline.json`, and the end-to-end mode in `generation_eval.json`).
  5. **Agent (V4):** the frozen Week 5 agent sets: 20 workflow tasks, the recovery cases and 11 red-team cases (31 ≥ 10), seeds 42, 43 and 44. The safety gate must pass: any red-team failure stops Week 6 (a stop reason). Baseline: Week 5 round 1 (`agent_eval.json`). The fresh holdout is **not** re-run (it was used once in Week 5). **No new agent cases**: the 31 frozen cases exceed the bar, and Week 6's new safety behaviour (outages, refusals) is covered by automated tests (logged under decisions made without review).
  6. **Nothing is tuned in Step 9.** Results are reported as measured, including any drop from Week 5; a drop is explained, not fixed, unless it is a safety failure.

- **Step 10 rules (committed before any Step 10 code):**
  1. **Checklist:** `docs/SECURITY.md` has one row per brief item: authorization, input validation, rate limiting, upload restrictions, prompt injection, agent write approvals, secrets, plus headers/CSRF and logging privacy. Each row names the control, the code, and the automated test that proves it. A control without a test is listed as a gap, not ticked.
  2. **New automated checks (S2):**
     - an **authorization matrix** built from the URL configuration: every `/api/` route is called anonymously and as a member, and only an explicit allow-list (public auth endpoints, the member's own resources) may answer anything but 401/403. A new route that forgets its permission fails CI;
     - a **secret scan** of the git-tracked files: no `.env`, no private keys, no strings shaped like real keys or tokens, and the seed passwords are not in the repo;
     - a **`security` marker** grouping the high-risk tests (authorization, uploads, prompt injection and red-team, write approvals, MCP tokens, prod settings, logging privacy), run as its own named CI step so a failure is visible by name.
  3. **Any failing security check is a stop reason** (a safety gate): it is fixed before anything else, or the user is told.

## Decisions made without review

| Step | Decision | Options considered | Reason |
|---|---|---|---|
| 9 | **No new agent cases** (the approved plan said "plus a few new cases marked author: assistant") | Write 3 new cases | The 31 frozen cases already exceed the bar of 10. New cases written now, after Week 5's results were seen, would be weaker evidence than the frozen ones. Week 6's new behaviour is covered by tests. |
| 7 | Django's `SessionMiddleware` is replaced by a **subclass** that keeps the 503 when the session can't be read on the way out; found by the live rehearsal (the first run returned 500 with the database down) | Catch it in a custom 500 handler | The subclass changes nothing when the database is up, and the fix is tested. |
| 7 | `Retry-After` is checked on the backend directly: the Next.js proxy does not pass it on to the browser | Patch the proxy | The 503 code and message still reach the browser; the header is a hint for API clients, which call the backend. |
| 4 | Examples are added by **one post-processing hook**, not by rewriting the Week 4/5 views; drf-spectacular's existing "unable to guess serializer" notices (10 Week 4/5 APIViews) are left as they are | Convert those views to serializers | That would be a risky change to working, tested views for documentation only. The hook documents their bodies and responses, and a test checks it. |
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
| CI1 | Lint/format | 5 | ☑ | `backend/ruff.toml`, `frontend/eslint.config.mjs`, `.prettierrc.json`; CI step "Lint and format" | ruff check/format, ESLint, Prettier check | | |
| CI2 | Unit tests | 5 | ☑ | CI step "Unit and API integration tests" (`-m "not rag and not ml_pipeline"`) | 694 passed (sqlite and postgres) | | |
| CI3 | API integration tests | 5 | ☑ | `e2e/api_integration.py` in the `docker stack` job (PRs and manual runs only) | 10/10 against running containers | | |
| CI4 | Model-pipeline smoke tests | 5 | ☑ | CI step "Model-pipeline smoke tests" (`-m ml_pipeline`) | 274 passed | | |
| CI5 | RAG regression tests | 5 | ☑ | CI step "RAG regression tests" (`-m rag`) | 605 passed; `tests/test_ci_groups.py` | | |
| CI6 | Frontend build checks | 5 | ☑ | `frontend` job: lint, format check, typecheck, vitest, `next build` | 62 vitest | | |
| CI7 | Publish a passing run | 5 | ☑ | All 7 jobs green, including the Docker job | [run 41479939168](https://github.com/AmanAtiq/healthprofile/actions/runs/41479939168) | | |

## APIs and artifacts

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| E1 | Version model artifacts and preprocessing | 4 | ☑ | `no-show-1.0.0`: model and preprocessing in one scikit-learn pipeline file, SHA-256 pinned (loading refuses a mismatch); `verify_release` rebuilds it byte for byte; the model card reports the preprocessing steps | `tests/test_openapi.py` (`…preprocessing_from_the_versioned_artifact`), CI ML reproducibility | | |
| E2 | Expose /health and /ready | 4 | ☑ | `config/health.py`: `/health/` and `/ready/` | `tests/test_health.py` | | |
| E3 | Expose /api/v1/predict, /api/v1/clusters and assistant endpoints | 4 | ☑ | `/api/v1/predict/` (alias), `/api/v1/clusters/`, `/api/v1/assistant/*`, `/api/v1/agent/*` | `tests/test_openapi.py` (`test_predict_alias…`) | | |
| E4 | OpenAPI documentation with representative requests/responses | 4 | ☑ | drf-spectacular with examples for 10 core operations plus the probes (`config/openapi.py`); `/api/docs/` in dev | `tests/test_openapi.py` | | |

## Evaluation

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| V1 | Reproducible evaluation suite: supervised metrics | 9 | ☑ | `make eval` → `evaluate_suite`: `ml.verify_release` (reproduced) and the recorded test metrics | [EVALUATION.md](EVALUATION.md): PR-AUC 0.280 vs floor 0.164 | | |
| V2 | Unsupervised clustering quality | 9 | ☑ | Silhouette, shuffled baseline, planted-control ARI | Real 0.169 ≈ shuffled 0.168 (no structure); control ARI 0.52 | | |
| V3 | 20-question RAG benchmark | 9 | ☑ | 23 frozen questions: retrieval and end to end, 3 seeds | Recall@3 100%, MRR 0.97; end to end identical to Week 5 | | |
| V4 | At least 10 agent safety/workflow tests | 9 | ☑ | 31 frozen cases (20 tasks, 11 red-team) plus recovery, 3 seeds | Success 14/20; red-team gate 11/11 passed | | |
| V5 | Document baseline versus final results | 9 | ☑ | `eval_suite/report.md` with Week 5 baseline and final columns | [EVALUATION.md](EVALUATION.md) | | |

## Observability

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| O1 | Structured logs | 6 | ☑ | `config/logging.py` JSON formatter; one access line per API request (route pattern, status, ms, user id) | `tests/test_ops.py::TestLogs` (no question, card number, query string or path value leaks) | | |
| O2 | Correlation/request IDs | 6 | ☑ | `config/middleware.py` sets the request id as logging context; echoed in `X-Request-ID` and audit rows; job ids on worker logs | `test_every_line_during_an_answer_shares_the_id...` | | |
| O3 | API latency/error metrics | 6 | ☑ | `monitoring.RequestSample` + `monitoring/metrics.py`: per-route count, p50, p95, 4xx/5xx rates | `TestMetrics` (percentiles, probes excluded, DB error never breaks a request) | | |
| O4 | Token usage and cost estimates | 6 | ☑ | `AnswerRecord.prompt_tokens/output_tokens`; daily totals with local cost 0 and illustrative hosted equivalent | `TestTokens` | | |
| O5 | Admin operational dashboard or documented monitoring view | 6 | ☑ | `GET /api/v1/ops/?hours=` (admin only) and the Operations tables on `/admin/audit` | `TestOpsView` | | |

## Load testing

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| L1 | Load test at least two core endpoints with a documented small synthetic workload | 8 | ☑ | `loadtest/locustfile.py`, `run.sh`, overlay; predict and clusters, 10 users, 3×60 s | [LOADTEST.md](LOADTEST.md), `loadtest/results/` | | |
| L2 | Report p50/p95 latency, throughput, errors | 8 | ☑ | `loadtest/summarize.py` (median of 3) | Baseline: predict p50 15 / p95 27 ms, 22.4 req/s; clusters 9 / 16 ms, 7.9 req/s; 0 errors | | |
| L3 | One measured optimization | 8 | ◐ | One change measured: gunicorn 3 → 9 workers | **Negative result:** p95 27 → 51 ms; reverted per the committed rule; no second attempt (see LOADTEST.md) | | |

## Resilience

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| R1 | LLM timeout/provider failure → safe, observable response | 7 | ☑ | Existing `504 assistant_timeout` / `503 assistant_unavailable`; log events `llm_timeout`, `llm_unavailable` | `tests/test_resilience.py::TestLLM`; live: unreachable Ollama URL → 503 | | |
| R2 | Unavailable vector store → safe, observable response | 7 | ☑ | Embedder failure → `503 assistant_unavailable`; passage-store `DatabaseError` → `503 retrieval_unavailable` (model never called) | `TestVectorStore` | | |
| R3 | Database outage → safe, observable response | 7 | ☑ | `config/exceptions.py`: `DatabaseError` → `503 service_unavailable` + `Retry-After: 30`; `OutageSafeSessionMiddleware`; 3 s connect timeout | `TestDatabase`, session-outage test; live: `db` stopped → 503, `/ready/` 503, recovery | | |
| R4 | Background worker failure → safe, observable response | 7 | ☑ | Broker down → `503 queue_unavailable`; ops view `jobs.queued_over_5_min`; late acks redeliver | `TestWorker`; live: worker stopped → job queued and counted → worker back → succeeded | | |

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
