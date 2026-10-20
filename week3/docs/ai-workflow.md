# AI workflow

How I used AI on this project, what I changed along the way, and how I checked its output.

## Tools used
- **Claude Code** (VS Code extension, agentic mode) for most of the build: editing files, running the shell, running tests.
- **Playwright** (Python) to drive a real browser for the end-to-end checks and the screenshots.
- Plain `curl` and the Django shell for poking at the API and the database when something looked off.

## 1. Prompt iterations

I didn't save the first chat word for word, so the prompts below are close paraphrases, not exact copies.

| | Iteration 1 (initial) | Iteration 2 (refined) |
|---|---|---|
| Prompt | "Act as a senior full-stack developer. Build the HealthProfile app from the attached assignment PDF so both roles are completely workable as in the guide. Justify the stack." | "Same assignment, but treat it as **two separate auth systems**: members sign up and get a short-lived JWT in an HttpOnly cookie; admins can **only** be created by a management command and log in with a Django server-side session + CSRF. A member token must never authenticate an admin route, and the other way round. No secrets in the repo: everything comes from `.env`, with a `.env.example` committed. Work one app at a time (`accounts`, `profiles`, `adminpanel`) and don't touch other apps. A feature is only done when there are tests for it, including the failure cases (bad token, expired token, other user's profile, duplicate email)." |
| What was wrong with the output | It worked as a demo, but the requirements were vague. "Admin" and "user" leaned towards sharing one login flow with a role flag, it didn't say where the token lives, and tests were an afterthought. Nothing actually proved a user couldn't reach admin endpoints. | Smaller problems remained, and the tests caught them (see bugs below). |
| What I changed and why | | I named both auth mechanisms explicitly, wrote down the access boundary as a rule, limited which files each step could touch, banned secrets, and made "tests pass" the definition of done. The assignment grades the separation, so I couldn't leave it to the model to infer. |
| Observed difference | | Separate login endpoints, separate authentication classes, and `DEFAULT_AUTHENTICATION_CLASSES = []`, so every view has to declare its own auth. Admin signup simply doesn't exist. I got 125 tests, including cross-role ones (`test_user_jwt_gives_no_admin_privileges`, `test_admin_session_does_not_authenticate_user_endpoints`). Changes stayed inside the app I asked for. |

**Smaller follow-up prompts that made a difference**
- "Return JSON errors in one envelope shape everywhere, including 404 and 405." This exposed Bug 1.
- "Run the whole flow through the Next.js proxy in a real browser, not just unit tests." This found Bug 2.
- "Show me an EXPLAIN plan before and after the index, on enough rows that the planner actually uses it." This gave me the numbers in `docs/explain-postgres.md`.

## 2. Blast-radius control (what was actually done)

- **Scoped by module**: backend split into `accounts/`, `profiles/`, `adminpanel/`; each change touched one app plus its tests.
- **Tests as the safety net**: 125 tests written alongside the code; every fix re-ran the whole suite, so a change that broke another area was caught in seconds.
- **Small, reviewable commits** (backend, then frontend) rather than one dump.
- **Explicit allow-list for auth**: `DEFAULT_AUTHENTICATION_CLASSES = []` so no view can silently inherit an authenticator.
- **Secrets isolated**: `.env` git-ignored; verified with `git ls-files` that no `.env`, `db.sqlite3` or venv is tracked.
- **Read-only evidence before claims**: query plans and the browser run were executed, not assumed.

## 3. Manual security review checklist

I went through these myself rather than trusting the AI's summary.

- [x] `grep -rn "SECRET\|PASSWORD" --include=*.py backend/ | grep -v tests` shows only env lookups, no literals.
- [x] `git log -p | grep -i "password\|secret"` shows nothing real (only `.env.example` placeholders).
- [x] Signup serializer has no `role` field; only `create_admin` / `seed_demo` create admins.
- [x] Every view declares `authentication_classes` and `permission_classes` (read `*/views.py`).
- [x] `PATCH /profiles/me/` cannot change `status`, `email`, `user` (see `test_read_only_and_foreign_fields_are_ignored`).
- [x] No endpoint takes a profile id for members (only `/me/`).
- [x] Login errors are generic; cookies are HttpOnly; CSRF required on POST/PATCH.
- [ ] Try it by hand: log in as a member, then `curl` an `/api/admin/` route with that cookie (expect 401). *(Doing this live in the Loom video.)*

## 4. Context management
- **One source of truth.** The assignment PDF stayed attached, and I pointed back to it instead of re-explaining requirements every time.
- **One module per session/step.** Backend `accounts`, then `profiles`, then `adminpanel`, then the frontend. I didn't ask for "the whole app" again after iteration 1.
- **Summaries instead of re-pasting.** Decisions went into `docs/ARCHITECTURE.md`, so new context could read that file instead of me pasting large files back into the chat.
- **Paths, not file dumps.** I referenced files by path (e.g. `backend/accounts/views.py`) and let the agent read just the part it needed.
- **Evidence over claims.** If the AI said something worked, I asked it to run the test, curl or EXPLAIN and show me the output.

## 5. Bugs and unexpected behaviour (real, from this build)

### Bug 1: unknown IDs returned HTML 500 instead of JSON 404
- **Symptom:** `tests/test_admin.py::test_deactivate_unknown_profile_is_404` failed with `AttributeError: 'Http404' object has no attribute 'detail'`.
- **Isolation:** the traceback pointed at my custom `api_exception_handler`; it read `exc.detail`, but Django's `Http404` (raised by `get_object_or_404`) is not a DRF exception.
- **Fix:** normalise `Http404`/`PermissionDenied` to DRF exceptions at the top of the handler.
- **Regression test:** `tests/test_error_format.py::test_get_object_or_404_returns_json_404_not_500` (+ unknown route, envelope shape, 405).
- **Lesson:** AI-written error handlers need tests for the *non-happy* exception types, not just validation errors.

### Bug 2: every API call 301/308-looped through the frontend proxy
- **Symptom:** `curl localhost:3000/api/health/` returned redirects; the page worked in isolation, the proxy did not.
- **Isolation:** `curl -i` showed `server: WSGIServer` on the 301, i.e. Django was redirecting. Next strips trailing slashes by default (and its rewrite destination dropped the slash), Django's `APPEND_SLASH` added it back: a loop.
- **Fix:** `skipTrailingSlashRedirect: true` plus a slash-terminated rewrite pattern in `next.config.mjs`.
- **Verification:** proxy returns 200/401 as expected; the 24-step browser run exercises every route through the proxy.
- **Regression guard:** the Playwright run (it fails immediately if any API call loops). A CI smoke test is on the to-do list (section 7).
- **Lesson:** unit tests passed while integration was broken; only an end-to-end run through the real proxy found it.

### Bug 3 (tooling): `pkill -f` killed my own shell
Matching a process name that also appeared in the command line terminated the shell (exit 144) and skipped the commit that followed. Fix: select PIDs with `ps | grep "[r]unserver"` and verify state before retrying.

### Bug 4 (setup): admin login kept returning 401
- **Symptom:** after a fresh setup, `POST /api/admin/login/` returned 401 even with the password from `.env`.
- **Isolation:** I checked the database directly from the Django shell: no `admin@example.test` row existed at all. Migrations had run, but `seed_demo` never had, so the password was fine and the account was missing.
- **Fix:** ran `python manage.py seed_demo` (it's idempotent), then confirmed `check_password()` was True and the role was `admin`.
- **Lesson:** a generic "invalid credentials" error is deliberate (no account enumeration), but it means you check the DB before assuming the password is wrong.

### Test-helper bug (not app code)
`Browser.get()` did not accept query params, causing 3 false failures. Fixed the helper, not the app: always decide *which side* is wrong before "fixing" a failing test.

## 6. Verification performed
- `pytest`: 125 passed on SQLite and on PostgreSQL 16.
- `npm run typecheck` + `npm run build`: clean.
- Playwright: 24/24 checks (both roles, forged client state, deactivation, mobile layout).
- `EXPLAIN ANALYZE` before/after index: 2.9 ms vs 14.1 ms at 20k rows (`docs/explain-postgres.md`).
- Not verified: `docker compose` (no Docker daemon in the build sandbox); HTTPS cookie behaviour with `Secure` (tests force `COOKIE_SECURE=true` and assert the flag, but no real TLS run).

## 7. What I'd do differently
- Write the refined prompt (two auth systems, tests as done) on day one. Most rework came from iteration 1 being vague.
- Save prompts as I go. I had to paraphrase my first one above.
- Add CI (GitHub Actions running pytest + the Playwright run) so the proxy-loop bug can't come back silently.
- Add a `jti` denylist so logging out kills an access token immediately instead of at expiry.
- Move throttling to Redis and use `pg_trgm` for admin search once the data grows.

---

# Week 2: professional directory

## Prompt iterations

| | Iteration 1 | Iteration 2 (how I steered the work) |
|---|---|---|
| Prompt | "Make a folder for week 2 and start working on the Week 2 assignment as a senior full stack engineer." (with the Weeks 2–6 PDF attached) | Follow-ups that narrowed it: keep Week 1 frozen and build on a copy; the URL is the only filter state; validate the JSON, don't trust it; tests and a real-browser run are the definition of done. |
| What the first prompt left open | Where Week 2 lives relative to Week 1, which state library to use, and how "done" is proven. The brief also says "CareConnect" while our app is "HealthProfile". | |
| What changed | | Copying `week1/` → `week2/` as its own commit keeps the Week 1 submission untouched and makes the Week 2 diff readable. Choosing URL + `localStorage` instead of a global store removed a whole category of sync bugs. Writing the browser acceptance script from the PDF's acceptance checks turned "looks done" into 33 pass/fail checks. |

## Blast radius
- Week 2 is a separate folder, and the copy is its own commit (`chore(week2): start Week 2 from a copy…`).
- Only three existing frontend files changed (home page link, appended CSS, `Shell` → `Layout` adapter). Backend untouched. See `docs/WEEK2.md`.
- Business rules live in pure modules (`lib/filters.ts`, `lib/appointment.ts`, `lib/professionals.ts`), so components stay thin and the rules are unit-tested without a browser.

## Bugs found by verification (real, from this build)

### Bug 1: ticking a specialty chip didn't tick
- **Symptom:** the browser test failed on its second step: `Locator.check: Clicking the checkbox did not change its state`. Unit tests were all green.
- **Isolation:** the checkbox was controlled by the URL. Clicking called `router.replace` inside a transition, so the box stayed unticked until the server re-render came back. A real user sees lag. Two fast clicks could also lose the first one, because the second built on the old URL.
- **Fix:** render the controls from `useOptimistic(committedFilters)` and set the optimistic value in the same transition as the navigation.
- **Regression guard:** the browser run's first filter step (`.check()` on a chip, then combine with a location) fails without the fix and passes with it.
- **Lesson:** "the URL is the state" is right, but URL updates are async; the UI needs an optimistic layer.

### Bug 2: error summary didn't always get focus
- **Symptom:** 32/33. "Error summary receives focus" failed.
- **Isolation:** focus was moved in `requestAnimationFrame` right after `setErrors`, which raced React's commit of the summary element.
- **Fix:** count failed attempts in state and focus inside a `useEffect` keyed on that count. It runs after the summary is in the DOM, every time (even when the errors are identical).
- **Regression guard:** the browser test waits on `to_be_focused()` and then asserts `document.activeElement`.

### Bug 3 (tooling): `npx next start` started the wrong Next.js
- Run from the wrong working directory, `npx` downloaded Next 16 instead of using the project's 15.5.4, and it failed with "no production build". Fix: call `./node_modules/.bin/next` explicitly. Lesson: never let `npx` silently fetch a tool version.

## Verification performed
- `npm test`: 33 Vitest unit tests (data validation incl. broken fixtures, filter parsing/round-trip/AND logic/sorting, form rules, corrupted-draft handling).
- `npm run typecheck` and `npm run build`: clean (16 profile pages + 16 request pages pre-rendered).
- `e2e/run_week2_e2e.py`: 33/33 against the production build (filters + URL + reset + empty state + garbage params, 200/404 routes, favourites persistence, form errors/focus/ARIA, draft survives refresh, mobile menu + no horizontal scroll, no uncaught JS errors).
- Screenshots reviewed by eye (desktop list, form errors, mobile).

---

# Week 2 (Full-Stack AI/ML track): completion status and audit events

## How this part started: wrong brief

I first built Week 2 from the **frontend** PDF (CareConnect). When I attached the **Full-Stack AI/ML**
PDF to start Week 3, the AI compared it with the repo before writing anything and flagged that the
AI/ML Week 2 asks for things the code didn't have: audit events and profile completion status. I chose
to fix Week 2 first and keep CareConnect as a bonus. Lesson: put the exact brief in the first prompt,
and ask the AI to diff the brief against the repo before planning.

## Prompt (paraphrased)

> "I'm on the AI/ML track. Fix Week 2 first: add audit events for profile edits and admin actions
> (no secrets or sensitive payloads) and a profile completion status, then build Week 3."

The AI read the existing models, views, tests and seed command before editing, and kept the change
inside `profiles/`, `adminpanel/`, one line in `accounts/views.py` (signup event), a new `audit/` app and
three frontend pages.

## Blast radius
- New behaviour in new modules: `audit/` (model, service, serializer), `profiles/completion.py`, `config/middleware.py`.
- Existing views got one `record_event(...)` call each, inside the same transaction as the change.
- The 125 existing tests were run **before** writing any new tests: all still passed, so nothing old broke.
- The Week 1 browser run (24/24) and CareConnect browser run (33/33) were re-run against the changed app.

## Issues found by verification
1. **Renamed migration broke every test (125 errors).** I renamed `0002_healthprofile_completion_status_and_more`
   to `0002_completion_status`, but `audit/0001` still depended on the old name.
   `pytest -x` showed `NodeNotFoundError`; fixed the dependency.
2. **"Admin viewed profile" logged twice.** Seen in the screenshot, not in tests. Cause: React StrictMode runs
   effects twice in `next dev`. Confirmed by re-running against `next build && next start`: one event per visit.
   Left as is; it's dev-only.
3. **Redundant index.** `EXPLAIN` on PostgreSQL showed Django's automatic FK index on `audit_auditevent.profile_id`
   next to my composite `(profile_id, created_at)`. Dropping it changed nothing in the plan, so the FK is now
   `db_index=False`: one less index to update on every audit insert.
4. **Tooling:** the temporary Postgres wouldn't start (Unix socket path over 103 bytes) → TCP-only.
   zsh doesn't word-split `$P` → used a shell function. `psql -c "BEGIN; …; ROLLBACK"` prints only the last
   result → piped the statements on stdin instead.
5. **Screenshot showed the bottom of the page** (after save the page was scrolled) and the audit "Fields" column was
   clipped → scroll to top before the screenshot, and let that column wrap.

## Verification
- `pytest`: 149 passed on SQLite and on PostgreSQL 14 (24 new: completion rules, API, admin filter, bulk seed,
  audit on every action, values never stored, append-only, request id, role boundaries).
- `e2e/run_audit_e2e.py`: 11/11 against the production build. Week 1 run 24/24, CareConnect run 33/33.
- EXPLAIN with and without each new index on 20k profiles / 60k events (`docs/explain-postgres.md`).

---

# Week 3: ML pipeline and prediction API

## Prompt (paraphrased)

> "Now Week 3" + the Full-Stack AI/ML PDF. The AI first checked the PDF against the repo (which is how the
> Week 2 gap above was found), fixed Week 2, then planned Week 3 from the acceptance checks backwards:
> reproducible artifact, validated versioned output, README metrics + limitations + sample request.

Constraints I held it to: synthetic data only; preprocessing saved inside the model; every choice on
validation, test scored once; exact dependency pins; no clinical wording anywhere; Week 1/2 tests stay green.

## Blast radius
- Week 3 is its own folder, copied from Week 2 in its own commit.
- New code in new places: `backend/ml/` (pure Python, no Django), `backend/predictions/` (API),
  `frontend/app/admin/predictions/`. Existing files touched: settings (app, throttle, artifact dir), root
  urls (`/api/v1/`), one new audit action (+ migration), one nav link, `lib/api.ts` types, CSS appended.
- All 149 Week 2 tests and the three earlier browser suites were re-run on Week 3.

## What verification caught
1. **The "improved" model wasn't better.** First run: gradient boosting vs logistic regression PR-AUC
   0.3265 vs 0.3263 on validation, and *worse* on test. Rather than tune until a number went up, I changed
   what "improved" means: baseline = logistic on raw inputs; improvement = five features each backed by an
   EDA table. That gave a real, consistent gain (validation PR-AUC 0.304 → 0.345; test 0.358 → 0.371).
2. **Was the model weak or the data noisy?** Added an "oracle ceiling" (score of the generator's true
   probability): 0.717 ROC-AUC vs 0.712 served. So the model is near the limit; noise is the cap.
3. **EDA captions over-claimed.** I'd written "no-show rate flattens past 60 days" and "distance only matters
   in person"; the tables showed it keeps rising and distance matters only beyond 20 km. Reworded to match.
4. **Four failing tests, four different causes:** (a) a substring check flagged the legit feature
   `prior_no_shows` as the target `no_show`; (b) a "train median ≠ full median" check was false because
   0.1-km medians coincide → switched to the scaler's mean, a continuous statistic; (c) two runs differed only
   in the data *file name* recorded in metadata; (d) the full retrain matched data hash and metrics but not
   the artifact bytes. Fresh processes always produced the committed SHA-256; only inside pytest (after other
   models were trained in the same process) did pickle bytes differ. The test now trains in a subprocess,
   like a reviewer would.
5. **UI test expectation was wrong, not the app:** DRF runs the cross-field rule (`prior_no_shows ≤
   prior_appointments`) only after per-field checks pass, so the browser test now checks the two in sequence.
6. **Model card hid a candidate:** the API listed 4 of 5 models (dropped gradient boosting). Showing all is
   more honest; fixed the API, not the test.

## Context management
- The AI read the existing code before each change instead of me pasting it.
- ML code is plain Python with no Django imports, so it's testable and reviewable on its own.
- Generated evidence (EDA, metrics, metadata JSON) is committed as files, so the next session reads numbers
  instead of re-deriving them.
