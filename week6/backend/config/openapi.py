"""Representative OpenAPI request/response examples for the core endpoints (Week 6 Step 4).

Added in one place by a drf-spectacular post-processing hook, so the views stay readable. Values are synthetic
and match the real response shapes (tests/test_openapi.py checks that each listed operation exists and has
its examples).
"""

PREDICT_IN = {
    "lead_time_days": 14,
    "appointment_weekday": "tuesday",
    "appointment_hour": 10,
    "age_band": "35-44",
    "visit_type": "in_person",
    "booking_channel": "web",
    "reminder_sent": True,
    "prior_appointments": 4,
    "prior_no_shows": 0,
    "distance_km": 6.5,
}
PREDICT_OUT = {
    "model_version": "no-show-1.0.0",
    "prediction": {
        "no_show_probability": 0.1212,
        "suggested_action": "standard_reminder",
        "suggested_action_label": "Standard reminder",
        "decision_threshold": 0.21,
        "average_no_show_rate": 0.1645,
    },
    "disclaimer": "Educational estimate on synthetic data; not a medical or operational decision.",
}

EXAMPLES = {
    ("/api/v1/predict/", "post"): (PREDICT_IN, PREDICT_OUT),
    ("/api/v1/predictions/no-show/", "post"): (PREDICT_IN, PREDICT_OUT),
    ("/api/v1/clusters/", "get"): (
        None,
        {
            "control": {"label": "Positive control (planted habits)", "k": 3},
            "real": {"structure_found": False},
            "methods": [{"method": "kmeans"}],
        },
    ),
    ("/api/v1/models/no-show/", "get"): (
        None,
        {
            "model_version": "no-show-1.0.0",
            "artifact_sha256": "6c1f…",
            "preprocessing": [
                {"step": "preprocess", "class": "ColumnTransformer"},
                {"step": "model", "class": "LogisticRegression"},
            ],
        },
    ),
    ("/api/v1/assistant/ask/", "post"): (
        {"question": "How many times can I reschedule an appointment?"},
        {
            "status": "answered",
            "answer": "You can reschedule up to two times.",
            "citations": [
                {
                    "passage_id": "rescheduling.md#0",
                    "quote": "Appointments can be rescheduled up to two times.",
                    "source": "rescheduling.md",
                }
            ],
            "usage": {"total_tokens": 812, "cost_usd": 0.0},
        },
    ),
    ("/api/v1/agent/run/", "post"): (
        {"message": "Please book the first telehealth slot on Thursday morning."},
        {
            "status": "done",
            "kind": "answer",
            "pending_action": {"action_id": "3f6c…"},
            "tool_calls": 2,
            "steps": [
                {"n": 1, "state": "execute", "tool": "check_availability", "code": "ok"},
                {"n": 2, "state": "execute", "tool": "book_mock_appointment", "code": "ok"},
            ],
        },
    ),
    ("/api/v1/agent/actions/{action_id}/confirm/", "post"): (
        None,
        {
            "action_id": "3f6c…",
            "status": "confirmed",
            "proposed_by_agent": True,
            "replayed": False,
            "booking": {"date": "2026-11-05", "time": "09:00", "clinician": "Clinician B", "visit_type": "telehealth"},
        },
    ),
    ("/api/v1/assistant/jobs/{job_id}/", "get"): (
        None,
        {
            "id": 7,
            "status": "succeeded",
            "attempts": 2,
            "max_attempts": 3,
            "error_code": None,
            "document_id": 3,
            "version": 2,
        },
    ),
    ("/api/v1/monitoring/", "get"): (
        None,
        {
            "predictions": 1200,
            "psi": 0.006,
            "verdict": "stable",
            "flags": [],
            "latency_ms": {"p50": 5.2, "p95": 5.4},
            "failure_rate": 0.0,
        },
    ),
}

PROBES = {
    "/health/": ("Liveness: the process answers", {"status": "ok"}),
    "/ready/": (
        "Readiness: database, broker and model (the LLM is reported but doesn't gate)",
        {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "ms": 0.4, "gates_readiness": True},
                "llm": {"status": "ok", "ms": 0.6, "gates_readiness": False},
            },
        },
    ),
}


def add_examples(result, generator, request, public):
    paths = result.setdefault("paths", {})
    for (path, method), (body, response) in EXAMPLES.items():
        op = paths.get(path, {}).get(method)
        if op is None:
            continue
        if body is not None:
            # Views without a serializer (ask, agent run) get a documented JSON body here.
            content = op.setdefault("requestBody", {"content": {}})["content"]
            content.setdefault("application/json", {"schema": {"type": "object"}})
            for media in content.values():
                media["examples"] = {"Representative": {"value": body}}
        ok = op.setdefault("responses", {}).setdefault("200", {"description": "OK"})
        ok.setdefault("content", {}).setdefault("application/json", {})["examples"] = {
            "Representative": {"value": response}
        }
    for path, (summary, response) in PROBES.items():
        paths[path] = {
            "get": {
                "operationId": path.strip("/") + "_probe",
                "summary": summary,
                "tags": ["ops"],
                "security": [],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {"application/json": {"examples": {"Representative": {"value": response}}}},
                    },
                    "503": {"description": "Not ready (only names and ok/error, no details)"},
                },
            }
        }
    return result
