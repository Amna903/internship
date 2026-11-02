# Week 4 regression evidence

Re-run on 2026-11-01, on the `week4` branch after Step 13 (commit `2a380f8`) plus the Step 14 docs.
Claude Code (the AI agent) ran everything below locally; CI re-runs the automated suites on every push.

| Suite | What it covers | Result |
|---|---|---|
| Backend `pytest` (SQLite) | Weeks 1–4: auth, profiles, admin, audit, predictions, ML pipeline and reports, clustering, assistant, evaluation scoring, docs | **761 passed, 1 skipped** (the skip is a PostgreSQL-only test); pytest exit code 0 |
| Frontend `npm test` | Weeks 1–4 unit and contract tests | **53 passed** |
| Frontend typecheck and `next build` | Every page, including the three Week 4 tabs | clean |
| `python -m ml.verify_release` | v1.0.0 rebuilt byte for byte, reports regenerated | passes in CI on every push |
| `e2e/run_e2e.py` (Week 1) | both roles through the Next.js proxy: member sign-up and profile, admin console, deactivate/reactivate, logout, mobile | **24/24** |
| `e2e/run_week2_e2e.py` (Week 2) | professional search (frontend only): combined filters, sorting, debounced search, URL as state, reset, empty state | **33/33** |
| `e2e/run_audit_e2e.py` (Week 2) | profile completion and audit events | **15/15** |
| `e2e/run_week3_e2e.py` (Week 3) | no-show estimate page, validation, errors, member refused | **17/17** |
| `e2e/run_week4_e2e.py` (Week 4) | three tabs, PCA plot, method table, the assistant's four example questions, 502 message, phone width, logged-out redirect | **23/23** |

The browser runs used the production frontend build on port 3000, the backend with a relaxed login limit
(`THROTTLE_LOGIN=1000/min`, as the Week 2 README describes), and the local model through Ollama for Week 4.

**Changed by Week 4 and re-checked:**
- The admin header link changed from "No-show estimate" to "ML tools". The Week 3 browser test was
  updated to match, and it still passes.
- Both the Week 3 and Week 4 browser tests accept `E2E_BASE`, defaulting to port 3000.

**Not re-run here:** the PostgreSQL 16 backend suite runs in CI only.
