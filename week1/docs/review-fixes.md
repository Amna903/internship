# Week 1 review: fixes and evidence

Each mentor point is listed below with the change made, the test that shows it works, and what is still assumed.
"Before" means the new test run against the previous commit's code; "after" means the current code.

## 1. Admin search: an older response can no longer replace newer results

**Problem.** `app/admin/page.tsx` started a new `fetch` on each filter, search or page change and never cancelled the old one. When responses arrived out of order (a slow `?search=ol` finishing after `?search=olivia`), the stale list was shown last.

**Change.**
- `lib/api.ts`: `api()` takes an `AbortSignal`, and `adminApi.list(params, signal)` passes it to `fetch`. The new `isAbort()` helper detects a cancelled request.
- `app/admin/page.tsx`: the list request now lives in the effect. The effect's cleanup aborts the request and marks it stale, so only the latest request can call `setData` or `setError`. The stale flag also covers a response that arrives just before the abort.

**Evidence.** `frontend/tests/api.test.ts` contains "an aborted request rejects with AbortError instead of resolving stale data". Before: fails. After: passes.

**Assumption.** The client test checks that a request can be cancelled. It does not check the React effect wiring, which is reviewed by reading the code and was not run in an automated browser test.

## 2. Concurrent token refreshes share one in-flight request

**Problem.** Each request that got a 401 ran its own `POST /api/auth/user/refresh/`. Refresh tokens rotate and the old one is blacklisted (`ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`). So when two requests expired together, the second refresh presented a token that was already blacklisted, and that request failed even though the user was still signed in.

**Change.** `refreshSession()` in `lib/api.ts` keeps one module-level promise. Every 401 that arrives while a refresh is running waits for that same promise. When it settles:
- if the refresh succeeded, each waiting request retries **exactly once**;
- if it failed, each one rejects with its own original 401, and none retries.

The promise is cleared once it settles, so a later expiry starts a new refresh.

**Evidence** (`npm test` in `frontend/`):

| Test | Before | After |
|---|---|---|
| 3 parallel 401s cause 1 refresh, and all 3 retry and succeed (7 calls total) | fail | pass |
| A failed refresh rejects every waiting request with a 401 and no retries | fail | pass |
| A later refresh is not blocked by an earlier finished one | pass | pass |

**Assumption.** Two browser tabs can still each refresh at the same moment, because the shared promise is per tab. Coordinating across tabs (for example with `BroadcastChannel` or a lock) is not implemented.

## 3. Production configuration is explicit and fails clearly

**Change** (`backend/config/settings.py`). When `DJANGO_DEBUG=false`, the app refuses to start unless:
- `JWT_SIGNING_KEY` is set (it no longer silently falls back to `DJANGO_SECRET_KEY`), is at least 32 characters, is not a placeholder, and differs from the Django secret key;
- `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are set explicitly, with no localhost defaults and no `*`;
- `COOKIE_SECURE` is true.

These checks apply in every mode:
- `COOKIE_SAMESITE` is a single explicit setting (`Lax` or `Strict`) used by the JWT, session and CSRF cookies. Before, it was hard-coded in three places.
- Malformed values such as `COOKIE_SECURE=ture` or `ACCESS_TOKEN_MINUTES=ten` are reported as errors. Before, they silently became `false` or crashed with a bare `ValueError`.

All problems are collected and raised together in one `ImproperlyConfigured` message. Local development with `DJANGO_DEBUG=true` keeps its localhost defaults.

**Evidence.**
- `backend/tests/test_config.py` (14 tests) imports the settings in a fresh interpreter with a controlled environment and no `.env`. Before: 13 fail. After: 14 pass.
- Full backend suite: **139 passed**.
- Sample startup with only the secret key set:
  ```
  ImproperlyConfigured: Invalid configuration:
    - JWT_SIGNING_KEY is required when DJANGO_DEBUG is off.
    - DJANGO_ALLOWED_HOSTS is required when DJANGO_DEBUG is off.
    - CSRF_TRUSTED_ORIGINS is required when DJANGO_DEBUG is off.
  ```
- `manage.py check --deploy` with a complete production config reports only W004 (HSTS) and W008 (SSL redirect). Both are deliberate opt-ins (`SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`) because they depend on how TLS is terminated.

**Assumptions.** No real HTTPS deployment was run. The `Secure` cookie flag is asserted in tests but has not been observed over TLS.

## How to describe the same-origin proxy

The Next.js rewrite (`/api/*` → Django) means the browser sees one origin. As a result, cookies are first-party, CORS is not needed, and `SameSite=Lax` works without exceptions. **The proxy is a convenience, not a security boundary.** Anyone can call Django directly, and every endpoint still enforces its own authentication, ownership checks and CSRF. The demo should show this with a direct, unauthenticated `curl` to `/api/profiles/me/` and `/api/admin/profiles/` that returns 401/403.

## Implemented, observed, assumed

| | Implemented control | Observed result | Remaining assumption |
|---|---|---|---|
| Stale search | Abort and stale guard per request | Abort test passes | Effect wiring not browser-tested |
| Refresh race | One shared refresh, at most one retry per request | 3 refresh tests pass | Per tab only |
| Config | Fail-fast validation of secrets, hosts, origins and cookies | 14 config tests, 139 total | No real TLS deployment |

How to run the tests: `cd backend && .venv/bin/python -m pytest`, and `cd frontend && npm test`.
