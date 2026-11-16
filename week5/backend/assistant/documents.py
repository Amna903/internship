"""Document lifecycle: create, add a version, approve (atomic swap), reject, retire, and the corpus snapshot.

Rules:
- a new document, and every update to one, arrives as a PENDING version with no chunks;
- approving a version embeds it FIRST, outside the lock (embedding can be slow or fail), then, in one
  transaction holding the document's row lock: re-check it is still pending, write the new chunks, mark it
  current and the previous version superseded, and delete the previous version's chunks. A failed
  embedding changes nothing, so the old edition stays live;
- retiring removes every chunk of the document but keeps all its versions for audit. Restoring it means
  uploading a new version, which needs approval like any other;
- at most one pending version per document, and an update identical to the current text is refused.

The corpus snapshot names the exact edition of every searchable document. Evaluation runs record it and
refuse to run when it differs from the corpus their frozen set was written against.
"""

from dataclasses import dataclass

import numpy as np
from django.db import transaction
from django.utils import timezone

from .chunking import chunk
from .embeddings import Embedder
from .models import Chunk, DocumentVersion, PolicyDocument

Status, VStatus = PolicyDocument.Status, DocumentVersion.Status


class DocumentError(ValueError):
    """A refused lifecycle step. `code` is the API error code; the message is safe to show."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _duplicate_anywhere(sha256: str) -> bool:
    """The same text is already live or waiting somewhere (retired documents and old editions don't count)."""
    return DocumentVersion.objects.filter(sha256=sha256, status__in=[VStatus.PENDING, VStatus.CURRENT]).exclude(
        document__status=Status.RETIRED).exists()


def create_document(filename: str, content: str, sha256: str, source: str, uploaded_by, policy_area: str = "other",
                    effective_date=None) -> PolicyDocument:
    if _duplicate_anywhere(sha256):
        raise DocumentError("A document with exactly this content already exists.", "duplicate_document")
    with transaction.atomic():
        document = PolicyDocument.objects.create(filename=filename, policy_area=policy_area, source=source,
                                                 uploaded_by=uploaded_by)
        DocumentVersion.objects.create(document=document, number=1, content=content, sha256=sha256,
                                       effective_date=effective_date, uploaded_by=uploaded_by)
    return document


def add_version(document: PolicyDocument, content: str, sha256: str, uploaded_by, effective_date=None) -> DocumentVersion:
    with transaction.atomic():
        document = PolicyDocument.objects.select_for_update().get(pk=document.pk)
        if document.versions.filter(status=VStatus.PENDING).exists():
            raise DocumentError("This document already has a version waiting for approval.", "version_pending")
        current = document.current_version
        if current is not None and current.sha256 == sha256 and document.status != Status.RETIRED:
            raise DocumentError("This is identical to the current version.", "duplicate_document")
        if _duplicate_anywhere(sha256):
            raise DocumentError("A document with exactly this content already exists.", "duplicate_document")
        number = (document.versions.order_by("-number").values_list("number", flat=True).first() or 0) + 1
        return DocumentVersion.objects.create(document=document, number=number, content=content, sha256=sha256,
                                              effective_date=effective_date, uploaded_by=uploaded_by)


def _embed(version: DocumentVersion, embedder: Embedder, chunk_tokens: int | None = None) -> tuple[list[str], np.ndarray]:
    texts = chunk(version.content, max_tokens=chunk_tokens) if chunk_tokens else chunk(version.content)
    return texts, (embedder.embed(texts) if texts else np.zeros((0, 0), dtype=np.float32))


def _write_chunks(version: DocumentVersion, texts: list[str], vectors: np.ndarray, embedder: Embedder) -> None:
    version.chunks.filter(embedding_model=embedder.identity).delete()
    Chunk.objects.bulk_create([
        Chunk(document_id=version.document_id, version=version, position=i, text=t,
              embedding=v.astype(np.float32).tobytes(), embedding_model=embedder.identity)
        for i, (t, v) in enumerate(zip(texts, vectors))])


@dataclass
class Approval:
    version: DocumentVersion
    previous: int | None  # the version number it replaced
    chunks: int


def approve_version(version: DocumentVersion, admin, embedder: Embedder, chunk_tokens: int | None = None) -> Approval:
    if version.status != VStatus.PENDING:
        raise DocumentError("Only a version waiting for approval can be approved.", "not_pending")
    texts, vectors = _embed(version, embedder, chunk_tokens)  # may raise LLMError: nothing has changed yet
    with transaction.atomic():
        document = PolicyDocument.objects.select_for_update().get(pk=version.document_id)
        version = DocumentVersion.objects.get(pk=version.pk)
        if version.status != VStatus.PENDING:  # someone else decided it while we were embedding
            raise DocumentError("Only a version waiting for approval can be approved.", "not_pending")
        previous = document.current_version
        _write_chunks(version, texts, vectors, embedder)
        now = timezone.now()
        version.status, version.decided_by, version.decided_at = VStatus.CURRENT, admin, now
        version.save(update_fields=["status", "decided_by", "decided_at"])
        if previous is not None and previous.pk != version.pk:
            previous.status = VStatus.SUPERSEDED
            previous.save(update_fields=["status"])
            previous.chunks.all().delete()
        document.current_version, document.status = version, Status.APPROVED
        document.approved_by, document.approved_at = admin, now
        document.retired_by, document.retired_at = None, None
        document.save(update_fields=["current_version", "status", "approved_by", "approved_at", "retired_by", "retired_at"])
    return Approval(version, previous.number if previous is not None and previous.pk != version.pk else None, len(texts))


def pending_version(document: PolicyDocument) -> DocumentVersion | None:
    return document.versions.filter(status=VStatus.PENDING).first()


def approve(document: PolicyDocument, admin, embedder: Embedder) -> int:
    """Week 4's shortcut: approve the document's pending version. Returns the number of chunks."""
    version = pending_version(document)
    if version is None:
        raise DocumentError("This document has no version waiting for approval.", "not_pending")
    return approve_version(version, admin, embedder).chunks


def reject_version(version: DocumentVersion, admin) -> DocumentVersion:
    with transaction.atomic():
        PolicyDocument.objects.select_for_update().get(pk=version.document_id)
        version = DocumentVersion.objects.get(pk=version.pk)
        if version.status != VStatus.PENDING:
            raise DocumentError("Only a version waiting for approval can be rejected.", "not_pending")
        version.status, version.decided_by, version.decided_at = VStatus.REJECTED, admin, timezone.now()
        version.save(update_fields=["status", "decided_by", "decided_at"])
    return version


def retire(document: PolicyDocument, admin) -> PolicyDocument:
    with transaction.atomic():
        document = PolicyDocument.objects.select_for_update().get(pk=document.pk)
        if document.status == Status.RETIRED:
            raise DocumentError("This document is already retired.", "already_retired")
        document.chunks.all().delete()
        document.status, document.retired_by, document.retired_at = Status.RETIRED, admin, timezone.now()
        document.save(update_fields=["status", "retired_by", "retired_at"])
    return document


def searchable_versions():
    return DocumentVersion.objects.filter(status=VStatus.CURRENT, document__status=Status.APPROVED).select_related("document")


def reindex_all(embedder: Embedder, chunk_tokens: int | None = None) -> dict:
    """Admin command only. Re-embed every searchable version with the current embedder (and, if given, a new
    chunk size) and remove chunks left over from other embedders."""
    versions = list(searchable_versions())
    chunks = 0
    for v in versions:
        texts, vectors = _embed(v, embedder, chunk_tokens)
        with transaction.atomic():
            _write_chunks(v, texts, vectors, embedder)
        chunks += len(texts)
    stale_removed, _ = Chunk.objects.exclude(embedding_model=embedder.identity).delete()
    return {"documents": len(versions), "chunks": chunks, "stale_removed": stale_removed}


# ---------------------------------------------------------------- corpus snapshot

def corpus_snapshot() -> list[dict]:
    """The exact edition of every searchable document, sorted by filename."""
    return sorted(({"filename": v.document.filename, "document_id": v.document_id, "version": v.number,
                    "sha256": v.sha256} for v in searchable_versions()), key=lambda r: (r["filename"], r["document_id"]))


class CorpusMismatch(RuntimeError):
    pass


def check_corpus(expected: dict[str, tuple[int, str]]) -> list[dict]:
    """Return the snapshot if the searchable documents are exactly `expected` ({filename: (version, sha256)});
    otherwise raise CorpusMismatch naming every difference. An evaluation must never quietly run against a
    different corpus from the one its frozen set was written for."""
    snapshot = corpus_snapshot()
    actual: dict[str, list[tuple[int, str]]] = {}
    for r in snapshot:
        actual.setdefault(r["filename"], []).append((r["version"], r["sha256"]))
    problems = [f"missing: {name} v{v}" for name, (v, _) in sorted(expected.items()) if name not in actual]
    problems += [f"not expected: {name}" for name in sorted(actual) if name not in expected]
    for name, (v, sha) in sorted(expected.items()):
        found = actual.get(name)
        if found and found != [(v, sha)]:
            problems.append(f"changed: {name} expected v{v} ({sha[:12]}), found " +
                            ", ".join(f"v{fv} ({fs[:12]})" for fv, fs in found))
    if problems:
        raise CorpusMismatch("The searchable documents differ from the corpus this evaluation set was frozen against: "
                             + "; ".join(problems) + ". Restore that corpus, or freeze a new set with a dated decision.")
    return snapshot
