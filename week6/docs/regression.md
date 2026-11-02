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
