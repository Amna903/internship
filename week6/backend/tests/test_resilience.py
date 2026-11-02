"""Week 6 Step 7 evidence (R1–R4): each injected failure gives a safe JSON error, a JSON log line with the request
id and a stable event code, and shows in the ops view."""

from datetime import timedelta
from unittest import mock

import pytest
from django.db import OperationalError
from django.utils import timezone

from assistant import answering
from assistant.llm import LLMTimeout, LLMUnavailable
from assistant.models import DocumentVersion, IndexJob
from monitoring import metrics

from .test_assistant_ask import ASK, setup  # noqa: F401
from .test_ops import lines, logs  # noqa: F401

QUESTION = "How many days do I have to request a refund?"


def post(browser, url, data, rid):
    return browser.client.post(url, data, format="json", HTTP_X_REQUEST_ID=rid, **browser._csrf_headers())


def events(stream, rid):
    return [line.get("event") for line in lines(stream) if line["request_id"] == rid]


def safe(body):
    text = str(body)
    return "Traceback" not in text and "OperationalError" not in text and "SELECT" not in text


@pytest.mark.django_db
class TestLLM:
    @pytest.mark.parametrize(
        "error, http, code, event",
        [
            (LLMTimeout("slow"), 504, "assistant_timeout", "llm_timeout"),
            (LLMUnavailable("down"), 503, "assistant_unavailable", "llm_unavailable"),
        ],
    )
    def test_model_failure_is_safe_and_observable(self, admin_browser, setup, logs, error, http, code, event):
        setup.replies.append(error)
        response = post(admin_browser, ASK, {"question": QUESTION}, "trace-llm00001")
        assert response.status_code == http and response.json()["error"]["code"] == code and safe(response.json())
        assert event in events(logs, "trace-llm00001")
        assert metrics.ops(1)["rate_5xx"] > 0


@pytest.mark.django_db
class TestVectorStore:
    def test_embedder_failure_is_a_calm_503(self, admin_browser, setup, monkeypatch):
        monkeypatch.setattr(answering, "shipped_retrieve", mock.Mock(side_effect=LLMUnavailable("embedder down")))
        response = post(admin_browser, ASK, {"question": QUESTION}, "trace-emb00001")
        assert response.status_code == 503 and response.json()["error"]["code"] == "assistant_unavailable"

    def test_passage_store_failure_is_a_calm_503_not_a_500(self, admin_browser, setup, monkeypatch, logs):
        monkeypatch.setattr(answering, "shipped_retrieve", mock.Mock(side_effect=OperationalError("SELECT secret")))
        response = post(admin_browser, ASK, {"question": QUESTION}, "trace-vec00001")
        assert response.status_code == 503 and response.json()["error"]["code"] == "retrieval_unavailable"
        assert safe(response.json()) and "secret" not in logs.getvalue()
        assert "retrieval_unavailable" in events(logs, "trace-vec00001")
        assert not setup.seen  # the model is never called without passages


@pytest.mark.django_db
class TestDatabase:
    def test_database_outage_is_a_retryable_503_with_no_detail(self, admin_browser, logs):
        with mock.patch("predictions.views.NoShowPredictionView.post", side_effect=OperationalError("SELECT pw")):
            response = post(admin_browser, "/api/v1/predict/", {}, "trace-db000001")
        assert response.status_code == 503 and response["Retry-After"] == "30"
        assert response.json()["error"]["code"] == "service_unavailable" and safe(response.json())
        assert "database_unavailable" in events(logs, "trace-db000001") and "SELECT pw" not in logs.getvalue()

    def test_ready_reports_the_database_down(self, client):
        with mock.patch("config.health._db", side_effect=OperationalError("down")):
            response = client.get("/ready/")
        assert response.status_code == 503 and response.json()["checks"]["database"]["status"] == "error"


@pytest.mark.django_db
class TestWorker:
    def test_jobs_no_worker_picks_up_are_reported(self, admin):
        from assistant.models import PolicyDocument

        doc = PolicyDocument.objects.create(filename="x.md", source=PolicyDocument.Source.UPLOAD)
        version = DocumentVersion.objects.create(document=doc, number=1, content="text", sha256="0" * 64)
        job = IndexJob.objects.create(version=version, requested_by=admin)
        assert metrics.jobs() == {"queued": 1, "queued_over_5_min": 0, "failed_last_24h": 0}
        IndexJob.objects.filter(pk=job.pk).update(queued_at=timezone.now() - timedelta(minutes=6))
        assert metrics.jobs()["queued_over_5_min"] == 1


@pytest.mark.django_db
def test_outage_while_reading_the_session_stays_a_503(admin_browser):
    """Found in the live rehearsal: the access log read the user (a session query) after the 503, giving a 500."""
    with mock.patch("django.contrib.sessions.backends.db.SessionStore.load", side_effect=OperationalError("down")):
        response = admin_browser.get("/api/v1/clusters/")
    assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"
