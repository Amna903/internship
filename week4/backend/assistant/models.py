"""Policy documents and their searchable chunks.

A document is searchable only when an admin has approved it: uploads arrive as `pending` and have no
chunks at all until approval, so a pending document can't be retrieved even by mistake. Every chunk stores
the embedding model that produced its vector; search uses only vectors from the current embedder and
reports any it had to skip (re-indexing is an explicit admin command, never part of a request).
"""

import numpy as np
from django.conf import settings
from django.db import models


class PolicyDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"

    class Source(models.TextChoices):
        SEED = "seed", "Approved policy shipped with the app"
        UPLOAD = "upload", "Uploaded by an admin"

    filename = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64, unique=True)  # same content can't be uploaded twice
    content = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=10, choices=Source.choices)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["filename", "id"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.status})"


class Chunk(models.Model):
    document = models.ForeignKey(PolicyDocument, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField()
    text = models.TextField()
    embedding = models.BinaryField()  # float32 vector, unit length
    embedding_model = models.CharField(max_length=100)  # e.g. "ollama/nomic-embed-text:latest"

    class Meta:
        ordering = ["document_id", "position"]
        constraints = [models.UniqueConstraint(fields=["document", "position", "embedding_model"],
                                               name="chunk_unique_per_model")]

    @property
    def passage_id(self) -> str:
        return f"{self.document.filename}#{self.position}"

    def vector(self) -> np.ndarray:
        return np.frombuffer(self.embedding, dtype=np.float32)
