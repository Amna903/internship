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


## Week 4: clusters and the clinic policy assistant (admin only)

Every example below was **captured from the running server** on 2026-11-01 (local model `llama3.2:3b`,
embeddings `nomic-embed-text`). The upload and approve examples ran against a **copy** of the local
database, so the real document index was not changed. Long responses are trimmed where marked `…`.

Same rules as the Week 3 routes: an admin session cookie, the CSRF token in `X-CSRFToken` on writes,
and the error envelope `{"error": {"code", "message", "details"}}`. A member's JWT gets 401; a missing
CSRF token gets 403. The prediction endpoints above are unchanged: Week 4 still serves `no-show-1.0.0`.

### `GET /api/v1/clusters/`

Reads the committed Step 7–8 results; no clustering runs during a request. Limit: 60 per minute.
Each call writes an `admin.clusters_viewed` audit event with the results version.

The PCA points and cluster descriptions come from the **positive-control data** (planted habits,
fictional) and are labelled as such. For the real synthetic patients the response gives the verdict (no
structure found) and the clusters K-Means formed anyway, under `misleading_clusters`. `methods` compares
K-Means with Ward.

`200` (trimmed)
```json
{
 "results_version": "2f0ceb1443dd",
 "results_sha256": "2f0ceb1443dd3e02…",
 "disclaimer": "Exploratory clustering of synthetic, fictional engagement data. Clusters describe booking patterns, not categories of people, and are never a medical or personal assessment.",
 "control": {
  "label": "Positive-control data with planted habits (fictional), not real patients",
  "patients": 1500,
  "k": 3,
  "pca_variance": [
   0.35137421309014355,
   0.2591676404604878
  ],
  "ari": 0.51786239486612,
  "recovery": "partially recovered",
  "clusters": [
   {
    "cluster": 0,
    "size": 420,
    "share": 0.28,
    "profile": {
     "mean_lead_time": 9.32425344496773,
     "telehealth_share": 0.7531843421129135,
     "phone_share": 0.12308346415489271,
     "app_share": 0.7331666812023955,
     "mean_hour": 16.320582592011164,
     "appointments": 3.9571428571428573
    },
    "description": "Books in the app more often; more telehealth visits; later appointment times.",
    "most_common_planted_habit": {
     "habit": "telehealth app users",
     "share": 0.85
    }
   },
   "… 2 more"
  ],
  "points": [
   {
    "x": 0.652,
    "y": -0.272,
    "cluster": 1,
    "planted_habit": "mixed"
   },
   {
    "x": -1.393,
    "y": -0.516,
    "cluster": 0,
    "planted_habit": "telehealth app users"
   },
   "… 1,498 more"
  ]
 },
 "real": {
  "patients": 5000,
  "k": 3,
  "structure_found": {
   "k-means": false,
   "agglomerative (Ward)": false
  },
  "silhouette": 0.16924811339778348,
  "baseline_bar": 0.17317526382248177,
  "appointments_share_of_split": 0.627879274329328,
  "misleading_clusters": [
   {
    "cluster": 0,
    "size": 2377,
    "share": 0.4754,
    "description": "Fewer appointments in the data; books closer to the date."
   },
   "… 2 more"
  ]
 },
 "methods": [
  {
   "method": "k-means",
   "real_structure_found": false,
   "real_silhouette": 0.16924811339778348,
   "real_baseline_bar": 0.17317526382248177,
   "real_chosen_k": 3,
   "control_chosen_k": 3,
   "control_ari": 0.51786239486612
  },
  {
   "method": "agglomerative (Ward)",
   "real_structure_found": false,
   "real_silhouette": 0.12959287489016755,
   "real_baseline_bar": 0.16331546922263412,
   "real_chosen_k": 3,
   "control_chosen_k": 2,
   "control_ari": 0.17927215231236512
  }
 ]
}
```

| status | when | `error.code` |
|---|---|---|
| 401 / 403 | not signed in as admin | `not_authenticated` / `permission_denied` |
| 429 | over 60/min | `throttled` |
| 503 | the results file is missing or damaged (reason logged server-side only) | `clusters_unavailable` |

### `GET /api/v1/assistant/status/`

The assistant's configuration. It never calls the model, and it never includes the server address.

`200` (output schema trimmed)
```json
{
 "provider": "local (Ollama)",
 "model": "llama3.2:3b",
 "embedder": "nomic-embed-text:latest",
 "temperature": 0.1,
 "max_output_tokens": 512,
 "context_tokens": 4096,
 "timeout_seconds": 60.0,
 "context_strategy": "System prompt and question always included; ranked passages fill the rest, lowest ranked dropped first. Token counts are approximate (4 characters per token) with a 20% safety margin.",
 "limits": {
  "question_chars": 500,
  "answer_chars": 1200,
  "citations": 4
 },
 "cost": {
  "local_usd_per_call": 0.0,
  "illustrative_hosted_usd_per_1k_tokens": {
   "input": 0.0005,
   "output": 0.0015
  }
 },
 "data_policy": "Only approved fictional clinic policies and the question reach the model; obvious identifiers in questions are redacted first. The model runs locally.",
 "output_schema": "{ … JSON schema: answer, citations, refused … }"
}
```

### `POST /api/v1/assistant/ask/`

```bash
curl -b jar.txt -H "X-CSRFToken: $CSRF" -H "Content-Type: application/json" \
  -d '{"question": "How many times can I reschedule?"}' \
  http://127.0.0.1:8000/api/v1/assistant/ask/
```

The order is fixed:
1. validate the question (1–500 characters);
2. redact obvious identifiers;
3. **refuse medical questions before any retrieval or model call**;
4. retrieve approved passages above the similarity floor;
5. if nothing clears the floor, return `insufficient_information` **without calling the model**;
6. otherwise call the model and verify its reply on the server.

**The server decides the status, not the model.** The model returns only `answer`, `citations` and
`refused`. An answer is shown only if every citation points to a passage it was given, each quote is in
that passage, every number is in the quotes, and the polarity and groundedness checks pass. `reason` is
one of a few public codes; the internal reason stays in the logs.

Limit: 10 per minute. Each call writes an `admin.assistant_asked` audit event holding the status and the
question's length, **never the question text**.

**Answered** `200`
```json
{
 "status": "answered",
 "answer": "An appointment can be rescheduled at most twice.",
 "citations": [
  {
   "passage_id": "rescheduling.md#0",
   "quote": "Each appointment can be rescheduled at most twice;",
   "source": "rescheduling.md"
  }
 ],
 "sources": [
  {
   "passage_id": "rescheduling.md#0",
   "source": "rescheduling.md",
   "similarity": 0.704
  }
 ],
 "reason": null,
 "stale_chunks_skipped": 0,
 "usage": {
  "prompt_tokens": 387,
  "output_tokens": 53,
  "total_tokens": 440,
  "cost_usd": 0.0,
  "hosted_equivalent_usd": 0.000273,
  "note": "Local model: no per-call cost. Hosted equivalent uses illustrative prices, not a quote."
 },
 "model": "llama3.2:3b",
 "model_called": true,
 "settings": {
  "floor": 0.7,
  "top_k": 2,
  "groundedness_threshold": 0.61
 },
 "disclaimer": "Educational assistant for a fictional clinic's policies. Answers come only from approved policy documents and are checked against them; it gives no medical advice."
}
```

**Nothing relevant above the floor** (`"Do you offer appointments on Sundays?"`): the model is not called. `200`
```json
{
 "status": "insufficient_information",
 "answer": "",
 "citations": [],
 "sources": [],
 "reason": "no_relevant_policy",
 "stale_chunks_skipped": 0,
 "usage": null,
 "model": "llama3.2:3b",
 "model_called": false,
 "settings": {
  "floor": 0.7,
  "top_k": 2,
  "groundedness_threshold": 0.61
 },
 "disclaimer": "Educational assistant for a fictional clinic's policies. Answers come only from approved policy documents and are checked against them; it gives no medical advice."
}
```

**Medical question**, refused before retrieval (`"Which medicine should I take for my fever before the visit?"`). `200`
```json
{
 "status": "refused",
 "answer": "This assistant only answers questions about the fictional clinic's policies. It can't give medical advice; please contact a qualified professional.",
 "citations": [],
 "sources": [],
 "reason": "medical_advice_not_given",
 "stale_chunks_skipped": 0,
 "usage": null,
 "model": "llama3.2:3b",
 "model_called": false,
 "settings": {
  "floor": 0.7,
  "top_k": 2,
  "groundedness_threshold": 0.61
 },
 "disclaimer": "Educational assistant for a fictional clinic's policies. Answers come only from approved policy documents and are checked against them; it gives no medical advice."
}
```

`reason` values: `no_relevant_policy`, `could_not_verify_answer` (any failed citation, number, polarity,
groundedness or prompt-leak check), `index_out_of_date` (vectors from another embedder; an admin must
run `reindex_documents`), and `medical_advice_not_given`.

| status | when | `error.code` |
|---|---|---|
| 400 | empty, non-text, over 500 characters, or unknown fields | `invalid_question`, e.g. `{
 "code": "invalid_question",
 "message": "Ask a question as non-empty text."
}` |
| 401 / 403 | not signed in as admin, or CSRF token missing | `not_authenticated` / `permission_denied` |
| 429 | over 10/min | `throttled` |
| 502 | the model's reply was not valid JSON for the schema | `assistant_invalid_output` |
| 503 | the model server is unreachable | `assistant_unavailable` |
| 504 | no reply within 60 seconds | `assistant_timeout` |

Error messages never include the model's output or the server's details.

### Policy documents: `GET` / `POST /api/v1/assistant/documents/`, `POST /api/v1/assistant/documents/<id>/approve/`

Uploads arrive as **pending** and are **not searchable until an admin approves them**. Approving embeds
the chunks and makes them searchable. Only UTF-8 `.txt` and `.md` files up to the size limit are accepted;
the content is checked, not just the extension.

```bash
curl -b jar.txt -H "X-CSRFToken: $CSRF" -F "file=@parking.md" http://127.0.0.1:8000/api/v1/assistant/documents/
```

`201` (pending, 0 chunks: not searchable yet)
```json
{
 "id": 7,
 "filename": "parking.md",
 "status": "pending",
 "source": "upload",
 "sha256": "99269f96acf8109edfcced31f3c39f2c6e89e9748c81479377706c4d3604c0bb",
 "created_at": "2026-11-01T12:57:33.710843Z",
 "approved_at": null,
 "chunks": 0
}
```

The same content again: `409`
```json
{
 "error": {
  "code": "duplicate_document",
  "message": "A document with exactly this content already exists."
 }
}
```

`POST /api/v1/assistant/documents/7/approve/`: `200`
```json
{
 "id": 7,
 "filename": "parking.md",
 "status": "approved",
 "source": "upload",
 "sha256": "99269f96acf8109edfcced31f3c39f2c6e89e9748c81479377706c4d3604c0bb",
 "created_at": "2026-11-01T12:57:33.710843Z",
 "approved_at": "2026-11-01T12:57:33.734527Z",
 "chunks": 1
}
```

After approval the new policy is answerable (`"Is there free parking at the clinic?"`), trimmed:
```json
{
 "status": "answered",
 "answer": "The clinic has free parking for patients in the car park behind the building, for up to 3 hours.",
 "citations": [
  {
   "passage_id": "parking.md#0",
   "quote": "Parking The clinic has free parking for patients in the car park behind the building, for up to 3 hours.",
   "source": "parking.md"
  }
 ],
 "sources": [
  {
   "passage_id": "parking.md#0",
   "source": "parking.md",
   "similarity": 0.857
  }
 ]
}
```

| status | when | `error.code` |
|---|---|---|
| 400 | no file, empty, wrong type, binary, not UTF-8, too many control characters | `upload_rejected` |
| 404 | approving an unknown id | `not_found` |
| 409 | same content already uploaded; approving an approved document | `duplicate_document` / `already_approved` |
| 413 | file over the size limit | `file_too_large` |
| 503 | embeddings unavailable while approving; the document stays pending | `embedding_unavailable` |
