"""Step 7 evidence: the versioned no-show API (F11, E3, E4, A2, K3).

Every request here is a direct API call through the Django test client, i.e. no frontend involved.
"""

import json
import logging

import pytest

from audit.models import AuditEvent
from ml import config
from ml.inference import ModelUnavailable, get_model
from predictions import views

from .conftest import Browser, user_login

PREDICT = "/api/v1/predictions/no-show/"
MODEL = "/api/v1/models/no-show/"
VALID = {
    "lead_time_days": 14, "appointment_weekday": "tuesday", "appointment_hour": 10, "age_band": "35-44",
    "visit_type": "in_person", "booking_channel": "web", "reminder_sent": True,
    "prior_appointments": 4, "prior_no_shows": 0, "distance_km": 6.5,
}


def post_raw(browser, body: str, csrf=True):
    headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value} if csrf else {}
    return browser.client.post(PREDICT, data=body, content_type="application/json", **headers)


def post(browser, payload, csrf=True):
    return post_raw(browser, json.dumps(payload), csrf)


def field_errors(response) -> dict:
    assert response.status_code == 400, response.content
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    return body["details"]


# ---------------- A2: validated output and model version ----------------

@pytest.mark.django_db
class TestValidRequest:
    def test_returns_model_version_prediction_and_disclaimer(self, admin_browser):
        response = post(admin_browser, VALID)
        assert response.status_code == 200
        body = response.json()
        assert body["model_version"] == f"{config.MODEL_NAME}-{config.MODEL_VERSION}"
        assert body["disclaimer"] == config.DISCLAIMER
        assert set(body["prediction"]) == {"no_show_probability", "suggested_action", "suggested_action_label",
                                           "decision_threshold", "average_no_show_rate"}
        assert response["X-Request-ID"]

    def test_matches_the_released_model_exactly(self, admin_browser):
        expected = get_model().predict([VALID])[0]
        assert post(admin_browser, VALID).json()["prediction"] == expected

    def test_same_request_gives_the_same_answer(self, admin_browser):
        assert post(admin_browser, VALID).json() == post(admin_browser, VALID).json()

    def test_null_distance_is_allowed(self, admin_browser):
        assert post(admin_browser, {**VALID, "distance_km": None}).status_code == 200

    def test_integer_distance_is_a_valid_number(self, admin_browser):
        assert post(admin_browser, {**VALID, "distance_km": 7}).status_code == 200

    def test_boundary_values_are_accepted(self, admin_browser):
        edge = {**VALID, "lead_time_days": 0, "appointment_hour": 19, "prior_appointments": 0, "prior_no_shows": 0,
                "distance_km": 0}
        assert post(admin_browser, edge).status_code == 200

    def test_no_clinical_wording_in_the_response(self, admin_browser):
        risky = {**VALID, "lead_time_days": 60, "age_band": "18-24", "reminder_sent": False,
                 "prior_appointments": 5, "prior_no_shows": 4}
        text = json.dumps(post(admin_browser, risky).json()["prediction"]).lower()
        for word in ("risk", "high", "diagnos", "disease", "illness"):
            assert word not in text


# ---------------- E3/E4: strict validation ----------------

@pytest.mark.django_db
class TestValidation:
    def test_unknown_field_is_rejected(self, admin_browser):
        assert field_errors(post(admin_browser, {**VALID, "patient_name": "Jane"})) == {"patient_name": ["Unknown field."]}

    def test_all_problems_are_reported_in_one_response(self, admin_browser):
        payload = {**VALID, "lead_time": 3, "appointment_hour": 22, "reminder_sent": "yes"}
        assert set(field_errors(post(admin_browser, payload))) == {"lead_time", "appointment_hour", "reminder_sent"}

    @pytest.mark.parametrize("field", list(config.FEATURE_SCHEMA))
    def test_each_missing_field_is_rejected(self, admin_browser, field):
        payload = {k: v for k, v in VALID.items() if k != field}
        assert field in field_errors(post(admin_browser, payload))

    @pytest.mark.parametrize("field, value", [
        ("lead_time_days", "14"),  # string is not an integer
        ("lead_time_days", 14.5),  # float is not an integer
        ("lead_time_days", True),  # bool is an int in Python; still rejected
        ("prior_appointments", None),
        ("reminder_sent", "yes"),
        ("reminder_sent", 1),
        ("distance_km", "6.5"),
        ("distance_km", False),
        ("age_band", 35),
        ("visit_type", None),
    ])
    def test_wrong_types_are_rejected(self, admin_browser, field, value):
        assert field in field_errors(post(admin_browser, {**VALID, field: value}))

    @pytest.mark.parametrize("field, value", [
        ("lead_time_days", -1), ("lead_time_days", 91), ("appointment_hour", 6), ("appointment_hour", 20),
        ("prior_appointments", -1), ("prior_appointments", 501), ("distance_km", -0.1), ("distance_km", 500.1),
    ])
    def test_out_of_range_values_are_rejected(self, admin_browser, field, value):
        assert field in field_errors(post(admin_browser, {**VALID, field: value}))

    @pytest.mark.parametrize("field, value", [("appointment_weekday", "funday"), ("appointment_weekday", "Tuesday"),
                                              ("booking_channel", "carrier_pigeon"), ("age_band", "16-17")])
    def test_unknown_categories_are_rejected(self, admin_browser, field, value):
        assert field in field_errors(post(admin_browser, {**VALID, field: value}))

    def test_more_no_shows_than_appointments_is_rejected(self, admin_browser):
        errors = field_errors(post(admin_browser, {**VALID, "prior_appointments": 2, "prior_no_shows": 3}))
        assert "prior_no_shows" in errors

    @pytest.mark.parametrize("body", ["{not json", "", "   ", "[1, 2, 3]", "42", '"text"', "null"])
    def test_malformed_or_non_object_bodies_are_rejected(self, admin_browser, body):
        response = post_raw(admin_browser, body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] in {"parse_error", "validation_error"}

    def test_oversized_body_is_rejected(self, admin_browser):
        response = post(admin_browser, {**VALID, "padding": "x" * 5000})
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"

    def test_non_finite_number_is_rejected(self, admin_browser):
        assert "distance_km" in field_errors(post_raw(admin_browser, json.dumps({**VALID, "distance_km": 1}).replace(
            '"distance_km": 1', '"distance_km": NaN')))


# ---------------- K3: Week 2 rules on the new endpoints ----------------

@pytest.mark.django_db
class TestAccessRules:
    @pytest.mark.parametrize("url, method", [(PREDICT, "post"), (MODEL, "get")])
    def test_anonymous_is_rejected(self, browser, url, method):
        browser.get("/api/auth/csrf/")
        response = getattr(browser, method)(url, VALID) if method == "post" else browser.get(url)
        assert response.status_code == 401

    @pytest.mark.parametrize("url, method", [(PREDICT, "post"), (MODEL, "get")])
    def test_member_jwt_is_rejected(self, user, url, method):
        member = Browser()
        user_login(member, user.email)
        response = member.post(url, VALID) if method == "post" else member.get(url)
        assert response.status_code in (401, 403)
        assert not AuditEvent.objects.filter(action="admin.prediction_made").exists()

    def test_missing_csrf_token_is_rejected(self, admin_browser):
        response = post(admin_browser, VALID, csrf=False)
        assert response.status_code == 403

    def test_wrong_method_is_rejected(self, admin_browser):
        assert admin_browser.get(PREDICT).status_code == 405

    def test_rate_limit(self, admin_browser):
        statuses = [post(admin_browser, VALID).status_code for _ in range(61)]
        assert statuses[:60] == [200] * 60 and statuses[60] == 429
        assert "retry_after_seconds" in post(admin_browser, VALID).json()["error"]["details"]


# ---------------- Audit: model version, never inputs ----------------

@pytest.mark.django_db
class TestAudit:
    def test_prediction_is_audited_with_the_model_version_only(self, admin_browser, admin):
        distinctive = {**VALID, "lead_time_days": 73, "distance_km": 123.4, "prior_appointments": 37,
                       "prior_no_shows": 19}
        response = post(admin_browser, distinctive)
        event = AuditEvent.objects.get(action="admin.prediction_made")
        assert (event.actor_id, event.actor_role, event.detail) == (admin.id, "admin", response.json()["model_version"])
        assert event.request_id == response["X-Request-ID"]
        # Column by column (searching the whole row for "19" would also hit the timestamp, a flaky test).
        stored = AuditEvent.objects.filter(pk=event.pk).values().get()
        assert set(stored) == {"id", "created_at", "actor_id", "actor_role", "action", "profile_id",
                               "changed_fields", "detail", "request_id"}  # no column could hold an input
        assert stored["changed_fields"] == [] and stored["profile_id"] is None
        assert stored["action"] == "admin.prediction_made" and stored["detail"] == response.json()["model_version"]

    def test_invalid_requests_are_not_audited_as_predictions(self, admin_browser):
        post(admin_browser, {**VALID, "appointment_hour": 3})
        assert not AuditEvent.objects.filter(action="admin.prediction_made").exists()

    def test_logs_contain_no_input_values(self, admin_browser, caplog):
        with caplog.at_level(logging.DEBUG):
            post(admin_browser, {**VALID, "distance_km": 123.4})
            post(admin_browser, {**VALID, "distance_km": 987.6})  # invalid: logged? must not leak the value
        assert "123.4" not in caplog.text and "987.6" not in caplog.text

    def test_append_only_triggers_survive_the_new_migration(self):
        from .test_audit import immutability_triggers
        from django.db import connection
        expected = {"audit_event_no_change", "audit_event_no_truncate"} if connection.vendor == "postgresql" \
            else {"audit_event_no_update", "audit_event_no_delete"}
        assert expected <= immutability_triggers()


# ---------------- Failure handling ----------------

@pytest.mark.django_db
class TestModelUnavailable:
    @pytest.fixture
    def broken_model(self, monkeypatch, caplog):
        def fail():
            raise ModelUnavailable("model file SHA-256 does not match its metadata")
        monkeypatch.setattr(views, "get_model", fail)
        return caplog

    @pytest.mark.parametrize("url", [PREDICT, MODEL])
    def test_returns_503_with_a_generic_message(self, admin_browser, broken_model, url):
        response = post(admin_browser, VALID) if url == PREDICT else admin_browser.get(url)
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "model_unavailable" and "SHA-256" not in error["message"]
        assert "SHA-256" in broken_model.text  # the reason is logged for operators

    def test_invalid_input_is_still_400_not_503(self, admin_browser, broken_model):
        assert post(admin_browser, {**VALID, "appointment_hour": 3}).status_code == 400

    def test_recovers_when_the_model_is_back(self, admin_browser, monkeypatch):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ModelUnavailable("missing file")
            return get_model()
        monkeypatch.setattr(views, "get_model", flaky)
        assert post(admin_browser, VALID).status_code == 503
        assert post(admin_browser, VALID).status_code == 200


# ---------------- Model card and API docs ----------------

@pytest.mark.django_db
def test_model_card_matches_the_released_metadata(admin_browser):
    card = admin_browser.get(MODEL).json()
    meta = get_model().metadata
    assert card["model_version"] == meta["model"]
    assert card["metrics"] == meta["metrics"] and card["decision"] == meta["decision"]
    assert card["inputs"] == config.FEATURE_SCHEMA
    assert card["artifact_sha256"] == meta["artifact_sha256"]
    assert "does not look them up" in card["inputs_note"]


@pytest.mark.django_db
def test_openapi_schema_documents_both_endpoints(browser):
    schema = browser.client.get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json").content.decode()
    assert "/api/v1/predictions/no-show/" in schema and "/api/v1/models/no-show/" in schema
