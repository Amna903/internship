"""Week 6: /health/ and /ready/ (liveness and readiness), without leaking error details."""

import pytest

from config import health


@pytest.mark.django_db
def test_health_is_ok(client):
    assert client.get("/health/").json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_reports_each_check(client):
    r = client.get("/ready/")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ready"
    assert set(body["checks"]) == {"database", "broker", "model", "llm"}
    assert body["checks"]["llm"]["gates_readiness"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["_db", "_broker", "_model"])
def test_a_failing_dependency_makes_ready_503_without_details(client, monkeypatch, name):
    def boom():
        raise RuntimeError("postgres://user:secret@db:5432")

    monkeypatch.setattr(health, name, boom)
    r = client.get("/ready/")
    assert r.status_code == 503 and r.json()["status"] == "not_ready" and "secret" not in r.text


@pytest.mark.django_db
def test_an_unreachable_llm_does_not_gate_readiness(client, monkeypatch):
    def down():
        raise OSError("connection refused")

    monkeypatch.setattr(health, "_llm", down)
    r = client.get("/ready/")
    assert r.status_code == 200 and r.json()["checks"]["llm"]["status"] == "error"
