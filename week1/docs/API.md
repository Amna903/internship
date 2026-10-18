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
