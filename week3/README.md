# HealthProfile: Week 3 (ML pipeline and prediction API), in progress

Week 3 builds on Week 2, which was copied into this folder with all its review fixes. Every Week 1 and Week 2 feature below still works, and the tests confirm it.

**Task:** an educational, synthetic **appointment no-show likelihood** model. It is not diagnostic and has no clinical validity.
**Progress:** [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) lists every line of the Week 3 brief, with its code, test and demo evidence.

## Week 3 model release

The served model is `backend/ml/artifacts/no-show-1.0.0.joblib`: one scikit-learn Pipeline holding
the input guard, the engineered features, preprocessing and the logistic regression together.
`no-show-1.0.0.json` sits next to it, recording:
- the seed and the dataset SHA-256
- the feature schema
- the decision threshold
- the metrics
- the exact library versions
- the file's SHA-256

Both files are committed, so the API works straight after cloning.

**Rebuild it** (the same files come out, see below):

```bash
cd backend
python -m ml.artifact
```

**What "reproducible" means here**, checked by `tests/test_ml_artifact.py`:

| Level | What matches | Where |
|---|---|---|
| 1 | Dataset SHA-256 | everywhere |
| 2 | Metrics and threshold in the metadata | everywhere (CI checks on Linux) |
| 3 | Predicted probabilities, within 1e-9 | everywhere |
| 4 | The `.joblib` file, byte for byte | same platform and library versions as the committed build (macOS arm64). Floating-point results can differ in the last bits across CPUs. |

**Safe loading** (`ml/inference.py`). The file is opened only after all of these checks pass, and any
failure becomes `ModelUnavailable`, which the API turns into a 503:
- both files exist;
- the metadata names this version and our exact feature schema;
- the installed scikit-learn is the exact version the model was saved with;
- the file's SHA-256 matches the metadata.

The SHA-256 check catches accidental corruption or mismatched files. It is not protection against a
deliberate attacker, because the fingerprint is stored in the `.json` next to the file. Real protection
comes from only loading our own committed file, never an uploaded one. That matters because joblib,
like pickle, can run code while loading.

**Output wording.** The estimate supports one low-cost action, so the API says
"Extra reminder suggested" or "Standard reminder". It never says "high risk", and the disclaimer is
always shown next to the suggestion.

**Prediction API**: `POST /api/v1/predictions/no-show/` (admin only). Sample request and response,
every input, and every error: [docs/API.md](docs/API.md#week-3-no-show-estimate-api-admin-only).
**The caller supplies the appointment history counts; the API does not look them up.**

**Dashboard.** Sign in as admin, then open **No-show estimate** in the top bar (`/admin/predictions`).
- "Fill example" buttons fill the form in one click. A backend test checks that each example really
  gives the result its label promises.
- The result shows the suggestion, the estimated chance, the average for comparison and the model
  version, with the disclaimer right beside it.
- Any edit clears the old result.

![No-show estimate page](docs/screenshots/w3-01-estimate-extra-reminder.png)

Real-browser check (17 checks, with backend and frontend running and `seed_demo` done; needs
`pip install playwright` and `python -m playwright install chromium`):

```bash
python e2e/run_week3_e2e.py "<admin password>" "<member password>" docs/screenshots
```

The browser check is not part of CI, because it needs both servers running. It was run locally on
2026-10-27: 17/17.

**Versions.** major = the inputs change (breaks callers) · minor = retrained on the same inputs ·
patch = metadata only.

---

# Week 2: Role-Based Health Profiles and Database Engineering

Week 2 builds on the Week 1 app (copied into this folder; everything in the Week 1 section below still works).
It has two parts:

1. **Role-Based Health Profiles and Database Engineering** (Full-Stack AI/ML track): profile completion
   status, audit events for profile edits and admin actions, new composite indexes with EXPLAIN evidence.
2. **CareConnect** (bonus, from the frontend brief): a directory for finding fictional wellness
   professionals and requesting an appointment. Frontend-only.

## Week 2 checklist: Role-Based Health Profiles and Database Engineering

| Requirement | How / where |
|---|---|
| User signup + JWT login; admins only via management command + session login | Kept from Week 1: `accounts/`, `adminpanel/`, `create_admin`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Profile sections: demographics (fictional), emergency contact, wellness preferences | `profiles/models.py`, edited on `/profile` |
| **Profile completion status** | `profiles/completion.py` (pure rules) → stored `completion_status` column, recomputed on every save; API returns `{status, percent, missing_sections}`; progress bar on `/profile`; admin filter `?completion=` |
| User-owned profile CRUD | `POST/GET/PATCH/DELETE /api/profiles/me/` (create, read, update, delete): always resolved from the token, there is no `/profiles/<id>` for members. Delete removes the profile, keeps the account, and is audited as `profile.deleted` |
| Admin-only listing/search | `GET /api/admin/profiles/?search=&status=&completion=&ordering=&page=` |
| **Audit events** for profile edits and admin actions, no secrets or sensitive payloads | `audit/` app: append-only `AuditEvent` (actor, role, action, profile, changed field **names**, request id). Recorded on signup, profile create/update, admin login/logout, profile view, deactivate/activate. `GET /api/admin/audit-events/`; "Activity" table on the admin profile page |
| Pagination, filtering, migrations, API docs | DRF pagination; filters validated (bad values → 400); migrations `profiles/0002_completion_status` (with data backfill) and `audit/0001_initial`; Swagger at `/api/docs/`, examples in [docs/API.md](docs/API.md) |
| Hashed passwords, JWT expiry/refresh, secure token storage, CSRF for admin sessions | Argon2id; 10-min access / 7-day rotating single-use refresh in HttpOnly cookies; CSRF on every unsafe route |
| Normalized relations, FKs, unique/indexed fields, composite indexes justified by query patterns | `User 1—1 HealthProfile 1—* AuditEvent`; composite indexes `(status, created_at)`, `(completion_status, created_at)`, `(profile, created_at)`, `(action, created_at)`. Each comment in the model names the query it serves |
| No horizontal privilege escalation | Members only reach `/profiles/me/`; tests `test_profiles.py`, `test_user_auth.py` |
| Validate input, hide sensitive fields, test role boundaries | Serializer validation; `completion` and `status` read-only; audit stores no values (test `test_values_and_secrets_are_never_stored`) |
| **Acceptance:** user can't reach another profile or admin routes | `test_user_jwt_gives_no_admin_privileges`, `test_users_and_anonymous_cannot_read_the_audit_log`, browser checks |
| **Acceptance:** admin session and user JWT paths stay distinct | `test_admin_session_does_not_authenticate_user_endpoints`, `DEFAULT_AUTHENTICATION_CLASSES = []` |
| **Acceptance:** migrations, indexes and EXPLAIN evidence | [docs/explain-postgres.md](docs/explain-postgres.md): completion list 5.5 ms → 0.20 ms, audit history 7.0 ms → 0.08 ms (PostgreSQL, 20k profiles / 60k events) |

![Audit trail on the admin profile page](docs/screenshots/w2-08-admin-audit-trail.png)

**Evidence:** [Week 2 requirement checklist](docs/REQUIREMENTS-week2.md) · [review fixes](docs/review-fixes.md) · CI: `.github/workflows/ci.yml`

**Verification (run by Claude Code in development; CI re-runs it on every push):** `pytest` 192 passed + 1 PostgreSQL-only skip (SQLite), full suite also on PostgreSQL 14.21 · `npm test` 37 passed · browser runs from **before** the review fixes, not re-run since: `e2e/run_audit_e2e.py` 15/15 (incl. delete → recreate) ·
`e2e/run_e2e.py` 24/24 (Week 1 flows still work) · `e2e/run_week2_e2e.py` 33/33.

```bash
# Real-browser check of completion + audit (backend and frontend running, seed_demo done)
python e2e/run_audit_e2e.py "<admin password>" docs/screenshots
python backend/manage.py explain_queries     # query plans for every indexed lookup
```

---

## CareConnect checklist (bonus, frontend brief)

![Directory](docs/screenshots/w2-01-directory.png)


| Requirement | Where |
|---|---|
| `/professionals` and `/professionals/[id]` routes (App Router) | `frontend/app/professionals/` |
| Single typed JSON source (professionals, specialties, locations, fees, availability) | `frontend/data/professionals.json` + `frontend/lib/professionals.ts` |
| JSON validated at import time (unknown references, bad times, duplicate ids, online-only + in-person…) | `validateDirectory()` in `lib/professionals.ts` |
| Multi-criteria search + filters (text, specialties (multi), location, visit type, day, max fee) | `components/professionals/ProfessionalFilters.tsx`, `lib/filters.ts` |
| Sorting (name, fee ↑/↓, experience) | `lib/filters.ts` |
| Empty state + one-click reset | `app/professionals/page.tsx` |
| Query-parameter persistence (refresh / share / back-forward) | URL is the filter state |
| Multi-step appointment request (4 steps, validation, Previous/Next, review, no real booking) | `components/professionals/AppointmentRequestForm.tsx`, `lib/appointment.ts` |
| Draft persisted locally (survives refresh) | `localStorage` key `hp.appointmentDraft.v1.<id>` |
| Favourites with local persistence + `/saved` page | `lib/favorites.ts`, `app/saved/` |
| Accessible navigation menu (skip link, `aria-current`, mobile disclosure, Escape) | `components/ui/SiteNav.tsx`, `components/ui/Layout.tsx` |
| Reusable typed components: Card, Filter, FormField, Stepper, Badge, Layout | `frontend/components/ui/` |
| Shared design tokens / CSS variables | top of `frontend/app/globals.css` |
| Invalid professional id → not-found UI (HTTP 404) | `app/professionals/[id]/not-found.tsx` |
| Client/server boundaries + state-management choice documented | [docs/WEEK2.md](docs/WEEK2.md) |

**Acceptance checks**, verified in a real browser by `e2e/run_week2_e2e.py` (33/33 passing):
direct navigation to a profile URL ✓ · filters combine and reset, URL reflects them ✓ · form errors are
accessible (error summary with focus, `aria-invalid`, `aria-describedby`) ✓ · draft survives refresh ✓ ·
mobile layout without horizontal scroll ✓.

## Run Week 2

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000/professionals
```
(The backend is only needed for the Week 1 member/admin pages; see "Quick start" below.)

## Week 2 tests

```bash
cd frontend
npm test               # 33 unit tests (Vitest): data validation, filters, URL round-trip, form rules
npm run typecheck
npm run build          # also fails if data/professionals.json is invalid

# Real-browser acceptance run (needs: pip install playwright && playwright install chromium)
npm run build && npm start      # in one terminal
python ../e2e/run_week2_e2e.py http://127.0.0.1:3000 ../docs/screenshots
```

| | |
|---|---|
| ![Form errors](docs/screenshots/w2-04-form-errors.png) | ![Mobile](docs/screenshots/w2-06-mobile.png) |

## Week 2 limitations

- Favourites and drafts live in this browser only (`localStorage`); they are not tied to the Week 1 account
  and don't sync across devices. Intentional for this week: Week 3 adds an API.
- Availability is a weekly template, not real dated slots, and nothing prevents double requests.
- Search is a simple substring match across a 16-item list; it would move server-side with real data.
- On small screens the filter panel is long; a collapsible "Filters" drawer would be the next improvement.

---

# Week 1: role-based profile builder

Role-based HealthTech profile app with **two independent authentication systems**:

- **Members** sign up themselves and manage only their own wellness profile. Auth: short-lived **JWT in HttpOnly cookies**.
- **Admins** are provisioned by a command (no self-registration) and review profiles. Auth: **server-side sessions**.

> Educational prototype. All data is synthetic. It stores wellness preferences, **not** medical records, and gives no medical advice.

![Admin dashboard](docs/screenshots/04-admin-dashboard.png)

## Features

| Member | Admin |
|---|---|
| Sign up (name, email, password), sign in/out | Sign in/out (session), no signup path exists |
| View/edit own profile: name, DOB *or* age range, contact preference, wellness goals, allergies, emergency contact, lifestyle notes | List profiles with search, status filter, sorting, pagination |
| Silent token refresh, field-level validation errors | View full profile detail |
| Cannot see or address anyone else's data | Deactivate / reactivate a profile (blocks sign-in, kills live tokens) |

## Stack

Django 5.2 + Django REST Framework · SimpleJWT · PostgreSQL (SQLite fallback) · Next.js 15 (App Router, TypeScript) · pytest · Playwright (E2E, run manually).
Rationale and trade-offs: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

Requirements: Python 3.11+, Node 20+. PostgreSQL is optional (SQLite is used if `DATABASE_URL` is unset).

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/init_env.py        # creates .env with fresh random secrets, prints demo passwords ONCE
python manage.py migrate
python manage.py seed_demo        # demo admin + 6 synthetic members (idempotent)
python manage.py runserver        # http://127.0.0.1:8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:3000  (proxies /api/* to :8000)
```

Demo accounts come from the values `init_env.py` printed (also in your local, git-ignored `backend/.env`):
admin `admin@example.test`; members such as `amina.rahman@example.test`.

**PostgreSQL:** `docker compose up -d db`, then set
`DATABASE_URL=postgres://healthprofile:healthprofile@localhost:5432/healthprofile` in `backend/.env` and re-run `migrate` + `seed_demo`.

**Create another admin** (password via env var or prompt, never a CLI argument):
```bash
ADMIN_PASSWORD='a-strong-passphrase' python manage.py create_admin --email you@example.test
```

## Tests

```bash
cd backend && pytest        # 155 tests (125 Week 1 + 30 Week 2), ~2 s; also green on PostgreSQL
cd frontend && npm run typecheck && npm run build
```

Covered: valid/invalid signup, duplicate email (case-insensitive), password hashing, expired / tampered /
`alg:none` / wrong-type JWTs, refresh rotation and replay, logout revocation, cross-user access, admin-only
endpoints, user JWT ⇒ no admin access, admin session logout, CSRF on every state-changing route, rate limiting,
DB-level constraints and index usage, validation, and the unified error format.
A 24-step real-browser run (signup → edit → admin search → deactivate → blocked login → reactivate, forged
client state, mobile layout) lives in `e2e/run_e2e.py`; screenshots are in `docs/screenshots/`. To rerun it
(`pip install playwright`, both servers up, `seed_demo` done):
```bash
# backend with a relaxed login limit, because one run uses ~8 of the 10/min allowed by default
THROTTLE_LOGIN=1000/min python manage.py runserver
python e2e/run_e2e.py "<admin password>" docs/screenshots
```

## API

Interactive docs: **http://127.0.0.1:8000/api/docs/** (Swagger UI) · schema at `/api/schema/`.
Examples with request/response bodies: [docs/API.md](docs/API.md).

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /api/auth/csrf/` | none | Sets the `csrftoken` cookie |
| `POST /api/auth/signup/` | none | Create a member |
| `POST /api/auth/user/login/` | none | Member login → JWT cookies |
| `POST /api/auth/user/refresh/` | refresh cookie | Rotate tokens |
| `POST /api/auth/user/logout/` | none | Revoke refresh token, clear cookies |
| `GET/PATCH/POST/DELETE /api/profiles/me/` | member JWT | Own profile only (full CRUD) |
| `POST /api/admin/login/` | none | Admin login → session cookie |
| `POST /api/admin/logout/` | none | Destroy session |
| `GET /api/admin/me/` | admin session | Who am I (used by the UI on every load) |
| `GET /api/admin/profiles/` | admin session | List; `?search=&status=&completion=&ordering=&page=&page_size=` |
| `GET /api/admin/audit-events/` | admin session | Audit trail; `?action=&profile=&page=&page_size=` (read-only) |
| `GET /api/admin/profiles/{id}/` | admin session | Detail |
| `POST /api/admin/profiles/{id}/deactivate/` · `/activate/` | admin session | Change status |

All unsafe requests need `X-CSRFToken` (value of the `csrftoken` cookie). Errors share one shape:
`{"error": {"code": "...", "message": "...", "details": {...}}}`.

## Project layout

```
backend/
  config/       settings (env-driven), error envelope, urls
  accounts/     User model, JWT-cookie auth, signup/login/refresh/logout, create_admin
  profiles/     HealthProfile model, completion rules, /profiles/me, seed_demo, explain_queries
  audit/        append-only AuditEvent model, record_event() service (Week 2)
  adminpanel/   admin session auth + dashboard endpoints
  tests/        pytest suite
frontend/       Next.js app (member pages, /admin pages, lib/api.ts)
  app/professionals/, app/saved/   Week 2 routes
  components/ui/                   Week 2 reusable components
  data/, lib/                      directory JSON, filters, form model, local storage
  tests/                           Vitest unit tests
e2e/            run_e2e.py (Week 1), run_week2_e2e.py (Week 2)
docs/           WEEK2.md, ARCHITECTURE.md, API.md, ai-workflow.md, explain-postgres.md, screenshots/
```

## Security notes

Secrets only via environment variables (`backend/.env.example` is the template; real `.env` is git-ignored and was never committed).
Argon2id hashing · HttpOnly/Secure/SameSite cookies · CSRF on all unsafe routes · throttled auth endpoints ·
generic login errors (no enumeration) · role stored server-side and checked on every request · DB CHECK/UNIQUE constraints.
See "Known limitations" in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for what this prototype deliberately does not do.
