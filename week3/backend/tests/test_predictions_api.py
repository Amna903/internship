"""Week 3: safe model loading and the versioned inference API."""

import json
import shutil

import pytest

from audit.models import AuditEvent
from ml import config, inference

from .conftest import Browser

PREDICT = "/api/v1/predictions/no-show/"
CARD = "/api/v1/models/no-show/"

VALID = {
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
RISKY = {**VALID, "lead_time_days": 45, "reminder_sent": False, "prior_appointments": 3, "prior_no_shows": 3, "age_band": "18-24"}


@pytest.fixture(autouse=True)
def _fresh_model_cache():
    inference.load.cache_clear()
    yield
    inference.load.cache_clear()


@pytest.fixture
def artifact_copy(tmp_path):
    for name in (f"{config.MODEL_NAME}-{config.MODEL_VERSION}.json", f"{config.MODEL_NAME}-{config.MODEL_VERSION}.joblib"):
        shutil.copy(config.ARTIFACT_DIR / name, tmp_path / name)
    return tmp_path


class TestLoader:
    def test_committed_model_loads_and_scores_in_range(self):
        model = inference.load(str(config.ARTIFACT_DIR))
        assert model.version == "no-show-1.0.0"
        result = inference.predict(model, VALID)
        assert 0 <= result["no_show_probability"] <= 1 and result["risk_band"] in {"low", "medium", "high"}

    def test_scores_move_in_the_documented_direction(self):
        model = inference.load(str(config.ARTIFACT_DIR))
        safe = inference.predict(model, VALID)["no_show_probability"]
        risky = inference.predict(model, RISKY)["no_show_probability"]
        assert risky > safe
        assert inference.predict(model, RISKY)["risk_band"] == "high"

    def test_missing_distance_is_imputed_not_an_error(self):
        model = inference.load(str(config.ARTIFACT_DIR))
        assert 0 <= inference.predict(model, {**VALID, "distance_km": None})["no_show_probability"] <= 1

    def test_tampered_artifact_is_refused(self, artifact_copy):
        joblib_file = artifact_copy / f"{config.MODEL_NAME}-{config.MODEL_VERSION}.joblib"
        raw = bytearray(joblib_file.read_bytes())
        raw[-10] ^= 0xFF
        joblib_file.write_bytes(bytes(raw))
        with pytest.raises(inference.ModelUnavailable, match="checksum"):
            inference.load(str(artifact_copy))

    def test_missing_artifact_is_refused(self, tmp_path):
        with pytest.raises(inference.ModelUnavailable):
            inference.load(str(tmp_path))

    def test_library_version_mismatch_is_refused(self, artifact_copy):
        meta_file = artifact_copy / f"{config.MODEL_NAME}-{config.MODEL_VERSION}.json"
        meta = json.loads(meta_file.read_text())
        meta["environment"]["scikit_learn"] = "0.0.1"
        meta_file.write_text(json.dumps(meta))
        with pytest.raises(inference.ModelUnavailable, match="scikit-learn"):
            inference.load(str(artifact_copy))

    @pytest.mark.parametrize("p, band", [(0.05, "low"), (0.18, "medium"), (0.5, "high")])
    def test_risk_bands(self, p, band):
        assert inference.risk_band(p, threshold=0.24, base_rate=0.166) == band


@pytest.mark.django_db
class TestPredictApi:
    def test_admin_gets_versioned_validated_output(self, admin_browser):
        resp = admin_browser.post(PREDICT, VALID)
        assert resp.status_code == 200
        body = resp.json()
        assert body["model_version"] == "no-show-1.0.0"
        assert set(body["prediction"]) == {"no_show_probability", "risk_band", "decision_threshold", "baseline_no_show_rate"}
        assert 0 <= body["prediction"]["no_show_probability"] <= 1
        assert "not a medical assessment" in body["disclaimer"]

    def test_prediction_is_audited_without_inputs_or_score(self, admin_browser):
        body = admin_browser.post(PREDICT, VALID).json()
        event = AuditEvent.objects.get(action="admin.prediction")
        assert event.actor_role == "admin" and event.profile is None and event.changed_fields == []
        assert str(body["prediction"]["no_show_probability"]) not in json.dumps(
            {f.name: str(getattr(event, f.attname)) for f in AuditEvent._meta.concrete_fields}
        )

    def test_distance_may_be_omitted_or_null(self, admin_browser):
        without = {k: v for k, v in VALID.items() if k != "distance_km"}
        assert admin_browser.post(PREDICT, without).status_code == 200
        assert admin_browser.post(PREDICT, {**VALID, "distance_km": None}).status_code == 200

    @pytest.mark.parametrize(
        "patch, field",
        [
            ({"appointment_hour": 3}, "appointment_hour"),
            ({"lead_time_days": -1}, "lead_time_days"),
            ({"lead_time_days": 9999}, "lead_time_days"),
            ({"distance_km": 1e9}, "distance_km"),
            ({"age_band": "90+"}, "age_band"),
            ({"appointment_weekday": "funday"}, "appointment_weekday"),
            ({"prior_appointments": "many"}, "prior_appointments"),
            ({"prior_no_shows": 5, "prior_appointments": 2}, "prior_no_shows"),
            ({"lead_time": 3}, "lead_time"),  # unknown key (typo) is rejected, not ignored
        ],
    )
    def test_out_of_range_and_malformed_fields_are_rejected(self, admin_browser, patch, field):
        resp = admin_browser.post(PREDICT, {**VALID, **patch})
        assert resp.status_code == 400
        body = resp.json()["error"]
        assert body["code"] == "validation_error" and field in body["details"]

    def test_missing_required_field(self, admin_browser):
        resp = admin_browser.post(PREDICT, {k: v for k, v in VALID.items() if k != "visit_type"})
        assert resp.status_code == 400 and "visit_type" in resp.json()["error"]["details"]

    def test_non_object_and_broken_json_are_rejected(self, admin_browser):
        assert admin_browser.post(PREDICT, [VALID]).status_code == 400
        csrf = admin_browser.cookies["csrftoken"].value
        resp = admin_browser.client.post(PREDICT, data="{not json", content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        assert resp.status_code == 400 and resp.json()["error"]["code"] == "parse_error"

    def test_members_anonymous_and_missing_csrf_are_blocked(self, browser, user_browser, admin_browser):
        assert browser.post(PREDICT, VALID).status_code == 401
        assert user_browser.post(PREDICT, VALID).status_code in (401, 403)
        assert admin_browser.post(PREDICT, VALID, csrf=False).status_code == 403

    def test_get_is_not_allowed(self, admin_browser):
        assert admin_browser.get(PREDICT).status_code == 405

    def test_unavailable_model_gives_503_without_leaking_details(self, admin_browser, settings, tmp_path):
        settings.ML_ARTIFACT_DIR = tmp_path
        resp = admin_browser.post(PREDICT, VALID)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "model_unavailable"
        assert "ml.train" not in resp.content.decode() and str(tmp_path) not in resp.content.decode()

    def test_model_card(self, admin_browser, browser):
        body = admin_browser.get(CARD).json()
        assert body["model_version"] == "no-show-1.0.0"
        assert {"logistic_raw", "majority_prior", "oracle_ceiling", body["selected_model"]} <= set(body["test_metrics"])
        assert "checked_in" in body["features"]["excluded"]
        assert browser.get(CARD).status_code == 401


@pytest.mark.django_db
def test_prediction_endpoint_is_throttled(admin, settings):
    rates = {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "predict": "2/min"}
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates}
    from rest_framework.throttling import ScopedRateThrottle

    ScopedRateThrottle.THROTTLE_RATES = rates
    try:
        b = Browser()
        b.post("/api/admin/login/", {"email": admin.email, "password": "Sturdy-Passw0rd!x"})
        codes = [b.post(PREDICT, VALID).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
    finally:
        from rest_framework.settings import api_settings

        ScopedRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
