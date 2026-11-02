"""Background indexing jobs (Week 5 Step 10; rules in docs/REQUIREMENTS.md, "Step 10 rules").

Approving a pending version queues an `IndexJob`; a Celery worker runs the existing `approve_version` (embed
first, then the atomic swap). States: queued -> running -> succeeded | failed, stored in the database.

- Only transient embedder failures (`LLMUnavailable`, `LLMTimeout`) are retried, at most MAX_ATTEMPTS in all,
  with a fixed backoff. Anything else fails at once with a typed code. A failed job leaves the version pending
  and the old edition live, as a failed synchronous approval always did.
- Safe to repeat: each run locks the job row and leaves a finished job alone, and `approve_version` re-checks
  "still pending" under the document lock, so a duplicate delivery can never approve or swap twice.
- The worker re-checks that the requester is still an active admin. Audit and logs carry ids and codes only.
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerError

from audit.models import AuditEvent

from .documents import DocumentError, approve_version
from .embeddings import get_embedder
from .llm import LLMTimeout, LLMUnavailable
from .models import DocumentVersion, IndexJob

logger = logging.getLogger(__name__)
CONFIG = settings.INDEX_JOB
Status = IndexJob.Status


def audit_detail(document_id: int, version: int) -> str:
    """Ids and version numbers only, never content. Version 1 keeps Week 4's form, like passage IDs."""
    return f"document:{document_id}" if version == 1 else f"document:{document_id}:v{version}"


class QueueUnavailable(RuntimeError):
    """The broker couldn't take the job. The job is marked failed and nothing else changed."""


def _audit(job: IndexJob, action: str, detail: str) -> None:
    actor = job.requested_by
    AuditEvent.objects.create(actor=actor, actor_role=actor.role if actor else "admin", action=action,
                              detail=detail[:64], request_id=job.request_id)


def _finish(job: IndexJob, status: str, code: str = "", chunks: int | None = None) -> None:
    job.status, job.error_code, job.chunks, job.finished_at = status, code, chunks, timezone.now()
    job.save(update_fields=["status", "error_code", "chunks", "finished_at"])
    if status == Status.FAILED:
        _audit(job, AuditEvent.Action.ADMIN_INDEX_JOB_FAILED, f"job:{job.id}:{code}")
        logger.warning("index job %s failed after %s attempt(s): %s", job.id, job.attempts, code)


def queue_approval(version: DocumentVersion, admin, request_id: str = "") -> tuple[IndexJob, bool]:
    """Queue the approval of a pending version. Returns (job, created): while a job for this version is still
    open, that job is returned and no second one is made. Raises DocumentError if the version isn't pending,
    and QueueUnavailable if the broker is down."""
    open_job = IndexJob.objects.filter(version=version, status__in=IndexJob.OPEN).first()
    if open_job is not None:
        return open_job, False
    if version.status != DocumentVersion.Status.PENDING:
        raise DocumentError("Only a version waiting for approval can be approved.", "not_pending")
    try:
        with transaction.atomic():
            job = IndexJob.objects.create(version=version, requested_by=admin, request_id=(request_id or "")[:64],
                                          max_attempts=CONFIG["MAX_ATTEMPTS"])
    except IntegrityError:  # another request queued it a moment ago
        return IndexJob.objects.get(version=version, status__in=IndexJob.OPEN), False
    _audit(job, AuditEvent.Action.ADMIN_INDEX_JOB_QUEUED, f"job:{job.id}:document:{version.document_id}:v{version.number}")
    try:
        index_version.apply_async(args=[job.id], retry=False)
    except BrokerError:
        _finish(job, Status.FAILED, "queue_unavailable")
        raise QueueUnavailable() from None
    job.refresh_from_db()
    return job, True


def run_job(job_id: int, embedder=None) -> int | None:
    """One attempt. Returns the countdown in seconds when a transient failure should be retried, else None."""
    with transaction.atomic():
        job = IndexJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.status not in IndexJob.OPEN:
            return None  # already finished (a duplicate delivery): leave it alone
        if job.attempts >= job.max_attempts:  # redelivered after a crash on its last attempt
            _finish(job, Status.FAILED, job.error_code or "worker_lost")
            return None
        job.status, job.attempts = Status.RUNNING, job.attempts + 1
        job.started_at = job.started_at or timezone.now()
        job.save(update_fields=["status", "attempts", "started_at"])
    admin = job.requested_by
    if admin is None or not (admin.is_active and admin.is_admin):
        _finish(job, Status.FAILED, "not_allowed")
        return None
    version = DocumentVersion.objects.select_related("document").get(pk=job.version_id)
    try:
        approval = approve_version(version, admin, embedder or get_embedder())
    except DocumentError as exc:
        _finish(job, Status.FAILED, exc.code)
        return None
    except (LLMUnavailable, LLMTimeout) as exc:
        code = "timeout" if isinstance(exc, LLMTimeout) else "unavailable"
        if job.attempts < job.max_attempts:
            job.status, job.error_code = Status.QUEUED, code
            job.save(update_fields=["status", "error_code"])
            logger.info("index job %s attempt %s: %s, retrying", job.id, job.attempts, code)
            backoff = CONFIG["BACKOFF_SECONDS"]
            return backoff[min(job.attempts, len(backoff)) - 1]
        _finish(job, Status.FAILED, code)
        return None
    except SoftTimeLimitExceeded:
        _finish(job, Status.FAILED, "time_limit")
        return None
    except Exception as exc:  # never retried; only the class is logged (messages could carry text)
        logger.error("index job %s failed unexpectedly (%s)", job.id, type(exc).__name__)
        _finish(job, Status.FAILED, "internal_error")
        return None
    _finish(job, Status.SUCCEEDED, chunks=approval.chunks)
    was = f":from_v{approval.previous}" if approval.previous else ""
    _audit(job, AuditEvent.Action.ADMIN_DOCUMENT_APPROVED, audit_detail(version.document_id, version.number) + was)
    return None


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, ignore_result=True,
             soft_time_limit=CONFIG["SOFT_TIME_LIMIT"], time_limit=CONFIG["TIME_LIMIT"])
def index_version(self, job_id: int) -> None:
    countdown = run_job(job_id)
    if countdown is not None:
        raise self.retry(countdown=countdown, max_retries=CONFIG["MAX_ATTEMPTS"] - 1)
