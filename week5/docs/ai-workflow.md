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

# UI refresh

Prompt (paraphrased): "improve the frontend: make it look cool, aesthetic, pretty and professional."

- **Constraint I kept:** class names and visible text that the browser tests rely on stay the same, so the
  restyle is mostly one rewritten `app/globals.css` (tokens for colour, radius, shadow and type, light and dark)
  plus a few small components (`BrandMark`, `Icon`, `Avatar`, `PageHeader`). No new npm dependencies; fonts
  (Inter, Instrument Serif) are self-hosted by `next/font` at build time.
- **Checked by screenshots, not by eye on the code:** light, dark and 390-px mobile. They caught a completion
  ring stretched into an ellipse (a flex rule meant for its sibling), a stray space in the logo wordmark, a
  floating preview card hiding text, colliding meter labels, the sticky header appearing mid-page in full-page
  screenshots (scroll to top first), and a progress bar captured mid-animation.
- **Regression:** every browser suite re-run against the production build after the restyle; all green.

---

# Completing CRUD: delete own profile

A re-check of the brief line by line found that "user-owned profile **CRUD** endpoints" was only C, R and U.
Added `DELETE /api/profiles/me/`: deletes the caller's profile only (there is still no id in the URL), keeps the
account, records `profile.deleted` in the same transaction, and needs CSRF like every other write. UI: a
"Delete my profile" section with a confirm dialog, and an empty state that lets the member create a new profile.
Tests: 6 API tests (own-only, audited without data, recreate, second delete 404, CSRF, admin/anonymous blocked)
and 4 browser checks (delete, persists after reload, recreate at 0%, visible to admins in the audit log).

---

# Review-fix round (2026-10-21): auditable record

**Tool.** Claude Code (Claude Opus 5.5, agentic mode in VS Code). It edited files, ran tests and ran the
PostgreSQL benchmark. Everything below marked "AI ran" was executed by the agent, not by me.

**Prompts, kept verbatim in substance.**
1. Original: the mentor's Week 1 review pasted as-is, then "now week 2 have any such … weakness which
   can be covered?" and "yes".
2. Refined: the mentor's Week 2 review pasted as-is. It named the priorities (requirement checklist,
   audit deletion/immutability tests, CI first). The agent was asked to turn each point into a focused
   change with a test that fails before and passes after.

**Allowed scope.** `week2/` (backend, frontend, docs) and `.github/workflows/ci.yml`. Week 1 was only
read. Week 3 was not touched (CI runs its existing tests). No secrets, no `.env` edits, nothing pushed
without asking.

**What the AI ran (observed output, not summaries).**
- `pytest` on SQLite and on PostgreSQL 14.21 after each change, plus each new test against the previous
  commit to confirm it failed there.
- `benchmark_admin_queries` on a throwaway PostgreSQL database (`docs/benchmarks/`).
- Every CI step locally: `makemigrations --check`, `npm test`, `npm run typecheck`, `npm run build`.

**Problems the agent hit and fixed along the way.**
- The `RAISE` message in the PostgreSQL trigger contains `%`, which psycopg read as a query
  placeholder. Fixed with `params=None`.
- Filtering audit events by profile while joining the profile table turned the join into an INNER JOIN
  and hid deleted profiles' events. Replaced with `EXISTS` subqueries.
- An existing test (`test_after_logout_browser_is_unauthenticated`) deleted the access cookie before
  checking, which hid that a copied access token kept working after logout. This led to fix B4.

**What I still have to do myself (not done by the AI).**
- [ ] Review each commit's diff line by line: `git log --oneline` then `git show <hash>`.
- [ ] Re-run `pytest` and `npm test` on my machine and fill the "Me" column in `REQUIREMENTS-week2.md`.
- [ ] Re-run the benchmark (commands in `explain-postgres.md`) and compare with the committed output.
- [ ] Be able to explain without notes: why DB triggers and not model methods, why stable ids instead
  of foreign keys, what logout revokes, and why the COUNT query doesn't use the index.

---

# Week 3: machine-learning pipeline and prediction API (2026-10-24 to 2026-10-27)

**Tools:** Claude Code (Claude Opus 5.5, agentic mode in VS Code) wrote the code and ran the commands
listed below. I directed every step, reviewed the checklists before any code was written, and sent
corrections, which are listed under "Refinements". Everything marked "AI ran" was executed by the agent;
"I ran" is listed separately at the end.

## 1. How the work was structured (context management)

- **The brief first.** I gave the agent the full-stack brief PDF (the Week 3 section) and asked for a
  checklist of what is required *before* any code. That is my Week 2 mentor's lesson: Week 2 started
  from the wrong brief. Result: [REQUIREMENTS.md](REQUIREMENTS.md), with one row per brief line and
  columns for code, test, demo moment and "re-run by me".
- **Base reset.** I chose to replace the old `week3/` with the reviewed Week 2 code; the old folder
  stays in git history. All 192 Week 1–2 tests were confirmed green in the new folder before any ML
  code.
- **One step at a time.** For each of Steps 1–11 the cycle was the same:
  1. the agent proposed a checklist with library choices and rejected alternatives;
  2. I reviewed it, often with corrections;
  3. it built;
  4. it reported results in plain language;
  5. I re-ran the commands myself.

  I asked for comparisons ("is this the best approach, and why?") before Step 1, and the agent
  compared the options (synthetic generator vs public dataset vs LLM-made data; which model, which
  metric, which file format) before choosing.
- **Reports instead of re-explaining.** Each step writes a committed, deterministic report (`eda.md`,
  `metrics.md`, `errors.md`, the model metadata), so later steps read the file rather than relying on
  chat history.
- **CI as the gate.** After CI was added, the rule was: push each step, wait for CI to be green, and
  only then start the next step.

## 2. Actual prompts and refinements

My messages were in Urdu/English. They are quoted or closely translated here.

| When | What I asked or corrected | What changed |
|---|---|---|
| Start | "assume week 3 wasn't done at all, now according to the requirements make the checklist" + the brief PDF | 14-step checklist from the brief |
| Step 1 | "is this the best approach, if yes why, and how?", then "no coding-related comparison yet? which model, which thing?" | Synthetic generator compared with a public dataset and with LLM-made data; formula given a curve, an interaction and a hidden habit, so an improved model has something real to find; oracle ceiling added |
| Step 3 | "use log1p for lead time (lead time can be 0), and handle prior_appointments = 0 in the no-show ratio without dividing by zero. Add tests for both." | `log1p` + ratio 0 with a separate `has_history` flag (so "new patient" ≠ "never missed"); tests that fail with the naive version (`-inf`, `nan`) |
| Step 3 → 4 | "Did you add a joblib save/reload test for the pipeline with the custom transformers?" and "push now, the laptop is the only copy" | The test had not been added; added (reload in a fresh process). 14 unpushed commits pushed; CI was green on its first GitHub run |
| Step 4 | "if 'improved beats baseline' fails, that's a finding, not a code bug; don't force the test to pass, report it" | The test now checks that the report tells the truth; added a bootstrap 95% interval and a computed verdict |
| Step 5 | "the 3-point calibration rule may give false alarms with ~400 rows per bin; account for sampling noise" and "if recalibration triggers, don't change the shipped model, because the test set was already used" | Bonferroni limit (|z| > 2.81); on this data a naive 2-SE rule would have raised two false alarms. No model change after the test; drop-age analysed only |
| Step 6 | "the fingerprint is in the .json too, so be honest: it catches accidents, not attackers" and "'High risk' sounds clinical; use plain, non-clinical terms" | README and code say what the SHA-256 does and does not do; output is "Extra reminder suggested" / "Standard reminder", enforced by tests |
| Step 7 | "who supplies prior_no_shows? Write: the caller supplies the history counts; the API does not look them up" and "tick K3 only when admin login, CSRF, rate limit and input-free audit all pass" | The sentence appears in the README, API docs, schema and model card; K3 ticked only after its four tests passed |
| Step 8 | "add 2–3 'Fill example' buttons with synthetic presets, one per result, so the Loom demo is quick" | 3 presets; a backend test checks that each preset gives the result its label promises |
| Throughout | "CI should finish first" | The next step starts only after the previous push is green |

## 3. Blast radius (what each step was allowed to touch)

Every step touched only the files listed. Nothing outside `week3/` changed except the shared CI file.
Week 1 and Week 2 were never edited.

| Step | Files | Commit |
|---|---|---|
| 0 | `week3/` replaced by a copy of `week2/`; `docs/REQUIREMENTS.md` | `6961ab5` |
| 1 | `ml/config.py`, `ml/data.py`, `requirements.txt` pins, `docs/DATA_CARD.md`, `tests/test_ml_data.py` | `4c1afd8` |
| 2 | `ml/eda.py`, `ml/reports/eda.md`, `tests/test_ml_eda.py` | `f2b1ede` |
| 3 | `ml/split.py`, `ml/features.py`, `ml/preprocess.py`, `tests/test_ml_preprocess.py` | `9341dc5`, `e904476` |
| 4 | `ml/models.py`, `ml/train.py`, `ml/reports/metrics.md`, `tests/test_ml_train.py` | `d8ac671`, `ea9ad48` |
| 5 | `ml/errors.py`, `ml/reports/errors.md`, DATA_CARD bias numbers, `tests/test_ml_errors.py` | `425ce70` |
| 6 | `ml/artifact.py`, `ml/inference.py`, `ml/artifacts/*`, `tests/test_ml_artifact.py` | `7e3d0d1` |
| 7 | new `predictions/` app, audit migration `0005`, settings/urls, `docs/API.md`, `tests/test_predictions_api.py` | `5ae227b` |
| 8 | `frontend/app/admin/predictions/`, `lib/prediction.ts`, `lib/noShowSchema.json`, tests, `e2e/run_week3_e2e.py` | `c4dea58` |
| 9–10 | README, `docs/WEEK3.md`, `docs/ARCHITECTURE.md`, `tests/test_docs.py` | `63293c3` |
| 11 | `ml/verify_release.py`, `.github/workflows/ci.yml` (new job) | `8a02397` |

The riskiest change was migration `0005` on the append-only audit table: adding a column can make
SQLite rebuild the table, which drops its triggers. The agent printed the SQL first (`sqlmigrate`) and
confirmed it is a plain `ALTER TABLE ADD COLUMN`. A test checks the triggers survive on SQLite and
PostgreSQL.

## 4. Debugging: real problems found and fixed

| Problem | How it showed up | Fix |
|---|---|---|
| EDA overclaim: "no link between missing distance and no-show" | The report itself showed a 2.1-point gap | Added a significance test (p = 0.03); stated honestly that it is a false alarm, because the blanks are random by construction |
| EDA wording contradicted itself ("unlikely chance" … "sampling noise") | Reading the generated report | Rewritten |
| Markdown tables not rendering | Missing blank line before two tables | Fixed |
| `get_feature_names_out` missing on the custom transformers | Smoke run crashed | Implemented on `ColumnGuard` and `EngineeredFeatures` |
| Engineered columns in the wrong order | `input_features is not equal to feature_names_in_` | `engineer()` always returns a fixed column order |
| `Candidate` couldn't be a dict key | `TypeError: unhashable type: 'dict'` | Settings stored as a tuple |
| Flaky audit test | Searched the whole row for "19", which the timestamp can contain | Checks each column explicitly |
| API reported only the first of several errors | Captured real output for the docs | All errors returned together; test added |
| Wrong error code in the docs (`csrf_failed`) | Checked the real response | Documented `permission_denied` |
| A test helper matched the wrong README row ("Baseline + improved …") | `test_docs.py` failed | Search limited to the Metrics section |
| No-show rate written as 16.4% for the test set | Cross-checked against the reports | Corrected to 16.5% (16.4% is the whole dataset) |
| Login selector `button[type=submit]` not found | Browser run timed out | Matched the existing scripts (`has-text('Sign in')`) |

## 5. Verification

**Fail-before evidence.** Edge-case tests were run against the naive version (`log(0) = -inf`,
`0/0 = nan`). The docs-number test was proven by changing 0.280 to 0.290 in the README: it failed, and
passed again after restoring. Each refusal path in the model loader is checked to never unpickle the
file.

**AI ran:**
- the backend suite after every step: 383 passed + 1 PostgreSQL-only skip on SQLite, and the full
  suite on local PostgreSQL 14.21;
- frontend: 53 tests, typecheck, `next build`;
- `python -m ml.verify_release`: all levels PASS, including the byte-identical model file on macOS;
- the real-browser check: 17/17, with the agent opening and reading the screenshots, not only the
  script output.

**CI ran (every push):** backend on PostgreSQL 16 and SQLite for Weeks 1–3, frontend checks, and the
"ML reproducibility (week3)" job on Linux.

**I ran:** see the "Me" column in [REQUIREMENTS.md](REQUIREMENTS.md). My own runs so far: Step 1
(`ml.data`: same SHA-256 `f458e62a…`, 14 tests), Step 2 (`ml.eda`, 8 tests).

**Still to do myself before submitting:**
- [ ] Read each Week 3 commit's diff: `git show <hash>` for the commits in section 3
- [ ] Re-run `pytest`, `npm test` and `python -m ml.verify_release`, and fill the "Me" column
- [ ] Run the `curl` sample from the README against my own backend
- [ ] Explain without notes:
  - why the split is by patient
  - why PR-AUC and not accuracy
  - what the oracle ceiling shows
  - why the test set is used once
  - why the calibration limit is 2.81
  - why the SHA-256 isn't attacker-proof
  - why the audit stores the model version but not the inputs

# Week 4: supervised + unsupervised ML and the local LLM assistant

A running record, added to as each step lands. The full decision history is in
[REQUIREMENTS-week4.md](REQUIREMENTS-week4.md) ("Lessons recorded along the way").

## Step 9: LLM foundation

### Finding: the small model's self-labelled status was unreliable

- **What happened.** The first design asked the model for `status` (answered / insufficient_information /
  refused) alongside its answer. On a development question whose answer was plainly in the passage
  ("How late can I cancel without a charge?"), `llama3.2:3b` returned `insufficient_information` with an
  empty answer three times out of three.
- **First diagnosis.** With Ollama's structured output, the model writes keys in schema order, so it
  committed to `status` before writing any answer. Putting `answer` and `citations` first made it write the
  correct answer and an exact, correct quote, and then still label it `insufficient_information`.
- **Decision (user-approved).** The model no longer labels its answer. It returns `answer`, `citations` and
  a `refused` flag; the server derives the status from checks it can verify: the cited passage was actually
  given, the quote appears in it (case and whitespace normalised), the answer is substantive (not empty,
  not "I don't know"), the answer's key terms appear in the quotes, and every number in the answer
  appears in the quotes. Refusal is defence in depth: a server-side medical-advice check (which refuses
  before any model call) or the model's flag.
- **Found by a test, fixed.** The word-share groundedness check alone accepted "Up to 48 hours" against a
  quote saying "24 hours" (3 of 4 terms matched). Numbers are now a hard rule.
- **Process guard.** All tuning so far used development questions only. The groundedness threshold is
  provisional and will be set on the development set in Step 11; the 12 evaluation cases are written and
  frozen before any further tuning.

### Verification

- Live, against the local model: the answerable development question is answered with a verified
  citation; an out-of-scope question returns insufficient_information; a dosage question is refused by
  the server check without calling the model.
- Automated (no real model in tests or CI): `tests/test_assistant_foundation.py` covers server-decided
  status, refusals, strict output validation, the context budget, redaction, the real client against a
  local imitation of Ollama (request format, timeout, server error, unreachable server), safe errors, cost
  reporting and the admin-only status endpoint.

## Step 11: tuning on the development set and the question endpoint

- **Rules first.** The floor, top-k and groundedness rules were written and approved before tuning ran
  (`assistant/tuning.py`), with three fixed seeds per value of k and a two-of-three majority.
- **First run exposed terse answers.** Every answer was a fragment ("No", "2 hours"), so the word-overlap
  groundedness check scored 1.0 everywhere and a wrong "No" passed with a real citation. Fixed with a
  complete-sentence instruction, a minimum of two key terms, and a polarity check.
- **My prompt example leaked a dev answer.** The first full-sentence example was literally the correct
  answer to dev question D4; replaced with a neutral sentence before tuning ran again.
- **The polarity check had a false block** (D3, "at no cost"); fixed with a short phrase list. The user's
  first list included "no fee" and "no charge"; checking the policies showed they don't occur there and would
  hide exactly the most harmful flip (the 15-euro fee), so the list was reduced to the two phrases that occur.
- **A stale test default hid failures.** `FakeLLM`'s default reply still used the old schema, so unscripted
  calls became 502s that some passing tests never checked; found from an unexpected count of "Bad Gateway"
  log lines, fixed, and pinned by a test.
- **Verification.** Live against the local model with dev questions only (answered / below floor without a
  model call / refused before retrieval); automated tests for every status path, injection defences, safe
  errors, rate limit and audit, with known lexical gaps kept as explicit tests.


## Step 12: evaluation on the frozen cases

- **Settings named before the run.** A (shipped) and B (top-k 4) were committed in the runner before any
  case ran; the comparison is for reporting only, and A ships whatever B scores.
- **The first run looked better than it was.** Both settings passed 17/18, but most adversarial cases
  never reached the model: the similarity floor stopped them. With the user's approval I added a "which
  defence decided it" table, a no-floor diagnostic, and the user's red-team set R1–R6 (written after the
  evaluation, diagnostic only, kept out of the frozen 18). The runner was committed before the re-run, and
  the A/B results matched the first run exactly.
- **What the diagnostics showed.** R1, R2, R3, R4 and R6 cleared the floor and none leaked. With the floor
  off, U1, U2 and U9b got true but off-topic answers, U8 got a terse answer, and A6 was falsely blocked by
  the polarity check. R5 stayed below the floor.
- **No checks changed on eval results.** The gaps are recorded in
  `backend/assistant/eval/known_gaps.md` as candidates for a future dev round.

## Step 13: dashboard tabs

- **Plan approved with four additions:** example-question buttons (including red-team R1), a K-Means vs
  Ward table, tokens and cost under each answer, and a text summary plus aria labels for the PCA plot.
- **Two small backend additions, no changed checks or settings.** `/clusters/` now includes a method
  comparison read from the committed Step 7 results, and `/assistant/status/` names the embedder. Both
  are pinned by tests.
- **Verified in a real browser.** `e2e/run_week4_e2e.py` passed 23/23 against the local model, and the
  Week 3 e2e still passes 17/17 after the header link changed. One run hit the assistant's rate limit
  (two runs back to back within a minute), which is that limit working as designed.
- **Local setup note.** Another project held port 3000, so the e2e ran on port 3100 (`E2E_BASE`), with
  the backend trusting that origin through `CSRF_TRUSTED_ORIGINS` for the run only. No setting changed.
- **Found by looking at screenshots:** a doubled bracket in the model line, fixed. Found by a test: the
  model-card check read the card before it loaded, so the check now waits for it.

## Step 14: docs, regression evidence and the Loom script

- **Plan approved with four additions:**
  - the weekly-folder trade-off in the README (plan: one codebase with git tags);
  - how the mentor's three review points were addressed;
  - the real debugging moments in the Loom script;
  - a simple spoken-English script with a one-word cue list.

  A standing request was also added: a plain-English study guide at the end of every week
  ([study-guide-week4.md](study-guide-week4.md)).
- **API examples captured, not written by hand.** Every example in the Week 4 section of
  [API.md](API.md) came from the running server. The upload and approve examples ran against a copy of
  the local database, so the real document index was not changed.
- **Drafted outside the repo while tests ran,** because `test_docs.py` reads the README and `docs/`.
- **Caught before shipping:**
  - the link test failed because the README linked to `regression.md` before that file existed;
  - CI uses Python 3.14, so an unverified "Python 3.12+" in the README draft was corrected.
- **Labelled honestly:** two "rejected alternatives" in the study guide (DBSCAN, a vector database)
  weren't recorded decisions at the time, so the guide marks them as reasoning written afterwards.
- **A mistake of mine:** a loop that ran the browser tests echoed their arguments, which printed the
  local demo seed passwords into the agent's tool output. They are synthetic, in the git-ignored `.env`,
  and were never committed. Rotation is recommended. `seed_demo` only creates *missing* accounts, so
  re-running it doesn't change existing passwords. Instead, set the new `.env` values on the existing
  admin and demo accounts with `set_password` in `manage.py shell`.
- **Parallel sessions.** After an editor restart, two older Claude sessions were still running and
  doing the same Step 14 work. They rewrote `regression.md` and REQUIREMENTS rows, and appended
  duplicate entries here. It was found from unexpected file contents and process listings, and the user
  stopped both sessions. The files were then reconciled into one version, and the full suite was re-run
  with a single session.
- **Regression:** see [regression-week4.md](regression-week4.md).


# Week 5: advanced RAG, LLM agents and ML automation

## Step 0: setup and regression baseline

- `week5/` was copied from the git-tracked files of `week4/` only, with fresh local secrets. The Week 4 checklist, study guide, Loom script and regression evidence are renamed with a `-week4` suffix.
- Code comments point at the decisions in `docs/REQUIREMENTS.md`. Instead of editing the code (which would change a generated, byte-checked report), the Week 5 checklist carries Week 4's decisions and lessons over word for word.
- Baseline: backend 763 passed and 1 skipped, frontend 53, `verify_release` reproduced, all five browser suites green. The +2 tests compared with Week 4 were traced to the docs link test, which runs once per file in `docs/`.

## Step 1: document versions, update and delete re-indexing, metadata

- **Option A approved:** versions hold the text, and the document is the stable identity. Soft delete ("retire") instead of hard delete, to keep the audit trail.
- **User additions:**
  - every citation names its edition (v1 IDs unchanged for the frozen Week 4 set; `@v2` from version 2);
  - every evaluation run records a corpus snapshot and refuses a different corpus.
- **Migration designed for reversibility.** The first draft could not be undone: going backwards would have made the text fields required before they were refilled. It was fixed by refilling inside 0003 at the point where the fields become nullable. It is tested forward and back with Django's migration executor, and was applied to the real local database (13 chunks kept, IDs unchanged).
- **Week 4 tests changed, and why:**
  - the citation assertion now includes the new `document_id` and `version` fields (the requested contract addition);
  - two "search must never re-index" guards patched functions that had moved, so they were pointed at the functions that really embed now. Left as they were, they would have kept passing while guarding nothing.

  All other Week 4 tests pass unchanged, helped by keeping v1 passage IDs and v1 audit details in Week 4's form.
- **Audit migration checked with `sqlmigrate`:** only `choices` change (no-op SQL), so the append-only triggers survive.
- **CI caught a PostgreSQL-only failure.** The migration test first used a transactional test database, which pytest empties afterwards with `TRUNCATE`. On PostgreSQL the Week 2 append-only trigger blocks `TRUNCATE` on the audit table (correctly), so the test errored only in CI. Limiting the flush with `available_apps` hid the other apps from the migration loader. The fix: on PostgreSQL the test runs inside the normal rolled-back transaction (PostgreSQL can roll back schema changes, with constraints set to immediate); on SQLite it stays transactional. It was verified on local PostgreSQL 14 before pushing (281 tests across the assistant and audit files).

## Step 2: retrieval evaluation set, harness and baseline

- **Corpus B approved:** 6 new fictional admin policies plus cancellation v2. The user moved the v2 date into the past so v2 is clearly in force.
- **The user wrote 11 of the 23 evaluation questions.** Every quote was checked word for word, and the three unanswerable topics were confirmed absent (with near-misses noted: "charge" in parking, "opening hours" in rescheduling).
- **A duplicate caught by the user:** dev D06 shared its evidence sentence with evaluation A05/A06 (the Week 4 A1/A6 lesson). Because v2 changed only one sentence, any v2-only dev question would have shared it. With the user's approval, a second v2 change was made before freezing, and a test now forbids shared evidence sentences (shown to catch the old D06).
- **Order kept and provable:** freeze (`48fe63e`) → harness (`648092b`) → baseline run.
- **The guard caught a false positive:** Week 4's "no code reads the evaluation cases" pattern matched `retrieval_cases` as a substring. It was tightened to whole names, with a test that it still catches real readers.
- **The harness caught a gap in its own check:** a manifest pointing at the wrong file passed the per-file hash check. It now also checks each document's current edition against its expected hash.
- **Baseline finding:** ranking is near the ceiling even on the harder corpus (Recall@3 100%, MRR 0.97). The losses come from the shipped floor and top-k: as shipped, only 61% of answerable questions get their evidence (0% false retrieval). Correct top-1 chunks score as low as 0.608, while unanswerable questions score as high as 0.679. Reported to the user before choosing Step 3's headline measure.

## Step 3: retrieval improvements chosen on dev, before/after on the frozen set

- **Rules first, committed before any code (`91ab685`):** the grid (shrunk by the user to limit overfitting), the selection and tie order, champion/challenger decided on dev only, and a safety gate.
- **A test found a gap in the rules before any run:** "closest to 80" doesn't decide 40 against 120. The user chose the larger. A test now checks that the tie order separates all 4,800 configurations.
- **The headline measure was chosen by the user after the baseline and before Step 3.** The reports show counts beside percentages (the guardrail rests on 5 questions).
- **Result, reported as it came out:**
  - on dev, Week 4's retrieval had 6 of 12 hits but 1 false retrieval (D13), so it was ineligible under the rules;
  - every eligible configuration reached at most 4 of 12, and hybrid gave no gain;
  - the dev winner (semantic, chunk size 120, floor 0.74) scored **5 of 18 against 11 of 18** on the frozen set (worse), with the guardrail unchanged.

  Champion/challenger kept the champion, so the safety gate did not run. **A6 (measurable improvement) is not achieved on the primary measure,** and it is marked ◐, not ticked.
- **What it showed:** the bottleneck is the abstention gate, not the ranking. Correct paraphrased chunks and near-misses fall in the same cosine range. This is recorded as the finding for a next round.
- **Honesty fixes in the report generator:** the "why" paragraph first hard-coded values read off this run (D13, 0.74, "4 of 12"). It now computes them, so a regenerated report can't state something stale.
- **Verified on local PostgreSQL before pushing** (lesson from Step 1): 204 tests across the Step 1–3 files.

## Step 3 round 2: LLM relevance judge

- **The rules, the expanded dev set (10 more questions, 7 unanswerable near-misses) and the round-1 lesson were committed before any round-2 code (`f2eb222`).** The code was committed before the run.
- **The user asked whether the grid could beat the champion at all**, given the judge only removes. It can: every candidate floor (0.50–0.65) is below the champion's 0.70.
- **Dev result:** the judge on the top 3 candidates (f_low 0.60, top-k 3) got 10 of 15 hits with 0 of 10 false retrievals, against the champion's 6 of 15 and 3 of 10. The judge injection check passed (0 of 9 votes forced). Cost: about +5 s per question (median).
- **The safety gate failed on R6.** One run answered "Cancellations are free up to 24 hours before the start time." That is true and cited, but it contains the forbidden phrase "cancellations are free". By the pre-declared rule the challenger does not ship. The assistant's reading (a lexical false positive, not a followed injection) was reported to the user as an opinion, not applied.
- **Frozen set (second comparison, chooses nothing):** a tie, 11 of 18 for both. The judge rescued 5 low-scoring paraphrases, mostly the user's questions, and wrongly rejected 5 correct passages. By author: user 3 → 6 of 8, assistant 8 → 5 of 10. **A6 stays ◐.**
- **Two report bugs, found and fixed before committing:**
  - the round-2 section showed the dev decision alone ("the challenger ships") without the safety gate. Shipping now needs both, for that exact winner, and this is tested;
  - the safety gate was first run from the saved winner by hand, because the command would have re-run the selection. The command can now gate the saved winner directly (`--gate-saved-winner`).
- **Decision (user, 2026-11-02): option 1, keep the champion.** The gate rule was pre-declared and the frozen set shows no net gain, so there is no case for a post-result rule change. Recorded:
  - dev improvement: 6 → 10 of 15 hits, 3 → 0 of 10 false retrievals;
  - frozen tie: 5 paraphrases rescued, 5 easy passages wrongly rejected;
  - the R6 lexical false positive;
  - +5 s median latency.

  A6 stays ◐ with that explanation, and Week 5 moves on to Step 4.

## Step 4: generation evaluation, separately from retrieval

- **Order of commits:** the rules and the frozen answer key came first (`dce5cf6`), then the harness (`d9703e3`, 515 targeted tests passed on SQLite and PostgreSQL), and only then the real run. Nothing was tuned.
- **Answer key review by the user:** the user's negation rule (a match doesn't count if not / no / never / cannot / *n't* comes up to 2 words before it), with tests for "Guide dogs are not allowed" and "an interpreter is not free". U02 accepts "interpreter" or "translator"; U03 accepts instalments as well as installments, and drops "3 months".
- **Result** (23 questions × 3 seeds × 2 modes, 9 min 48 s; counts in [generation_eval.md](../backend/assistant/eval/generation_eval.md)):

  | | key fact correct | false abstention | answered but wrong | correct abstention |
  |---|---|---|---|---|
  | A: oracle context | 9 of 18 | 8 of 18 | 1 of 18 | 5 of 5 |
  | B: end to end | 7 of 18 | 10 of 18 | 1 of 18 | 5 of 5 |

- **The main finding: even when the right text is in front of it, the stack abstains on 8 of 18 answerable questions.** A breakdown of the reason behind each of the 40 abstaining runs in mode A:
  - in 12, the model itself said it didn't know;
  - in 28, the server's checks turned the answer down: 15 for groundedness below 0.61 (most scored 0.50), 7 for the number check, 6 for no citation or an unverified one.

  So the Week 4 safety checks cost answers as well as stopping bad ones. A06 is a clear case. End to end, it answered correctly ("From 1 October 2026"). With the oracle context, all 3 runs were turned down by the number check, at a groundedness of 0.0. In mode B, 33 of 45 abstaining runs were below the retrieval floor, which is the Step 3 problem.
- **Wrong answers:** both modes had 1 answered-but-wrong question each.
  - Mode A, A07: it said an interpreter can join the video call, but left out the patient app. It also cited the distractor, which accounts for all 3 citation-precision misses (54 of 57).
  - Mode B, A05: "The late cancellation fee is 20 euros." That's true but incomplete, because the fee applies from the second late cancellation. The key fact rule caught it.
- **Safety held:** every unanswerable question was abstained on in both modes.
- **By author:** the user's questions got 4 of 8 in A and 2 of 8 in B (retrieval lost U06 and U07, both area hints). The assistant's got 5 of 10 in both modes.
- **Not applied, by rule 4:** the groundedness threshold, the number check on dates, and the model's own "don't know" are candidates for a future dev round. No check was changed on these results.
