# API examples

Base URL via the frontend proxy: `http://localhost:3000/api` (or Django directly: `http://127.0.0.1:8000/api`).
Responses below were captured from the running app. Unsafe methods need the CSRF header.

```bash
B=http://127.0.0.1:8000/api; J=jar.txt
curl -s -c $J $B/auth/csrf/                                   # sets csrftoken cookie
CSRF=$(awk '/csrftoken/{print $7}' $J)
```

## Member flow (JWT in HttpOnly cookies)

**Sign up** `POST /auth/signup/`
```bash
curl -s -b $J -c $J -H "X-CSRFToken: $CSRF" -H 'Content-Type: application/json' \
  -d '{"name":"Maya Example","email":"maya@example.test","password":"Correct-Horse-9-Battery"}' $B/auth/signup/
```
`201` → `{"user":{"id":7,"email":"maya@example.test","role":"user"}}`
Duplicate email → `400`
```json
{"error":{"code":"validation_error","message":"One or more fields are invalid.",
          "details":{"email":["An account with this email already exists."]}}}
```

**Login** `POST /auth/user/login/` body `{"email","password"}`
`200` → `{"user":{"id":2,"email":"amina.rahman@example.test","role":"user"},"access_expires_in":600}`
plus `Set-Cookie: hp_access=…; HttpOnly; SameSite=Lax; Path=/` and `hp_refresh=…; HttpOnly; Path=/api/auth/user/`.
Bad credentials (any reason) → `401` `{"error":{"code":"invalid_credentials","message":"Invalid email or password.","details":{}}}`
Too many attempts → `429` with `details.retry_after_seconds`.

**Own profile** `GET /profiles/me/` → `200`
```json
{"email":"amina.rahman@example.test","full_name":"Amina Rahman","date_of_birth":"1994-03-14","age_range":"",
 "contact_preference":"email","wellness_goals":["Walk 8,000 steps daily","Sleep 7+ hours"],"allergies":["Pollen"],
 "emergency_contact_name":"Tariq Rahman","emergency_contact_phone":"+1 555 010 0101",
 "emergency_contact_relationship":"Brother","lifestyle_notes":"Desk job, trying to move more.",
 "status":"active","created_at":"…","updated_at":"…"}
```
**Update** `PATCH /profiles/me/` (partial; `status`, `email`, timestamps are read-only and ignored)
```bash
curl -s -b $J -X PATCH -H "X-CSRFToken: $CSRF" -H 'Content-Type: application/json' \
  -d '{"lifestyle_notes":"updated"}' $B/profiles/me/
```
Invalid → `400` `{"error":{"code":"validation_error",…,"details":{"emergency_contact_phone":["Enter a valid phone number…"]}}}`
No cookie → `401` `not_authenticated` · expired/invalid token → `401` `token_not_valid` · missing CSRF → `403` `csrf_failed`.

**Delete own profile** `DELETE /profiles/me/` (CSRF header required) → `204`, empty body. The account stays and
can sign in; `GET` then returns `404` and `POST /profiles/me/` with `{"full_name": "…"}` creates a new profile (`201`).
Writes a `profile.deleted` audit event (actor + time, no profile data). Second delete → `404`; no CSRF → `403`.

**Refresh** `POST /auth/user/refresh/` (rotates; old refresh token becomes unusable) · **Logout** `POST /auth/user/logout/` → `{"detail":"Logged out."}`

## Admin flow (server-side session)

**Login** `POST /admin/login/` → `200` `{"user":{"id":1,"email":"admin@example.test","role":"admin"}}`
plus `Set-Cookie: hp_admin_session=…; HttpOnly; SameSite=Lax`. Member credentials → the same generic `401`.

**List** `GET /admin/profiles/?search=amina&status=active&ordering=-created_at&page=1&page_size=10`
```json
{"count":1,"next":null,"previous":null,"results":[{"id":1,"user_id":2,"email":"amina.rahman@example.test",
 "full_name":"Amina Rahman","age_range":"","contact_preference":"email","status":"active","created_at":"…"}]}
```
**Detail** `GET /admin/profiles/{id}/` → full profile + `account_active`, `last_login`, `deactivated_at`.
**Deactivate** `POST /admin/profiles/{id}/deactivate/` → profile with `"status":"deactivated"`; the member can no longer sign in and any live JWT stops working. `…/activate/` reverses it.
**Logout** `POST /admin/logout/` → `{"detail":"Logged out."}`; the session row is deleted.

Using a member JWT (or no credentials) on any `/admin/*` route → `401`.

## Week 2 additions: profile completion and audit events

**Completion** is part of every profile response (`GET/PATCH /profiles/me/`, admin detail). It is
computed by the server and read-only: sending `completion` or `completion_status` in a PATCH is ignored.
```json
"completion": {"status": "incomplete", "percent": 67, "missing_sections": ["emergency_contact"]}
```
Sections: `demographics` (name + DOB or age range), `emergency_contact` (name, relationship and phone),
`wellness_preferences` (contact preference + at least one goal).

**Filter admin list by completion** `GET /admin/profiles/?completion=incomplete&page_size=1`
```json
{"count":1,"next":null,"previous":null,"results":[{"id":6,"user_id":7,"email":"carlos.mendez@example.test",
 "full_name":"Carlos Mendez","age_range":"25-34","contact_preference":"email","status":"active",
 "completion_status":"incomplete","created_at":"…"}]}
```

**Audit trail** `GET /admin/audit-events/?action=profile.updated&profile=10&page=1&page_size=10` (admin session only, read-only)
```json
{"count":6,"next":"…&page=2","previous":null,"results":[{"id":26,"created_at":"…","action":"profile.updated",
 "action_label":"Profile updated","actor_email":"e2e1792471739@example.test","actor_role":"user","profile_id":10,
 "changed_fields":["allergies","contact_preference","date_of_birth","emergency_contact_name",
 "emergency_contact_phone","emergency_contact_relationship","wellness_goals"],
 "request_id":"b26b521bebc747399276ccf9d16829e7"}]}
```
Field **names** only, never values. `request_id` matches the `X-Request-ID` response header of the request that caused the event.
Actions: `profile.created`, `profile.updated`, `admin.login`, `admin.logout`, `admin.profile_viewed`,
`admin.profile_deactivated`, `admin.profile_activated`.
Unknown action → `400` `{"error":{"code":"validation_error",…,"details":{"action":["Must be one of: …"]}}}`.
Member JWT or no credentials → `401`. `POST` → `405` (append-only).


## Week 3: no-show estimate API (admin only)

`/api/v1/` is the API contract. `model_version` in every response names the model that produced the
answer. A retrained model with the same inputs keeps `/v1/`; changed inputs would mean `/v2/`.

**The caller supplies the appointment history counts; the API does not look them up.** There is no
patient lookup and no patient ID. The admin types every value, including `prior_appointments` and
`prior_no_shows`.

Same rules as every other admin route:
- an admin session cookie;
- the CSRF token in `X-CSRFToken`;
- a limit of 60 requests per minute per admin (`THROTTLE_PREDICTIONS`).

Each estimate writes an `admin.prediction_made` audit event holding the model version, **never the input values**.

### `POST /api/v1/predictions/no-show/`

```bash
curl -b jar.txt -H "X-CSRFToken: $CSRF" -H "Content-Type: application/json" \
  -d '{"lead_time_days": 14, "appointment_weekday": "tuesday", "appointment_hour": 10,
       "age_band": "35-44", "visit_type": "in_person", "booking_channel": "web",
       "reminder_sent": true, "prior_appointments": 4, "prior_no_shows": 0, "distance_km": 6.5}' \
  http://127.0.0.1:8000/api/v1/predictions/no-show/
```

`200`
```json
{"model_version": "no-show-1.0.0",
 "prediction": {"no_show_probability": 0.1279,
                "suggested_action": "standard_reminder",
                "suggested_action_label": "Standard reminder",
                "decision_threshold": 0.1688,
                "average_no_show_rate": 0.1645},
 "disclaimer": "Educational prototype trained on synthetic data. Estimates whether a fictional appointment may be missed, to help plan reminders. Not a medical assessment and not clinically validated."}
```
`suggested_action` is `extra_reminder_suggested` when `no_show_probability >= decision_threshold`,
otherwise `standard_reminder`. The output never says "risk".

**Inputs** (also returned by `GET /api/v1/models/no-show/` under `inputs`). All are required; only
`distance_km` may be `null`.

| field | type | allowed |
|---|---|---|
| `lead_time_days` | integer | 0–90 (days between booking and appointment) |
| `appointment_weekday` | text | monday … saturday (lower case) |
| `appointment_hour` | integer | 7–19 |
| `age_band` | text | 18-24, 25-34, 35-44, 45-54, 55-64, 65+ |
| `visit_type` | text | in_person, telehealth |
| `booking_channel` | text | web, phone, app |
| `reminder_sent` | boolean | true / false |
| `prior_appointments` | integer | 0–500 |
| `prior_no_shows` | integer | 0–500, and not more than `prior_appointments` |
| `distance_km` | number or `null` | 0–500 |

Validation is strict:
- `"14"`, `14.5` and `true` are not integers;
- `"yes"` and `1` are not booleans;
- unknown fields are rejected, so no name or email can be slipped in;
- every problem is reported in one response.

**Errors** (same envelope as the rest of the API):

| status | when | example `error` |
|---|---|---|
| 400 | invalid input | `{"code": "validation_error", "details": {"lead_time": ["Unknown field."], "appointment_hour": ["Ensure this value is less than or equal to 19."], "reminder_sent": ["Must be true or false (JSON boolean)."]}}` |
| 400 | more no-shows than appointments | `{"code": "validation_error", "details": {"prior_no_shows": ["Cannot be more than prior_appointments (2)."]}}` |
| 400 | broken, empty or non-object JSON | `{"code": "parse_error", "message": "Request body is not valid JSON."}` |
| 401 | not signed in as admin, including with a member's JWT | `{"code": "not_authenticated", "message": "Authentication credentials were not provided."}` |
| 403 | CSRF token missing | `{"code": "permission_denied", "message": "CSRF Failed: CSRF token missing."}` |
| 405 | wrong method | `{"code": "method_not_allowed"}` |
| 413 | body over 4 KB | `{"code": "request_too_large"}` |
| 429 | over 60/min | `{"code": "throttled", "details": {"retry_after_seconds": 42}}` |
| 503 | model missing, corrupted or built for another scikit-learn | `{"code": "model_unavailable", "message": "The estimate service is temporarily unavailable."}` (the reason is logged server-side only) |

### `GET /api/v1/models/no-show/`

The model card: version, estimator, disclaimer, input schema, decision rule, validation and test
metrics, training-data SHA-256, seed, library versions and file SHA-256. These are the values from
`ml/artifacts/no-show-1.0.0.json`.
