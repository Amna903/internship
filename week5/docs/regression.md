# Week 5 regression evidence

Week 5 must keep every Week 1–4 feature working. This file records the local runs. CI re-runs the
automated suites and `python -m ml.verify_release` on every push.

## Step 0 baseline (before any Week 5 feature code)

Run on 2026-11-01, macOS (Apple silicon), in `week5/` at commit `2f1b54a` (the copy of `week4/`), plus
the Step 0 checklist, README placeholder and CI change. No code differs from Week 4. The `week5/` setup
was fresh: a new venv, `npm ci`, a new `.env`, `migrate`, `seed_demo` and `load_policies`, and the
dataset regenerated from its seed (SHA-256 `f458e62a…`, the same as Weeks 3 and 4).

| Suite | Result |
|---|---|
| Backend `python -m pytest` (SQLite) | **763 passed, 1 skipped** (the PostgreSQL-only TRUNCATE test); pytest exit code 0 |
| Frontend `npm test` | **53 passed** |
| Frontend typecheck and `next build` | clean |
| `python -m ml.verify_release` | all levels pass; `no-show-1.0.0: reproduced` |
| `e2e/run_e2e.py` (Week 1) | **24/24** |
| `e2e/run_week2_e2e.py` (Week 2) | **33/33** |
| `e2e/run_audit_e2e.py` (Week 2 audit) | **15/15** |
| `e2e/run_week3_e2e.py` (Week 3) | **17/17** |
| `e2e/run_week4_e2e.py` (Week 4) | **23/23** |

The browser tests ran against the `week5/` production frontend build on port 3000 and the `week5/`
backend, with only one agent session running.

The backend count is 2 higher than Week 4's 761 only because the docs link test runs once per file in `docs/`, and `week5/docs/` has two more files (this one and the Week 5 `REQUIREMENTS.md`).
