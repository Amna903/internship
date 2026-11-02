"""Policy documents, their versions, their searchable chunks, and a record of which editions each answer used.

A document is the stable identity (filename, policy area). Its text lives in versions. Only the document's
CURRENT version, and only while the document is approved (not retired), has chunks that search can see:
- uploads, first versions and later updates arrive as `pending` and have no chunks until approved;
- approving an update swaps the chunks atomically (assistant/documents.py), so the old edition stays live
  until the new one is indexed;
- retiring a document removes its chunks but keeps every version for audit.

Every chunk stores the embedding model that produced its vector; search uses only vectors from the current
embedder and reports any it had to skip (re-indexing is an explicit admin command, never part of a request).
"""

import numpy as np
from django.conf import settings
from django.db import models

POLICY_AREAS = (
    "billing",
    "cancellation",
    "privacy",
    "reminders",
    "rescheduling",
    "telehealth",
    "access",
    "results",
    "other",
)


class PolicyDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "No approved version yet"
        APPROVED = "approved", "Approved: its current version is searchable"
        RETIRED = "retired", "Retired: not searchable, kept for audit"

    class Source(models.TextChoices):
        SEED = "seed", "Approved policy shipped with the app"
        UPLOAD = "upload", "Uploaded by an admin"

    filename = models.CharField(max_length=100)
    policy_area = models.CharField(max_length=20, choices=[(a, a) for a in POLICY_AREAS], default="other")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=10, choices=Source.choices)
    current_version = models.ForeignKey(
        "DocumentVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )  # who approved the current version
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)  # when the current version was approved
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["filename", "id"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.status})"


class DocumentVersion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for approval"
        CURRENT = "current", "The approved, searchable edition"
        SUPERSEDED = "superseded", "Replaced by a later approved edition"
        REJECTED = "rejected", "Rejected by an admin"

    document = models.ForeignKey(PolicyDocument, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    content = models.TextField()
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    effective_date = models.DateField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )  # approved or rejected it
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["document_id", "number"]
        constraints = [models.UniqueConstraint(fields=["document", "number"], name="version_number_per_document")]

    def __str__(self) -> str:
        return f"{self.document.filename} v{self.number} ({self.status})"


def passage_id(filename: str, version: int, position: int) -> str:
    """Version 1 keeps Week 4's form (`billing.md#0`), so the frozen Week 4 evaluation's IDs still match.
    Later versions name their edition (`billing.md@v2#0`), so a citation always says which edition it came from."""
    return f"{filename}#{position}" if version == 1 else f"{filename}@v{version}#{position}"


class Chunk(models.Model):
    document = models.ForeignKey(PolicyDocument, on_delete=models.CASCADE, related_name="chunks")
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField()
    text = models.TextField()
    embedding = models.BinaryField()  # float32 vector, unit length
    embedding_model = models.CharField(max_length=100)  # e.g. "ollama/nomic-embed-text:latest"

    class Meta:
        ordering = ["document_id", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "position", "embedding_model"], name="chunk_unique_per_version_and_model"
            )
        ]

    @property
    def passage_id(self) -> str:
        return passage_id(self.document.filename, self.version.number, self.position)

    def vector(self) -> np.ndarray:
        return np.frombuffer(self.embedding, dtype=np.float32)


class AnswerRecord(models.Model):
    """Which document editions one assistant answer used, so the audit can always tell. Linked to the
    `admin.assistant_asked` audit event. Never stores the question or the answer text."""

    audit_event = models.OneToOneField(
        "audit.AuditEvent", on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    status = models.CharField(max_length=30)
    public_reason = models.CharField(max_length=40, blank=True)
    model = models.CharField(max_length=100, blank=True)
    # [{"passage_id", "document_id", "version", "sha256"}]: cited passages, and all passages given to the model
    citations = models.JSONField(default=list)
    sources = models.JSONField(default=list)
    # Week 5 Step 5: the turn number in its conversation, retries for invalid output, and the prompt's token
    # split. Never the question, the answer or the history itself.
    turn = models.PositiveSmallIntegerField(default=1)
    retries = models.PositiveSmallIntegerField(default=0)
    budget = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class IndexJob(models.Model):
    """One background indexing job (Week 5 Step 10): approving a pending version, run by a Celery worker.

    The states live here, not in Celery's result backend, so the audit page can join them to versions and
    admins. One open (queued or running) job per version, by a database constraint. Never holds document text.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting for a worker"
        RUNNING = "running", "A worker is indexing it"
        SUCCEEDED = "succeeded", "Indexed and swapped in"
        FAILED = "failed", "Failed; the version stays pending"

    OPEN = (Status.QUEUED, Status.RUNNING)

    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="index_jobs")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    request_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    error_code = models.CharField(max_length=30, blank=True)  # a typed code only, never upstream error text
    chunks = models.PositiveIntegerField(null=True, blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-queued_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["version"],
                condition=models.Q(status__in=["queued", "running"]),
                name="one_open_index_job_per_version",
            )
        ]

    def __str__(self) -> str:
        return f"index job {self.pk} ({self.status})"
