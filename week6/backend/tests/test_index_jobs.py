"""Week 5 Step 10 (J1–J3, C5, C6): background indexing jobs, in Celery's eager mode (inline, no broker), with
injected embedders. Job states, bounded retries of transient failures only, safe repeats, the worker's own
authorisation check, the queue being down, the job API, and audit and logs with ids only. The real worker and
Redis are tested in test_index_worker.py."""

import logging

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.db import IntegrityError, transaction
from kombu.exceptions import OperationalError

from accounts.models import User
from assistant import jobs
from assistant.documents import create_document
from assistant.embeddings import FakeEmbedder, FlakyEmbedder, get_embedder
from assistant.jobs import index_version, run_job
from assistant.llm import LLMTimeout, LLMUnavailable
from assistant.models import DocumentVersion, IndexJob
from audit.models import AuditEvent

from .conftest import Browser, user_login
from .test_assistant_versions import DOCS, NEW, OLD, post, texts, upload

JOBS = "/api/v1/assistant/jobs/"


class Scripted(FakeEmbedder):
    """Raises each scripted error in turn, then embeds normally."""

    def __init__(self, *errors):
        super().__init__()
        self.errors, self.calls = list(errors), 0

    def embed(self, texts_):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return super().embed(texts_)


def use(monkeypatch, embedder):
    monkeypatch.setattr("assistant.jobs.get_embedder", lambda: embedder)
    return embedder


@pytest.fixture
def pending(db, admin):
    """A new document whose v1 is pending (nothing searchable yet)."""
    import hashlib
    document = create_document("refunds.md", OLD, hashlib.sha256(OLD.encode()).hexdigest(), "upload", admin,
                               policy_area="billing")
    return document.versions.get()


def new_job(version, admin, **fields):
    return IndexJob.objects.create(version=version, requested_by=admin, request_id="req-1", **fields)


# ---------------- states and retries ----------------

@pytest.mark.django_db
class TestStates:
    def test_a_job_goes_queued_running_succeeded_and_indexes_the_version(self, admin_browser, pending, monkeypatch):
        seen = []
        real = jobs._finish
        monkeypatch.setattr(jobs, "_finish", lambda job, *a, **k: (seen.append(IndexJob.objects.get(pk=job.pk).status),
                                                                    real(job, *a, **k)))
        body = post(admin_browser, f"{DOCS}{pending.document_id}/approve/").json()
        job = IndexJob.objects.get()
        assert seen == ["running"] and job.status == "succeeded" and job.attempts == 1 and job.chunks >= 1
        assert body["job"]["id"] == job.id and body["status"] == "approved" and OLD in texts()
        assert job.started_at and job.finished_at and job.error_code == ""

    def test_a_transient_failure_is_retried_then_succeeds(self, admin_browser, pending, monkeypatch):
        embedder = use(monkeypatch, Scripted(LLMUnavailable("down")))
        job = post(admin_browser, f"{DOCS}{pending.document_id}/approve/").json()["job"]
        assert (job["status"], job["attempts"], embedder.calls) == ("succeeded", 2, 2)
        assert OLD in texts()

    def test_retries_are_bounded_and_a_failed_job_changes_nothing(self, admin_browser, monkeypatch):
        doc = upload(admin_browser, DOCS, "refunds.md", OLD, policy_area="billing").json()["id"]
        post(admin_browser, f"{DOCS}{doc}/approve/")
        upload(admin_browser, f"{DOCS}{doc}/versions/", "refunds.md", NEW)
        embedder = use(monkeypatch, Scripted(*[LLMUnavailable("down")] * 10))
        job = post(admin_browser, f"{DOCS}{doc}/versions/2/approve/").json()["job"]
        assert (job["status"], job["attempts"], job["error_code"], embedder.calls) == ("failed", 3, "unavailable", 3)
        assert DocumentVersion.objects.get(document_id=doc, number=2).status == "pending"
        assert OLD in texts() and NEW not in texts()

    def test_a_timeout_is_transient_and_reported_as_timeout(self, admin_browser, pending, monkeypatch):
        use(monkeypatch, Scripted(*[LLMTimeout("slow")] * 3))
        job = post(admin_browser, f"{DOCS}{pending.document_id}/approve/").json()["job"]
        assert (job["status"], job["attempts"], job["error_code"]) == ("failed", 3, "timeout")

    def test_backoff_is_five_then_ten_seconds(self, admin, pending, monkeypatch):
        monkeypatch.setitem(jobs.CONFIG, "BACKOFF_SECONDS", [5, 10])
        use(monkeypatch, Scripted(*[LLMUnavailable("down")] * 3))
        job = new_job(pending, admin)
        assert [run_job(job.id), run_job(job.id), run_job(job.id)] == [5, 10, None]
        job.refresh_from_db()
        assert (job.status, job.attempts) == ("failed", 3)

    def test_a_permanent_error_fails_at_once_without_a_retry(self, admin, pending, monkeypatch):
        embedder = use(monkeypatch, Scripted())
        job = new_job(pending, admin)
        DocumentVersion.objects.filter(pk=pending.pk).update(status="rejected")
        assert run_job(job.id) is None
        job.refresh_from_db()
        assert (job.status, job.attempts, job.error_code, embedder.calls) == ("failed", 1, "not_pending", 0)

    def test_an_unexpected_error_is_not_retried_and_only_its_class_is_logged(self, admin, pending, monkeypatch, caplog):
        use(monkeypatch, Scripted(ValueError("secret refund text")))
        job = new_job(pending, admin)
        with caplog.at_level(logging.INFO, logger="assistant.jobs"):
            assert run_job(job.id) is None
        job.refresh_from_db()
        assert (job.status, job.attempts, job.error_code) == ("failed", 1, "internal_error")
        assert "ValueError" in caplog.text and "secret" not in caplog.text and "refund" not in caplog.text

    def test_the_soft_time_limit_fails_the_job(self, admin, pending, monkeypatch):
        use(monkeypatch, Scripted(SoftTimeLimitExceeded()))
        job = new_job(pending, admin)
        run_job(job.id)
        job.refresh_from_db()
        assert (job.status, job.error_code) == ("failed", "time_limit")
        assert DocumentVersion.objects.get(pk=pending.pk).status == "pending"


# ---------------- safe to repeat ----------------

@pytest.mark.django_db
class TestRepeats:
    def test_a_duplicate_delivery_does_nothing(self, admin, pending, monkeypatch):
        embedder = use(monkeypatch, Scripted())
        job = new_job(pending, admin)
        run_job(job.id)
        run_job(job.id)
        job.refresh_from_db()
        assert (job.status, job.attempts, embedder.calls) == ("succeeded", 1, 1)
        assert AuditEvent.objects.filter(action="admin.document_approved").count() == 1

    def test_a_job_redelivered_after_a_crash_on_its_last_attempt_is_failed_not_rerun(self, admin, pending, monkeypatch):
        embedder = use(monkeypatch, Scripted())
        job = new_job(pending, admin, status="running", attempts=3, error_code="unavailable")
        run_job(job.id)
        job.refresh_from_db()
        assert (job.status, job.error_code, embedder.calls) == ("failed", "unavailable", 0)

    def test_a_job_redelivered_mid_run_counts_as_a_new_attempt(self, admin, pending, monkeypatch):
        use(monkeypatch, Scripted())
        job = new_job(pending, admin, status="running", attempts=1)
        run_job(job.id)
        job.refresh_from_db()
        assert (job.status, job.attempts) == ("succeeded", 2)

    def test_approving_while_a_job_is_open_returns_that_job(self, admin_browser, admin, pending):
        job = new_job(pending, admin)  # queued, not yet picked up
        r = post(admin_browser, f"{DOCS}{pending.document_id}/approve/")
        assert r.status_code == 200 and r.json()["job"]["id"] == job.id and IndexJob.objects.count() == 1

    def test_the_database_allows_one_open_job_per_version(self, admin, pending):
        new_job(pending, admin)
        with pytest.raises(IntegrityError), transaction.atomic():
            new_job(pending, admin, status="running")
        new_job(pending, admin, status="failed")  # finished jobs don't count

    def test_a_version_approved_by_an_earlier_job_is_not_approved_again(self, admin_browser, pending):
        assert post(admin_browser, f"{DOCS}{pending.document_id}/approve/").status_code == 202
        assert post(admin_browser, f"{DOCS}{pending.document_id}/versions/1/approve/").status_code == 409
        assert IndexJob.objects.count() == 1


# ---------------- authorisation, queue, task settings ----------------

@pytest.mark.django_db
class TestGuards:
    def test_the_worker_rechecks_that_the_requester_is_still_an_active_admin(self, admin, pending, monkeypatch):
        embedder = use(monkeypatch, Scripted())
        job = new_job(pending, admin)
        User.objects.filter(pk=admin.pk).update(role=User.Role.USER)
        run_job(job.id)
        job.refresh_from_db()
        assert (job.status, job.error_code, embedder.calls) == ("failed", "not_allowed", 0)
        assert DocumentVersion.objects.get(pk=pending.pk).status == "pending"

    def test_a_deactivated_requester_is_refused_too(self, admin, pending):
        job = new_job(pending, admin)
        User.objects.filter(pk=admin.pk).update(is_active=False)
        run_job(job.id)
        assert IndexJob.objects.get(pk=job.pk).error_code == "not_allowed"

    def test_a_down_queue_is_a_503_and_changes_nothing(self, admin_browser, pending, monkeypatch):
        def down(*a, **k):
            raise OperationalError("Error 61 connecting to localhost:6379")
        monkeypatch.setattr(index_version, "apply_async", down)
        r = post(admin_browser, f"{DOCS}{pending.document_id}/approve/")
        assert r.status_code == 503 and r.json()["error"]["code"] == "queue_unavailable" and "6379" not in r.text
        job = IndexJob.objects.get()
        assert (job.status, job.error_code, job.attempts) == ("failed", "queue_unavailable", 0)
        assert DocumentVersion.objects.get(pk=pending.pk).status == "pending"

    def test_the_task_is_late_acknowledged_and_time_limited(self):
        assert index_version.acks_late and index_version.reject_on_worker_lost and index_version.ignore_result
        assert (index_version.soft_time_limit, index_version.time_limit) == (120, 150)

    def test_the_flaky_test_embedder_is_refused_outside_the_fake_provider(self, settings):
        settings.ASSISTANT = {**settings.ASSISTANT, "EMBEDDER": "flaky", "PROVIDER": "ollama"}
        from django.core.exceptions import ImproperlyConfigured
        with pytest.raises(ImproperlyConfigured):
            get_embedder()
        settings.ASSISTANT = {**settings.ASSISTANT, "PROVIDER": "fake"}
        assert isinstance(get_embedder(), FlakyEmbedder)


# ---------------- audit and the job API ----------------

@pytest.mark.django_db
class TestAuditAndApi:
    def test_audit_has_queued_approved_and_failed_with_ids_only(self, admin_browser, pending, monkeypatch):
        post(admin_browser, f"{DOCS}{pending.document_id}/approve/")
        job = IndexJob.objects.get()
        rows = list(AuditEvent.objects.order_by("id").values_list("action", "detail", "actor_id"))
        assert ("admin.index_job_queued", f"job:{job.id}:document:{pending.document_id}:v1", job.requested_by_id) in rows
        assert ("admin.document_approved", f"document:{pending.document_id}", job.requested_by_id) in rows
        doc2 = upload(admin_browser, DOCS, "other.md", NEW).json()["id"]
        use(monkeypatch, Scripted(*[LLMUnavailable("down")] * 3))
        post(admin_browser, f"{DOCS}{doc2}/approve/")
        failed = IndexJob.objects.get(version__document_id=doc2)
        assert AuditEvent.objects.filter(action="admin.index_job_failed", detail=f"job:{failed.id}:unavailable").exists()
        assert not any("refund" in (d or "").lower() for _, d, _ in rows)

    def test_the_job_api_lists_filters_and_shows_one_job(self, admin_browser, admin, pending):
        post(admin_browser, f"{DOCS}{pending.document_id}/approve/")
        job = IndexJob.objects.get()
        listed = admin_browser.get(JOBS).json()["jobs"]
        assert [j["id"] for j in listed] == [job.id] and listed[0]["status"] == "succeeded"
        assert admin_browser.get(JOBS + "?status=failed").json()["jobs"] == []
        assert admin_browser.get(JOBS + "?status=nope").status_code == 400
        one = admin_browser.get(f"{JOBS}{job.id}/").json()
        assert one["document_id"] == pending.document_id and one["version"] == 1 and one["attempts"] == 1
        assert admin_browser.get(f"{JOBS}999999/").status_code == 404
        assert "content" not in one and OLD not in admin_browser.get(JOBS).text

    @pytest.mark.parametrize("path", ["", "1/"])
    def test_members_and_anonymous_cannot_read_jobs(self, browser, user, path):
        assert browser.client.get(JOBS + path).status_code in (401, 403)
        member = Browser()
        user_login(member, user.email)
        assert member.client.get(JOBS + path).status_code in (401, 403)


@pytest.mark.django_db
def test_job_polling_has_its_own_rate_limit_and_does_not_use_the_question_budget(admin_browser, pending):
    from assistant.views import IndexJobsView, IndexJobView
    assert IndexJobView.throttle_scope == IndexJobsView.throttle_scope == "jobs"
    post(admin_browser, f"{DOCS}{pending.document_id}/approve/")
    job = IndexJob.objects.get()
    assert all(admin_browser.get(f"{JOBS}{job.id}/").status_code == 200 for _ in range(15))  # above the 10/min question limit
