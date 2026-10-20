# HealthProfile: Week 3 (ML pipeline and prediction API)

Week 3 builds on Week 2 (copied into this folder; every Week 1 and Week 2 feature below still works) and adds
an **educational appointment no-show model**: a reproducible scikit-learn pipeline trained on synthetic data,
served by a versioned, validated API, and shown in the admin dashboard.

> Not a diagnostic tool. It estimates whether a *fictional appointment* may be missed (to plan reminders),
> was trained on synthetic data, and has no clinical validity.

![No-show estimate in the admin dashboard](docs/screenshots/w3-01-no-show-estimate.png)

## Week 3 checklist

| Requirement | How / where |
|---|---|
| Synthetic or approved non-sensitive data; provenance, license, schema, limitations | Seeded generator `backend/ml/data.py`; [docs/DATA_CARD.md](docs/DATA_CARD.md) |
| Exploratory analysis, missing values, train/validation/test split | `python -m ml.eda` → [backend/ml/reports/eda.md](backend/ml/reports/eda.md); median imputation + missing indicator (fit on train only); patient-grouped 60/20/20 split |
| Baseline + at least one improved scikit-learn model, non-diagnostic task | Floor (`DummyClassifier`), baseline (logistic, raw inputs), improved (logistic + engineered features; gradient boosting) |
| Compare with appropriate metrics, error analysis, no leakage | PR-AUC / ROC-AUC / Brier, threshold metrics, per-group errors, calibration: [backend/ml/reports/metrics.md](backend/ml/reports/metrics.md). Leakage: `checked_in` and ids excluded, patient-grouped split, preprocessing inside the pipeline, test scored once (all tested) |
| Versioned inference endpoint + output in the dashboard | `POST /api/v1/predictions/no-show/`, `GET /api/v1/models/no-show/`; admin page `/admin/predictions` |
| No clinical claims | Disclaimer in API response, UI and docs |
| Preprocessing and model saved together, reproducibly | One sklearn `Pipeline` in `ml/artifacts/no-show-1.0.0.joblib` + metadata JSON (data hash, metrics, seed, library versions, artifact SHA-256) |
| Validate inference schema; malformed and out-of-range input | Strict DRF serializer: unknown keys, types, ranges, `prior_no_shows ≤ prior_appointments`, nullable distance; broken JSON → 400 |
| Pinned dependencies, recorded seeds, class imbalance and bias documented | Exact pins in `backend/requirements.txt`; seed 42 in `ml/config.py` and metadata; [docs/DATA_CARD.md](docs/DATA_CARD.md) |
| **Acceptance:** training script reproduces the artifact | `pytest -m slow` retrains in a fresh process and asserts the same data hash, metrics and artifact SHA-256 |
| **Acceptance:** inference returns validated output + model version | `{"model_version": "no-show-1.0.0", "prediction": {...}, "disclaimer": ...}` (tests in `tests/test_predictions_api.py`) |
| **Acceptance:** README has metrics, dataset limitations, sample request/response | Below |

### Metrics (test set: 3,967 appointments of patients never seen in training, 16.5% no-show)

| Model | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|
| Floor: always predict the average | 0.500 | 0.165 | 0.138 |
| Baseline: logistic regression, raw inputs | 0.705 | 0.358 | 0.124 |
| **Served: logistic regression + engineered features** | **0.712** | **0.371** | **0.123** |
| Gradient boosting + engineered features | 0.707 | 0.356 | 0.124 |
| Oracle ceiling (the generator's true probability) | 0.717 | 0.372 | 0.123 |

Threshold 0.236 (picked on validation by F1): precision 0.365, recall 0.452, F1 0.404.
The served model is within 1% of the best achievable ROC-AUC; what's left is noise in the synthetic data.
Design notes and error analysis: [docs/WEEK3.md](docs/WEEK3.md).

### Dataset limitations (short version)

Synthetic: the model can only learn the effects we planted, so the metrics say nothing about real clinics.
No time dimension, missingness is random by construction, and age is a planted driver: young people are
flagged far more often (false-positive rate 29.5% for 18–24 vs 4.6% for 55–64), so the output is only fit
for supportive actions like an extra reminder. Full list: [docs/DATA_CARD.md](docs/DATA_CARD.md).

### Sample request / response

```bash
curl -b jar.txt -H "X-CSRFToken: $CSRF" -H 'Content-Type: application/json' \
  -d '{"lead_time_days":14,"appointment_weekday":"tuesday","appointment_hour":10,"age_band":"35-44",
       "visit_type":"in_person","booking_channel":"web","reminder_sent":true,
       "prior_appointments":4,"prior_no_shows":0,"distance_km":6.5}' \
  http://127.0.0.1:8000/api/v1/predictions/no-show/
```
`200` (header `X-Request-ID: a7a6d9c4…`)
```json
{"model_version": "no-show-1.0.0",
 "prediction": {"no_show_probability": 0.0829, "risk_band": "low",
                "decision_threshold": 0.2363, "baseline_no_show_rate": 0.1664},
 "disclaimer": "Educational prototype trained on synthetic data. Estimates appointment attendance only; not a medical assessment and not clinically validated."}
```
`risk_band`: `high` at or above the threshold, `medium` above the average no-show rate, otherwise `low`.

Errors (same envelope as the rest of the API):
- unknown key → `400 {"error":{"code":"validation_error",…,"details":{"lead_time":["Unknown field."]}}}`
- out of range → `400 … {"appointment_hour":["Ensure this value is greater than or equal to 7."]}`
- broken JSON → `400 parse_error` · member/anonymous → `401` · no CSRF → `403` · over 60/min → `429`
- model missing, tampered or built for another scikit-learn → `503 model_unavailable`

### Run and test Week 3

```bash
cd backend
pip install -r requirements-dev.txt     # includes the pinned ML stack
python manage.py migrate && python manage.py seed_demo
python -m ml.eda && python -m ml.train  # optional: the trained model is committed; this rebuilds it identically
python manage.py runserver
pytest                                  # 196 tests (incl. the slow full-retrain reproducibility check)

cd ../frontend && npm install && npm run dev   # http://localhost:3000/admin/predictions (sign in as admin)

# Real-browser check (both servers up)
python e2e/run_week3_e2e.py "<admin password>" docs/screenshots   # 13 checks
```

**Verification:** `pytest` 196 passed · `run_week3_e2e.py` 13/13 · earlier browser suites still green
(`run_e2e.py` 24/24, `run_audit_e2e.py` 15/15, `run_week2_e2e.py` 33/33) · `npm run typecheck`, `npm test` 33/33, `npm run build` clean.

---

# Week 2

Week 2 built on the Week 1 app. It has two parts:

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

**Verification:** `pytest` 155 passed · `e2e/run_audit_e2e.py` 15/15 (incl. delete → recreate) ·
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
| `POST /api/v1/predictions/no-show/` | admin session | Week 3: no-show estimate (validated input, versioned output) |
| `GET /api/v1/models/no-show/` | admin session | Week 3: model card (version, metrics, schema) |
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
  ml/           Week 3: data generator, features, train, eda, inference; artifacts/ and reports/
  predictions/  Week 3: versioned no-show API (serializer, views)
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
