# Week 6 regression baseline (Step 0, 2026-11-02)

`week6/` is a copy of `week5/`'s tracked files on a fresh `week6` branch made from `week5`, with fresh local secrets (`scripts/init_env.py`).

| Check | Result |
|---|---|
| Backend `pytest` (SQLite) | 1543 passed, 2 skipped (the PostgreSQL-only test, and the real-worker test, which needs Redis) after fixing 2 doc links broken by renaming the Week 5 docs |
| Migrations complete | `makemigrations --check`: no changes |
| Frontend | typecheck OK, 62 tests passed, build OK |
| CI | full Week 1–6 regression on the PR (opened against `week5`) |

The Week 5 CI's final gate job had failed only because GitHub Actions minutes ran out. The repository is now public (free minutes), and the gate passed on re-run.
