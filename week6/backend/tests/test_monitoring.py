"""Week 5 Step 11 (M1–M5): prediction logging, the PSI drift check against the committed baseline, latency
and failure flags, the monitoring API and the fixed disclaimer. No language model."""

import json
import math
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from ml.inference import ModelUnavailable
from monitoring import drift
from monitoring.drift import psi, shares, summarise, verdict
from monitoring.models import PredictionLog

from .conftest import Browser, user_login

URL = "/api/v1/monitoring/"
ROW = {"lead_time_days": 5, "appointment_weekday": "monday", "appointment_hour": 10, "age_band": "35-44",
       "visit_type": "in_person", "booking_channel": "web", "reminder_sent": True, "prior_appointments": 4,
       "prior_no_shows": 0, "distance_km": 6.5}
BASE = {"model_version": "no-show-1.0.0", "shares": [0.1] * 10, "latency_ms": {"p50": 1.0, "p95": 2.0}}


# ---------------- the maths, by hand ----------------

class TestPsi:
    def test_identical_distributions_score_zero(self):
        assert psi([0.1] * 10, [0.1] * 10) == 0

    def test_a_hand_computed_value(self):
        e, a = [0.5, 0.5] + [0] * 8, [0.25, 0.75] + [0] * 8
        assert psi(e, a) == pytest.approx((0.25 - 0.5) * math.log(0.5) + (0.75 - 0.5) * math.log(1.5))

    def test_empty_bins_are_floored_not_infinite(self):
        assert math.isfinite(psi([1.0] + [0] * 9, [0] * 9 + [1.0]))

    def test_bins_are_fixed_width_and_one_lands_in_the_last(self):
        assert shares([0.0, 0.05, 0.1, 0.99, 1.0]) == [0.4, 0.2, 0, 0, 0, 0, 0, 0, 0, 0.4]

    @pytest.mark.parametrize("value, word", [(None, "not enough data"), (0.0999, "stable"), (0.1, "watch"),
                                             (0.25, "watch"), (0.2501, "possible drift")])
    def test_thresholds_are_the_committed_ones(self, value, word):
        assert verdict(value) == word


class TestSummarise:
    def rows(self, n, p=0.05, version="no-show-1.0.0", outcome="ok", latency=1.0):
        return [(version, outcome, p if outcome == "ok" else None, latency)] * n

    def test_fewer_than_100_predictions_gives_no_verdict(self):
        s = summarise(self.rows(99), BASE)
        assert s["psi"] is None and s["verdict"] == "not enough data" and "possible_drift" not in s["flags"]

    def test_a_concentrated_window_is_possible_drift(self):
        s = summarise(self.rows(200, p=0.95), BASE)
        assert s["verdict"] == "possible drift" and "possible_drift" in s["flags"]

    def test_failure_rate_flag_needs_20_calls_and_ignores_invalid_input(self):
        assert "failure_rate" not in summarise(self.rows(10, outcome="failed"), BASE)["flags"]
        s = summarise(self.rows(19) + self.rows(2, outcome="failed") + self.rows(50, outcome="invalid_input"), BASE)
        assert s["failure_rate"] == round(2 / 21, 4) and "failure_rate" in s["flags"] and s["invalid_input"] == 50
        assert "failure_rate" not in summarise(self.rows(100) + self.rows(5, outcome="failed"), BASE)["flags"]

    def test_latency_flag_is_three_times_the_baseline_p95(self):
        assert "latency" not in summarise(self.rows(10, latency=6.0), BASE)["flags"]
        assert "latency" in summarise(self.rows(10, latency=6.1), BASE)["flags"]

    def test_another_model_version_is_not_compared(self):
        s = summarise(self.rows(200, p=0.95, version="no-show-2.0.0"), BASE)
        assert s["psi"] is None and s["other_versions"] == ["no-show-2.0.0"]
        assert "baseline_is_for_another_version" in s["flags"]


# ---------------- logging from both paths ----------------

@pytest.mark.django_db
class TestLogging:
    def test_the_api_logs_ok_and_invalid_without_input_values(self, admin_browser):
        assert admin_browser.post("/api/v1/predictions/no-show/", ROW).status_code == 200
        assert admin_browser.post("/api/v1/predictions/no-show/", {**ROW, "appointment_hour": 99}).status_code == 400
        logs = list(PredictionLog.objects.order_by("id").values())
        assert [(r["source"], r["outcome"]) for r in logs] == [("api", "ok"), ("api", "invalid_input")]
        assert logs[0]["model_version"] == drift.SERVED and 0 <= logs[0]["probability"] <= 1
        assert logs[0]["latency_ms"] > 0
        assert set(logs[0]) == {"id", "created_at", "model_version", "source", "outcome", "probability", "latency_ms"}

    def test_the_api_logs_a_failure(self, admin_browser, monkeypatch):
        def down():
            raise ModelUnavailable("checksum")
        monkeypatch.setattr("predictions.views.get_model", down)
        assert admin_browser.post("/api/v1/predictions/no-show/", ROW).status_code == 503
        assert PredictionLog.objects.get().outcome == "failed"

    def test_the_agent_tool_logs_with_source_agent(self, admin):
        from agent.registry import ToolContext, run_tool
        ctx = ToolContext(user=admin, request_id="t", embedder=None, llm=None, via_agent=False)
        assert run_tool("predict_no_show", ROW, ctx).ok
        assert not run_tool("predict_no_show", {**ROW, "prior_no_shows": 9}, ctx).ok
        assert list(PredictionLog.objects.order_by("id").values_list("source", "outcome")) == [
            ("agent", "ok"), ("agent", "invalid_input")]

    def test_pruning_keeps_90_days(self):
        old = PredictionLog.objects.create(model_version="v", source="api", outcome="ok", probability=0.1, latency_ms=1)
        PredictionLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=91))
        PredictionLog.objects.create(model_version="v", source="api", outcome="ok", probability=0.1, latency_ms=1)
        call_command("prune_prediction_logs")
        assert PredictionLog.objects.count() == 1


# ---------------- the API, the baseline and the evidence ----------------

@pytest.mark.django_db
class TestApi:
    def test_summary_has_the_fixed_disclaimer_and_the_baseline(self, admin_browser):
        admin_browser.post("/api/v1/predictions/no-show/", ROW)
        body = admin_browser.get(URL).json()
        assert body["disclaimer"] == drift.DISCLAIMER and "no claim about real-world medical impact" in body["disclaimer"]
        assert body["predictions"] == 1 and body["verdict"] == "not enough data" and len(body["baseline_shares"]) == 10

    @pytest.mark.parametrize("days", ["0", "91", "x", "-1"])
    def test_days_is_validated(self, admin_browser, days):
        assert admin_browser.get(f"{URL}?days={days}").status_code == 400

    def test_members_and_anonymous_are_refused(self, browser, user):
        assert browser.client.get(URL).status_code in (401, 403)
        member = Browser()
        user_login(member, user.email)
        assert member.client.get(URL).status_code in (401, 403)


def test_the_committed_baseline_matches_the_served_model():
    b = json.loads(drift.BASELINE.read_text())
    assert b["model_version"] == drift.SERVED and b["split"] == "validation"
    assert len(b["shares"]) == 10 and sum(b["shares"]) == pytest.approx(1, abs=1e-3)


def test_the_committed_evidence_met_its_expectations():
    r = json.loads(drift.BASELINE.with_name("monitoring.json").read_text())
    assert r["seed"] != 20261101  # never the fresh holdout's seed
    assert r["met"] == {"no_drift": True, "drift": True, "failures": True}
