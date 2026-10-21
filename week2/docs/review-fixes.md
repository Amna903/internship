# Week 2: review fixes and evidence

The Week 1 review found three reliability gaps. Week 2 started as a copy of the Week 1 code, so it had the same gaps. I applied the same fixes here (see [Week 1 review-fixes](../../week1/docs/review-fixes.md) for the full reasoning).

The same review lens also turned up three gaps in the new Week 2 features. Each fix has a test that fails on the previous commit and passes now.

| # | Gap | Before | After |
|---|---|---|---|
| 1 | Admin list: an older search response could replace newer results | fail | pass |
| 2 | Parallel 401s each refreshed separately, so the member could be logged out | 2 fail | pass |
| 3 | Production config silently fell back to unsafe defaults | 13 fail | 14 pass |
| 4 | A deleted profile's audit history disappeared | fail | pass |
| 5 | Failed admin sign-ins left no trace | 4 fail | pass |
| 6 | Activity list on the admin profile page could show an older trail | (code fix, see below) | |

Totals: backend `pytest` **173 passed**, frontend `npm test` **37 passed**, typecheck clean.

## 1–3. Same fixes as Week 1

- `frontend/lib/api.ts`: one shared in-flight refresh, and every request accepts an `AbortSignal`.
- `frontend/app/admin/page.tsx`: the list request is aborted when the search, status, completion, sort or page changes.
- `backend/config/settings.py`: with debug off, the app refuses to start without a separate JWT key, explicit hosts and origins, and secure cookies. All problems are reported in one message.
- Tests: `frontend/tests/api.test.ts` (vitest) and `backend/tests/test_config.py`.

## 4. Audit history survives profile deletion

**Problem.** Audit events linked to a profile with a foreign key set to `ON DELETE SET NULL`. When a member deleted their profile, every one of its events lost the link, including the "profile deleted" event itself. Filtering the audit log by that profile then returned nothing, exactly when the history mattered most.

**Change.**
- `AuditEvent.subject_profile_id` is a plain copy of the profile id, written by `record_event` and never nulled.
- The `?profile=` filter and the API's `profile_id` field now use it.
- New composite index `audit_subject_created_idx (subject_profile_id, created_at DESC)`.
- The existing `profile_id` index stays, so deleting a profile can find its rows to null without a full scan.
- Migration `audit/0003_audit_hardening` backfills the id for existing events that are still linked.

**Evidence.** `test_history_survives_profile_deletion`: a member edits their profile, an admin views it, then the member deletes it. Filtering by the old id still returns all three events, newest first. `explain_queries` shows the history query uses `audit_subject_created_idx`.

**Assumptions.**
- Events orphaned before this migration can't be recovered.
- The PostgreSQL timings in `explain-postgres.md` were measured on the earlier `profile_id` query and were not re-run for the new index. The new index has the same shape.
- On SQLite, ids can be reused after the newest row is deleted. PostgreSQL sequences never reuse ids.

## 5. Failed admin sign-ins are audited

**Problem.** Only successful admin logins were recorded, and a test explicitly asserted that failures recorded nothing. Repeated password guessing against an admin account left no trace for anyone to review.

**Change.** A rejected `POST /api/admin/login/` writes an `admin.login_failed` event with `actor_role = "anonymous"`:
- If the email belongs to a real account, the event links to it, and the API shows that account as `target_email`, never as `actor_email`.
- If the email matches no account, nothing typed is stored. People sometimes paste a password into the email field.
- The client still receives the same generic 401, so this gives an attacker no new signal about which accounts exist.
- The login throttle (10/min per IP) still limits how many events one attacker can generate.

**Evidence** (`backend/tests/test_audit.py`):
- `test_failed_admin_login_is_recorded_against_the_targeted_account`
- `test_failed_login_for_unknown_email_stores_nothing_typed`: the typed value appears nowhere in the audit table
- `test_member_trying_admin_login_is_recorded`
- `test_failed_login_is_shown_as_target_not_actor`

**Assumption.** No alerting yet. The events are recorded, but nothing notifies anyone when they spike.

## 6. Activity list cannot show an older trail

**Problem.** `app/admin/profiles/[id]/page.tsx` reloaded the activity list after each activate/deactivate without cancelling the previous load. With quick clicks, an older list could land last.

**Change.** Each reload aborts the previous one, and only the newest request can call `setEvents`. Pending loads are also aborted when the page unmounts.

**Evidence.** Same abort mechanism as fix 1, which `api.test.ts` covers. The page wiring itself was reviewed by reading the code and typechecked, not browser-tested.

## Implemented, observed, assumed

| | Implemented | Observed | Assumed / not verified |
|---|---|---|---|
| 1, 6 | Abort and latest-wins per request | Abort test passes | Page wiring not browser-tested |
| 2 | One shared refresh | 3 refresh tests pass | Per tab, not across tabs |
| 3 | Fail-fast config | 14 config tests | No real TLS deployment |
| 4 | Surviving profile id plus index | Deletion test, SQLite plan | Postgres timing not re-measured |
| 5 | Failed sign-in events, nothing typed stored | 4 audit tests | No alerting on spikes |

How to run the tests: `cd backend && .venv/bin/python -m pytest`, and `cd frontend && npm test`.
