"""Searching the approved documents.

Only the current version of an approved document has chunks (assistant/documents.py), and search also
filters on both, so a pending, superseded, rejected or retired edition can never be retrieved. Search uses
only chunks embedded by the CURRENT embedder: chunks from another embedder are skipped and counted, never
re-embedded during a request. Re-indexing is the explicit admin command
`manage.py reindex_documents`.
"""

from dataclasses import dataclass

import numpy as np

from .documents import approve, reindex_all  # noqa: F401  (Week 4 import paths; the lifecycle lives in documents.py)
from .embeddings import Embedder
from .models import Chunk, DocumentVersion, PolicyDocument
from .prompts import Passage


@dataclass
class SearchResult:
    passages: list[Passage]  # ranked, best first, all at or above the floor
    scores: list[float]
    stale_skipped: int  # approved-document chunks skipped because another embedder made them
    searched: int  # current chunks compared


def search(question: str, embedder: Embedder, top_k: int, floor: float) -> SearchResult:
    approved = Chunk.objects.filter(document__status=PolicyDocument.Status.APPROVED,
                                    version__status=DocumentVersion.Status.CURRENT).select_related("document", "version")
    current = list(approved.filter(embedding_model=embedder.identity))
    stale = approved.exclude(embedding_model=embedder.identity).count()
    if not current:
        return SearchResult([], [], stale, 0)
    q = embedder.embed([question])[0]
    matrix = np.stack([c.vector() for c in current])
    similarity = matrix @ q  # vectors are unit length, so this is cosine similarity
    order = [i for i in np.argsort(-similarity, kind="stable") if similarity[i] >= floor][:top_k]
    return SearchResult(
        passages=[Passage(current[i].passage_id, current[i].document.filename, current[i].text,
                          version=current[i].version.number, document_id=current[i].document_id,
                          sha256=current[i].version.sha256) for i in order],
        scores=[float(similarity[i]) for i in order], stale_skipped=stale, searched=len(current))
