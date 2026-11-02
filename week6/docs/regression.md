# Week 6 regression baseline (Step 0, 2026-11-02)

`week6/` is a copy of `week5/`'s tracked files on a fresh `week6` branch made from `week5`, with fresh local secrets (`scripts/init_env.py`).

| Check | Result |
|---|---|
| Backend `pytest` (SQLite) | 1543 passed, 2 skipped (the PostgreSQL-only test, and the real-worker test, which needs Redis) after fixing 2 doc links broken by renaming the Week 5 docs |
| Migrations complete | `makemigrations --check`: no changes |
| Frontend | typecheck OK, 62 tests passed, build OK |
| CI | full Week 1–6 regression on the PR (opened against `week5`) |

The Week 5 CI's final gate job had failed only because GitHub Actions minutes ran out. The repository is now public (free minutes), and the gate passed on re-run.

## Step 1: fresh-clone check (the user's addition), 2026-11-02

From a new folder: `git clone https://github.com/Amna903/internship.git`, `git checkout week6`, `cd week6`, `make up`, following only the README. Docker ran on Colima with a 15 GB disk; Ollama ran on the host.
- `make up` generated `backend/.env`, built and started all 5 services, seeded the data, loaded 6 policies through the host Ollama, and `/ready/` returned ready (database, broker, model and LLM all ok).
- The browser smoke test (`e2e/run_stack_smoke.py`) passed **6 of 6**: `/ready/`, admin sign-in, a prediction with its disclaimer, the clusters PCA plot, a cited assistant answer, and an agent run (done, 2 tool calls).

## Step 3: production rehearsal over HTTPS, 2026-11-02

`make prod` (base compose + `docker-compose.prod.yml`, Caddy with its internal CA at `https://healthprofile.localhost`):
- all 6 services healthy; `/ready/` ready;
- `http://` gives a 308 redirect to `https://`;
- HSTS is sent once (`max-age=86400`) and `X-Frame-Options: DENY`;
- `/api/docs/` returns 404;
- the CSRF cookie is `Secure; SameSite=Lax`;
- the browser smoke test over HTTPS passed **6 of 6** (sign-in, prediction, clusters, cited answer, agent run).

Operations rehearsal:
- `make backup` wrote a 128 KB `pg_dump`;
- `make restore` brought it back (7 users before and after; a deleted table was restored);
- `make tag TAG=rehearsal` then `make rollback TAG=rehearsal` restarted on the tagged images, and `/ready/` returned 200.

## Step 7: live resilience rehearsal (`e2e/resilience_rehearsal.py`, local Compose stack)

First run: 7/10. With the database stopped, the API returned **500**, because Django's session middleware re-read the session after the 503 was built. Fixed (`OutageSafeSessionMiddleware`, with a regression test). The other two failures were in the script (it read the header through the proxy, and re-uploaded duplicate content).

Final run: **10/10**:
- LLM unreachable → 503 `assistant_unavailable`;
- database stopped → 503 `service_unavailable` with `Retry-After: 30`, `/ready/` 503, recovery once the database is back;
- worker stopped → approval 202, job stays `queued` and the ops view counts it, worker back → `succeeded`.

Full suite: 1596 passed, 2 skipped.
