# Week 2: review fixes and evidence

This file covers two rounds of review:
- **Round A:** the Week 1 review points, applied to Week 2 (which started as a copy of the Week 1 code).
- **Round B:** the Week 2 review: audit reliability, the authorisation lifecycle, query-plan evidence, and CI.

For each fix it lists the change, the test that proves it, and what is still assumed. "Fails before" means the new test was run against the previous commit and failed there.

**Who ran what.** Claude Code (AI agent) ran everything below during development on 2026-10-21:
- backend `pytest`: **192 passed, 1 skipped** on SQLite (the skip is a PostgreSQL-only TRUNCATE test);
- the same suite on **PostgreSQL 14.21**;
- frontend `npm test`: **37 passed**; typecheck and `next build` clean.

CI (`.github/workflows/ci.yml`) re-runs all of this on every push. Re-run it yourself before quoting any number; [REQUIREMENTS-week2.md](REQUIREMENTS-week2.md) has a column for that.

## Round A: Week 1 review points

| # | Gap | Fix | Evidence |
|---|---|---|---|
| A1 | An older admin search response could replace newer results | List requests are aborted when filters change, and only the latest response may update the table (`app/admin/page.tsx`). The activity list on the profile page is latest-wins too (`app/admin/profiles/[id]/page.tsx`). | `tests/api.test.ts` abort test: fails before, passes now |
| A2 | Parallel 401s each refreshed separately. Refresh tokens are single use, so the member got logged out. | One shared in-flight refresh, and each request retries once (`lib/api.ts`) | 3 refresh tests in `tests/api.test.ts`: 2 fail before |
| A3 | Production config silently fell back to unsafe defaults | With debug off, the app refuses to start without a separate JWT key, explicit hosts and origins, and secure cookies. All problems are reported in one message. | `backend/tests/test_config.py`: 13 of 14 fail before |

## Round B: Week 2 review points

### B1. Audit stays attributable when a profile or account is deleted

**Before.** Audit events had real foreign keys with `ON DELETE SET NULL`. Deleting a profile blanked the link on every event about it, including the "deleted" event itself, so the profile's history could no longer be found.

**Now.**
- `actor_id` and `profile_id` are **stable identifiers**: `db_constraint=False, on_delete=DO_NOTHING`. Deleting a user or profile never touches an audit row.
- The API adds **deletion markers**, `profile_deleted` and `actor_deleted`, computed with `EXISTS` subqueries. A join would hide deleted profiles' events and read profile contents for no reason.
- Migration `audit/0004` restores the ids that the earlier cascade had already blanked.

**Evidence** (`tests/test_audit.py::TestDeletionKeepsAttribution`):
- After a profile is deleted, its earlier rows are unchanged, field for field.
- The history is still found by id, marked `profile_deleted: true`.
- A deleted account keeps its `actor_id` and is marked `actor_deleted: true`.

### B2. Append-only is enforced by the database, not just the model

**Before.** `AuditEvent.save()` and `.delete()` raised errors, but `QuerySet.update()`, `QuerySet.delete()`, `bulk_update()` and raw SQL skip those methods, so they could change history.

**Now.** Migration `audit/0004` installs triggers that reject every `UPDATE` and `DELETE` on `audit_auditevent`, and on PostgreSQL also `TRUNCATE`. The model guards stay only to give a clearer error in application code. **The database is the layer that enforces immutability.**

**Evidence** (`tests/test_audit.py::TestDatabaseEnforcesAppendOnly`):
- Six bypass paths are each rejected with "append-only", and the table is unchanged afterwards.
- `TRUNCATE` is rejected on PostgreSQL.
- The triggers exist.
- Inserts still work.

All of this passes on SQLite and PostgreSQL 14.21.

**Limits.**
- A database superuser can drop the triggers. In production the app's database role should only be granted `INSERT`/`SELECT` on this table. That isn't implemented.
- On SQLite, a future migration that rebuilds this table would drop the triggers. The "triggers exist" test catches that.

### B3. Failed admin sign-ins are audited

Recorded as `admin.login_failed`, with `actor_role = anonymous`:
- If the email belongs to an account, the event links to it and the API shows it as `target_email`.
- If the email matches no account, nothing typed is stored.
- The response to the person signing in is unchanged.

**Evidence:** 4 tests in `test_audit.py`, which fail before.

### B4. Logout actually invalidates the member's credentials

**Before.** Logout blacklisted the refresh token and cleared the cookies. A copy of the access token taken before logout still worked for up to 10 minutes. The old test hid this by deleting the cookie itself before checking.

**Now.** Logout also adds the access token's `jti` to `RevokedAccessToken`, kept only until the token would have expired anyway. `CookieJWTAuthentication` rejects tokens on that list. Other devices stay signed in.

**Evidence:** `tests/test_user_auth.py::TestLogoutAndRevocationLifecycle` (9 tests). Each one replays copied cookies from a separate client, which is exactly what a direct API request does:
- a copied access token is rejected after logout, and can't PATCH the profile;
- a copied admin session id is rejected after admin logout;
- member logout and admin logout don't affect each other.

One known limit is pinned by a test: after a token **refresh**, the previous access token stays valid until it expires (at most 10 minutes).

How the account, profile, JWT cookies and admin session relate, and what each event invalidates, is set out as a table in [ARCHITECTURE.md](ARCHITECTURE.md#account-profile-credentials-how-they-relate-and-what-ends-them).

### B5. Reproducible query-plan evidence for the exact endpoint SQL

`python manage.py benchmark_admin_queries --compare-without-index` runs the real view code (filters, ordering, the paginator's `COUNT` and the page) and EXPLAIN ANALYZEs the exact SQL it captures. It prints:
- the database version, row counts and index definitions;
- the median of 5 runs, with and without each index (the index is dropped inside a rolled-back transaction).

`seed_demo --bulk-audit N` makes the audit dataset reproducible too (seed 42).

Results are labelled synthetic. They also show two honest weak spots:
- the paginator `COUNT` doesn't benefit from the indexes;
- search takes about 20 ms because no index can serve it.

See [explain-postgres.md](explain-postgres.md) and the full output in [benchmarks/](benchmarks/).

### B6. CI

`.github/workflows/ci.yml`, for each of week1, week2 and week3:
- backend: `makemigrations --check` and `pytest`, on PostgreSQL 16 and on SQLite;
- frontend: `npm ci`, typecheck, tests and `next build`;
- a final `ci-passed` job that fails if anything above failed.

**To make failures block merging**, set a branch protection rule on `main` that requires `ci-passed`. That is a repository setting, not code, and it hasn't been set yet.

### B7. Requirement → evidence checklist

[REQUIREMENTS-week2.md](REQUIREMENTS-week2.md) maps each requirement to its code, its test and its demo moment, with a column for checks you have re-run yourself.

## Implemented, observed, assumed

| | Implemented | Observed (AI session + CI) | Assumed / not verified |
|---|---|---|---|
| A1 | Abort and latest-wins | Abort test | Page wiring not browser-tested |
| A2 | Shared refresh | 3 tests | Per tab only |
| A3 | Fail-fast config | 14 tests | No real TLS deployment |
| B1–B2 | Stable ids, markers, DB triggers | 12 audit tests, SQLite + PostgreSQL | Superuser can drop triggers; no DB role separation |
| B3 | Failed sign-in events | 4 tests | No alerting on spikes |
| B4 | Access-token denylist on logout | 9 lifecycle tests | Rotation doesn't revoke the previous access token |
| B5 | Endpoint-exact benchmark | One run, PostgreSQL 14.21, 20k rows | Laptop, synthetic data; not production latency |
| B6 | CI workflow | Every step passed when run locally | Not yet run on GitHub; branch protection not set |
