"""Week 6 Step 6 evidence (O1–O5): JSON log lines with the request id, route-pattern access logs that never carry
question text or bodies, latency and error samples, token totals and the admin-only ops view."""

import io
import json
import logging
from unittest import mock

import pytest
from django.db import DatabaseError

from assistant.models import AnswerRecord
from config.logging import JsonFormatter
from monitoring import metrics
from monitoring.models import RequestSample

from .test_assistant_ask import ASK, reply, setup  # noqa: F401

OPS = "/api/v1/ops/"
SECRET_QUESTION = "My name is Zelda Quokka and my card is 4111 1111 1111 1111, can I get a refund?"


@pytest.fixture
def logs():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    yield stream
    root.removeHandler(handler)


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


@pytest.mark.django_db
class TestLogs:
    def test_access_line_is_json_with_request_id_and_route_pattern(self, admin_browser, logs):
        response = admin_browser.get("/api/v1/clusters/", HTTP_X_REQUEST_ID="trace-12345678")
        assert response["X-Request-ID"] == "trace-12345678"
        access = [line for line in lines(logs) if line["logger"] == "access"]
        assert access and access[-1]["request_id"] == "trace-12345678"
        assert access[-1]["route"] == "/api/v1/clusters/" and access[-1]["method"] == "GET"
        assert access[-1]["status"] == response.status_code and access[-1]["duration_ms"] >= 0
        assert access[-1]["user_id"] is not None

    def test_every_line_during_an_answer_shares_the_id_and_no_question_or_body_leaks(self, admin_browser, setup, logs):
        setup.replies.append(reply("A refund can be requested within 14 days of a payment."))
        admin_browser.client.post(
            ASK,
            {"question": SECRET_QUESTION},
            format="json",
            HTTP_X_REQUEST_ID="trace-abcdefgh",
            **admin_browser._csrf_headers(),
        )
        text = logs.getvalue()
        assert "Zelda" not in text and "4111" not in text and "refund?" not in text and "password" not in text
        ours = [line for line in lines(logs) if line["request_id"] == "trace-abcdefgh"]
        assert any(line["logger"] == "access" for line in ours)

    def test_path_values_are_not_logged(self, admin_browser, logs):
        admin_browser.get("/api/v1/assistant/jobs/987654/?q=secret-term")
        access = [line for line in lines(logs) if line["logger"] == "access"][-1]
        assert "987654" not in json.dumps(access) and "secret-term" not in logs.getvalue()
        assert "<" in access["route"] or access["route"] == "unmatched"


@pytest.mark.django_db
class TestMetrics:
    def test_api_requests_are_sampled_by_route_pattern_and_probes_are_not(self, admin_browser, client):
        RequestSample.objects.all().delete()  # sign-in during setup is sampled too
        client.get("/health/")
        client.get("/ready/")
        admin_browser.get("/api/v1/clusters/")
        assert list(RequestSample.objects.values_list("route", "method")) == [("/api/v1/clusters/", "GET")]

    def test_a_database_error_never_breaks_the_request(self, admin_browser):
        with mock.patch.object(RequestSample.objects, "create", side_effect=DatabaseError):
            assert admin_browser.get("/api/v1/clusters/").status_code == 200

    def test_percentiles_and_error_rates(self, db):
        for ms in range(1, 101):
            RequestSample.objects.create(route="/api/x/", method="GET", status=500 if ms > 95 else 200, ms=ms)
        RequestSample.objects.create(route="/api/x/", method="GET", status=404, ms=1)
        [row] = metrics.routes(1)
        assert row["count"] == 101 and row["p50_ms"] == 50 and row["p95_ms"] == 95
        assert row["rate_5xx"] == round(5 / 101, 3) and row["rate_4xx"] == round(1 / 101, 3)

    def test_old_samples_are_left_out(self, db):
        old = RequestSample.objects.create(route="/api/x/", method="GET", status=200, ms=1)
        RequestSample.objects.filter(pk=old.pk).update(created_at=old.created_at.replace(year=2000))
        assert metrics.routes(168) == []


@pytest.mark.django_db
class TestTokens:
    def test_answer_records_keep_token_counts(self, admin_browser, setup):
        setup.replies.append(reply("A refund can be requested within 14 days of a payment."))
        assert admin_browser.post(ASK, {"question": "How many days to request a refund?"}).status_code == 200
        record = AnswerRecord.objects.get()
        assert record.prompt_tokens > 0 and record.output_tokens > 0

    def test_ops_totals_tokens_with_zero_local_cost_and_illustrative_hosted_cost(self, admin_browser, setup):
        setup.replies.append(reply("A refund can be requested within 14 days of a payment."))
        admin_browser.post(ASK, {"question": "How many days to request a refund?"})
        body = admin_browser.get(OPS).json()
        [day] = body["tokens_by_day"]
        assert day["assistant"]["total_tokens"] > 0 and day["assistant"]["cost_usd"] == 0
        assert "illustrative" in body["cost_note"]


@pytest.mark.django_db
class TestOpsView:
    def test_admin_sees_routes(self, admin_browser):
        admin_browser.get("/api/v1/clusters/")
        body = admin_browser.get(OPS + "?hours=1").json()
        assert body["window_hours"] == 1 and body["requests"] >= 1
        assert {"method", "route", "count", "p50_ms", "p95_ms", "rate_4xx", "rate_5xx"} <= set(body["routes"][0])

    @pytest.mark.parametrize("hours", ["0", "169", "x", "-1"])
    def test_bad_window_is_rejected(self, admin_browser, hours):
        assert admin_browser.get(OPS + "?hours=" + hours).status_code == 400

    def test_members_and_anonymous_are_refused(self, user_browser, client):
        assert user_browser.get(OPS).status_code in (401, 403)
        assert client.get(OPS).status_code in (401, 403)
