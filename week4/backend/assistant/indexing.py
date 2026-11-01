"""Turning approved documents into searchable chunks, and searching them.

Only approved documents are ever chunked and embedded; a pending upload has no chunks, so it can never be
retrieved. Search uses only chunks embedded by the CURRENT embedder: chunks from another embedder are
skipped and counted, never re-embedded during a request. Re-indexing is the explicit admin command
`manage.py reindex_documents`.
"""

from dataclasses import dataclass

import numpy as np
from django.db import transaction
from django.utils import timezone

from .chunking import chunk
from .embeddings import Embedder
from .models import Chunk, PolicyDocument
from .prompts import Passage


def index_document(document: PolicyDocument, embedder: Embedder) -> int:
    """(Re)build one approved document's chunks for this embedder. Returns the number of chunks."""
    if document.status != PolicyDocument.Status.APPROVED:
        raise ValueError("only approved documents are indexed")
    texts = chunk(document.content)
    vectors = embedder.embed(texts) if texts else np.zeros((0, 0), dtype=np.float32)
    with transaction.atomic():
        document.chunks.filter(embedding_model=embedder.identity).delete()
        Chunk.objects.bulk_create([
            Chunk(document=document, position=i, text=t, embedding=v.astype(np.float32).tobytes(),
                  embedding_model=embedder.identity)
            for i, (t, v) in enumerate(zip(texts, vectors))])
    return len(texts)


def approve(document: PolicyDocument, admin, embedder: Embedder) -> int:
    """Embed first, then mark approved, in one transaction: a failed embedding leaves it pending."""
    with transaction.atomic():
        document.status = PolicyDocument.Status.APPROVED
        document.approved_by, document.approved_at = admin, timezone.now()
        document.save(update_fields=["status", "approved_by", "approved_at"])
        return index_document(document, embedder)


def reindex_all(embedder: Embedder) -> dict:
    """Admin command only. Re-embed every approved document with the current embedder and remove chunks
    left over from other embedders."""
    documents = list(PolicyDocument.objects.filter(status=PolicyDocument.Status.APPROVED))
    chunks = sum(index_document(d, embedder) for d in documents)
    stale_removed, _ = Chunk.objects.exclude(embedding_model=embedder.identity).delete()
    return {"documents": len(documents), "chunks": chunks, "stale_removed": stale_removed}


@dataclass
class SearchResult:
    passages: list[Passage]  # ranked, best first, all at or above the floor
    scores: list[float]
    stale_skipped: int  # approved-document chunks skipped because another embedder made them
    searched: int  # current chunks compared


def search(question: str, embedder: Embedder, top_k: int, floor: float) -> SearchResult:
    approved = Chunk.objects.filter(document__status=PolicyDocument.Status.APPROVED).select_related("document")
    current = list(approved.filter(embedding_model=embedder.identity))
    stale = approved.exclude(embedding_model=embedder.identity).count()
    if not current:
        return SearchResult([], [], stale, 0)
    q = embedder.embed([question])[0]
    matrix = np.stack([c.vector() for c in current])
    similarity = matrix @ q  # vectors are unit length, so this is cosine similarity
    order = [i for i in np.argsort(-similarity, kind="stable") if similarity[i] >= floor][:top_k]
    return SearchResult(
        passages=[Passage(current[i].passage_id, current[i].document.filename, current[i].text) for i in order],
        scores=[float(similarity[i]) for i in order], stale_skipped=stale, searched=len(current))
