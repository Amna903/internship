"""Week 4 Step 8 evidence for GET /api/v1/clusters/: admin only, rate limited, audited with the results
version, served from the committed results (no clustering per request), safe 503, no identifiers leak."""

import json
import logging

import pytest

from audit.models import AuditEvent
from ml import cluster_view
from predictions import views

from .conftest import Browser, user_login
from .test_audit import immutability_triggers

CLUSTERS = "/api/v1/clusters/"


@pytest.fixture(autouse=True)
def fresh_cache():
    views.load_cluster_view.cache_clear()
    yield
    views.load_cluster_view.cache_clear()


@pytest.mark.django_db
class TestAccess:
    def test_anonymous_is_rejected(self, browser):
        assert browser.get(CLUSTERS).status_code == 401

    def test_member_is_rejected_and_nothing_is_audited(self, user):
        member = Browser()
        user_login(member, user.email)
        assert member.get(CLUSTERS).status_code in (401, 403)
        assert not AuditEvent.objects.filter(action="admin.clusters_viewed").exists()

    def test_rate_limit(self, admin_browser):
        statuses = [admin_browser.get(CLUSTERS).status_code for _ in range(61)]
        assert statuses[:60] == [200] * 60 and statuses[60] == 429


@pytest.mark.django_db
class TestResponse:
    def test_returns_the_committed_view_with_its_version_and_disclaimer(self, admin_browser):
        body = admin_browser.get(CLUSTERS).json()
        committed = json.loads(cluster_view.RESULT.read_text())
        assert {k: body[k] for k in committed} == committed
        assert body["disclaimer"] == cluster_view.DISCLAIMER
        assert len(body["results_sha256"]) == 64 and body["results_sha256"].startswith(body["results_version"])

    def test_control_data_is_labelled_and_real_clusters_are_marked_misleading(self, admin_browser):
        body = admin_browser.get(CLUSTERS).json()
        assert "not real patients" in body["control"]["label"]
        assert body["real"]["structure_found"] == {"k-means": False, "agglomerative (Ward)": False}
        assert "misleading_clusters" in body["real"]

    def test_no_identifier_leaks(self, admin_browser):
        text = admin_browser.get(CLUSTERS).text
        assert "patient_id" not in text and "appointment_id" not in text and "100000" not in text

    def test_no_clustering_runs_during_a_request(self, admin_browser, monkeypatch):
        from ml import cluster
        def forbidden(*args, **kwargs):
            raise AssertionError("clustering must not run during a request")
        monkeypatch.setattr(cluster, "run", forbidden)
        monkeypatch.setattr(cluster, "kmeans_labels", forbidden)
        assert admin_browser.get(CLUSTERS).status_code == 200


@pytest.mark.django_db
class TestAudit:
    def test_view_is_audited_with_the_results_version_only(self, admin_browser, admin):
        body = admin_browser.get(CLUSTERS).json()
        event = AuditEvent.objects.get(action="admin.clusters_viewed")
        assert (event.actor_id, event.detail) == (admin.id, f"cluster_view:{body['results_version']}")

    def test_append_only_triggers_survive_the_new_action(self):
        assert immutability_triggers()


@pytest.mark.django_db
class TestUnavailable:
    @pytest.mark.parametrize("content", [None, "not json", json.dumps({"control": {}})])
    def test_missing_or_broken_results_give_a_generic_503(self, admin_browser, tmp_path, monkeypatch, caplog, content):
        path = tmp_path / "cluster_view.json"
        if content is not None:
            path.write_text(content)
        monkeypatch.setattr(views, "CLUSTER_VIEW", path)
        with caplog.at_level(logging.ERROR):
            response = admin_browser.get(CLUSTERS)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "clusters_unavailable"
        assert str(tmp_path) not in response.text
        assert "cluster view unavailable" in caplog.text
        assert not AuditEvent.objects.filter(action="admin.clusters_viewed").exists()
