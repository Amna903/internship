# AI workflow

> **Owner note:** sections marked ✏️ must be filled in with *your own* prompts and observations before
> you submit. This file is graded on your real process; do not leave placeholders and do not paste
> text you cannot explain on camera. Everything not marked ✏️ was recorded from the actual build session.

## Tools used
- Claude (agentic coding session: file edits, shell, test runs) for implementation. ✏️ add any other tool you actually used (IDE assistant, prompt refiner, MCP, skills).

## 1. Prompt iterations ✏️

Assignment requires **at least two iterations** and how the outputs differed. Template:

| | Iteration 1 (initial) | Iteration 2 (refined) |
|---|---|---|
| Prompt | ✏️ paste exact text | ✏️ paste exact text |
| What was wrong with the output | ✏️ | |
| What you changed in the prompt and why | | ✏️ (e.g. added role, constraints, file scope, acceptance tests) |
| Observed difference | | ✏️ |

Context for your own writing: the prompt that drove this build set a role ("senior full-stack developer"),
an explicit goal ("both roles completely workable as in the guide"), and asked for stack justification.
Things a *refined* prompt added in practice were: naming the two auth mechanisms explicitly, requiring tests as the
definition of done, and forbidding secrets in the repo. Decide for yourself what your iteration 1 vs 2 really were.

## 2. Blast-radius control (what was actually done)

- **Scoped by module**: backend split into `accounts/`, `profiles/`, `adminpanel/`; each change touched one app plus its tests.
- **Tests as the safety net**: 125 tests written alongside the code; every fix re-ran the whole suite, so a change that broke another area was caught in seconds.
- **Small, reviewable commits** (backend, then frontend) rather than one dump.
- **Explicit allow-list for auth**: `DEFAULT_AUTHENTICATION_CLASSES = []` so no view can silently inherit an authenticator.
- **Secrets isolated**: `.env` git-ignored; verified with `git ls-files` that no `.env`, `db.sqlite3` or venv is tracked.
- **Read-only evidence before claims**: query plans and the browser run were executed, not assumed.

## 3. Manual security review checklist (do this yourself and tick it)

- [ ] `grep -rn "SECRET\|PASSWORD" --include=*.py backend/ | grep -v tests` shows only env lookups, no literals.
- [ ] `git log -p | grep -i "password\|secret"` shows nothing real (only `.env.example` placeholders).
- [ ] Signup serializer has no `role` field; only `create_admin` / `seed_demo` create admins.
- [ ] Every view declares `authentication_classes` and `permission_classes` (read `*/views.py`).
- [ ] `PATCH /profiles/me/` cannot change `status`, `email`, `user` (see `test_read_only_and_foreign_fields_are_ignored`).
- [ ] No endpoint takes a profile id for members (only `/me/`).
- [ ] Login errors are generic; cookies are HttpOnly; CSRF required on POST/PATCH.
- [ ] Try it by hand: log in as a member, then `curl` an `/api/admin/` route with that cookie (expect 401).

## 4. Context management ✏️
Describe what you did: e.g. kept the assignment PDFs + clarification text as the single source of truth, worked
one module at a time, summarised state in `docs/ARCHITECTURE.md`, avoided re-pasting large files. ✏️ add specifics (and any skills/agents/MCP you used).

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
- **Regression guard:** the Playwright run (it fails immediately if any API call loops). ✏️ consider adding a CI smoke test.
- **Lesson:** unit tests passed while integration was broken; only an end-to-end run through the real proxy found it.

### Bug 3 (tooling): `pkill -f` killed my own shell
Matching a process name that also appeared in the command line terminated the shell (exit 144) and skipped the commit that followed. Fix: select PIDs with `ps | grep "[r]unserver"` and verify state before retrying.

### Test-helper bug (not app code)
`Browser.get()` did not accept query params, causing 3 false failures. Fixed the helper, not the app: always decide *which side* is wrong before "fixing" a failing test.

## 6. Verification performed
- `pytest`: 125 passed on SQLite and on PostgreSQL 16.
- `npm run typecheck` + `npm run build`: clean.
- Playwright: 24/24 checks (both roles, forged client state, deactivation, mobile layout).
- `EXPLAIN ANALYZE` before/after index: 2.9 ms vs 14.1 ms at 20k rows (`docs/explain-postgres.md`).
- Not verified: `docker compose` (no Docker daemon in the build sandbox); HTTPS cookie behaviour with `Secure` (tests force `COOKIE_SECURE=true` and assert the flag, but no real TLS run).

## 7. What I'd do differently ✏️
Write your own. Honest candidates: add a CI pipeline running pytest + Playwright; `jti` denylist for instant access-token revocation; Redis-backed throttling; `pg_trgm` for search.
