# Week 6 study guide

Week 6 is the capstone layer: it makes the earlier synthetic HealthProfile application reproducible, observable, safer to operate and easier to review. It does not turn the prototype into a real clinical system.

## 1. Containers and reproducibility

`make up` builds and starts the frontend, API, database, Redis broker and background worker together. A fresh clone was tested from the README alone (smoke test 6/6).

*Everyday example:* instead of handing someone five separate recipes, you give them one labelled meal kit with all the ingredients and instructions.

The production profile adds Caddy for HTTPS. `make backup`, `make restore` and `make rollback` are rehearsed procedures, not untested promises.

## 2. Production security settings

Development and production use separate settings. Production refuses unsafe configuration: debug mode, weak or shared secrets, missing secure cookies, wildcard hosts and unapproved origins.

The browser uses same-origin requests through Next.js, so the API does not need permissive CORS. CSRF still protects every unsafe request.

*Everyday example:* a building can have a public reception desk without leaving every internal door unlocked.

## 3. Observability without collecting sensitive content

Every API request has a request ID and produces a structured log line with its route pattern, outcome and duration. The operations page aggregates latency, error rates and token totals.

The design deliberately excludes question text, answer text, passwords, emails, request bodies and raw path values from logs.

*Everyday example:* a delivery dashboard records that a parcel was late, not the private letter inside it.

## 4. Resilience

The application has controlled failure paths for an unavailable LLM, passage-store/database errors and a stopped worker. Responses use stable error codes, logs use stable event names, and the operations view makes the effect visible.

The live Compose rehearsal initially found a real fault: Django re-read a session after a database-outage response and changed the intended 503 into a 500. `OutageSafeSessionMiddleware` fixed it; the final rehearsal passed 10/10.

*Lesson:* a failure handler must be tested during the whole request lifecycle, not only at the point where the error is caught.

## 5. Load testing

Locust ran a fixed synthetic workload against prediction and cluster endpoints: 10 users, 60 seconds, three measured runs per configuration.

The one permitted optimization raised Gunicorn workers from 3 to 9. Median p95 got worse, from 27 ms to 51 ms, so the change was reverted. That is a valid measurement, but it does **not** satisfy a requirement for a positive improvement.

*Everyday example:* adding extra checkout lanes can slow a small shop if the shared stockroom becomes the bottleneck.

## 6. Evaluation and security regression

`make eval` reproduces the released supervised model and reports clustering, frozen RAG cases and frozen agent cases. The Week 6 run reproduced the earlier RAG result and the agent red-team gate passed 11/11.

The security suite adds an authorization matrix, a tracked-file secret scan and a named high-risk test group. A new API route that accidentally misses permissions is meant to fail CI.

## 7. Honest boundaries

- Data, users, policies, appointments and outcomes are synthetic and fictional.
- Predictions are not diagnoses or medical advice.
- The project is a local reproducible deployment procedure, not a hosted clinical deployment.
- Tool-output prompt injection is defended and tested offline, but was not demonstrated end to end because the real model did not retrieve the injected text.
- Latest GitHub CI must be green before treating the current commit as the verified release.

## What to remember

1. A deployment is only reproducible if someone can start it from the documented instructions.
2. Security is enforceable server-side rules plus regression tests, not prompts.
3. Logs should help operate the system without becoming a second database of sensitive text.
4. A negative performance result is still useful when it is measured, reverted and reported honestly.
