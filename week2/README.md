# HealthProfile: Week 2 (professional directory)

Week 2 builds on the Week 1 app (copied unchanged into this folder, so everything below still works) and adds
**CareConnect**: a multi-page directory for finding fictional wellness professionals and requesting an
appointment. All Week 2 features are frontend-only and need no backend.

![Directory](docs/screenshots/w2-01-directory.png)

## Week 2 feature checklist

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
cd backend && pytest        # 125 tests, ~2 s; also green on PostgreSQL 16
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
| `GET/PATCH/POST /api/profiles/me/` | member JWT | Own profile only |
| `POST /api/admin/login/` | none | Admin login → session cookie |
| `POST /api/admin/logout/` | none | Destroy session |
| `GET /api/admin/me/` | admin session | Who am I (used by the UI on every load) |
| `GET /api/admin/profiles/` | admin session | List; `?search=&status=&ordering=&page=&page_size=` |
| `GET /api/admin/profiles/{id}/` | admin session | Detail |
| `POST /api/admin/profiles/{id}/deactivate/` · `/activate/` | admin session | Change status |

All unsafe requests need `X-CSRFToken` (value of the `csrftoken` cookie). Errors share one shape:
`{"error": {"code": "...", "message": "...", "details": {...}}}`.

## Project layout

```
backend/
  config/       settings (env-driven), error envelope, urls
  accounts/     User model, JWT-cookie auth, signup/login/refresh/logout, create_admin
  profiles/     HealthProfile model, /profiles/me, seed_demo, explain_queries
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
