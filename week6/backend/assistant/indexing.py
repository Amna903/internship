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
    approved = Chunk.objects.filter(
        document__status=PolicyDocument.Status.APPROVED, version__status=DocumentVersion.Status.CURRENT
    ).select_related("document", "version")
    current = list(approved.filter(embedding_model=embedder.identity))
    stale = approved.exclude(embedding_model=embedder.identity).count()
    if not current:
        return SearchResult([], [], stale, 0)
    q = embedder.embed([question])[0]
    matrix = np.stack([c.vector() for c in current])
    similarity = matrix @ q  # vectors are unit length, so this is cosine similarity
    order = [i for i in np.argsort(-similarity, kind="stable") if similarity[i] >= floor][:top_k]
    return SearchResult(
        passages=[
            Passage(
                current[i].passage_id,
                current[i].document.filename,
                current[i].text,
                version=current[i].version.number,
                document_id=current[i].document_id,
                sha256=current[i].version.sha256,
            )
            for i in order
        ],
        scores=[float(similarity[i]) for i in order],
        stale_skipped=stale,
        searched=len(current),
    )


# ---------------------------------------------------------------- Week 5 Step 3: hybrid retrieval, gates, filters

SEMANTIC, HYBRID = "semantic", "hybrid"
GATE_S, GATE_SK = "S", "S+K"


@dataclass(frozen=True)
class RetrievalConfig:
    """One retrieval setting. `chunk_tokens` is fixed when the index is built; the rest act at query time."""

    method: str = SEMANTIC
    floor: float = 0.70
    top_k: int = 2
    rrf_k: int = 60
    gate: str = GATE_S
    f_kw: float = 1.0
    chunk_tokens: int = 80

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Candidates:
    """Every searchable chunk for one question, scored once, so many configurations can be compared cheaply."""

    chunks: list
    cosine: np.ndarray
    keyword: np.ndarray  # normalised BM25, 0..1
    stale_skipped: int


def _searchable(area: str | None = None, document: str | None = None):
    qs = Chunk.objects.filter(
        document__status=PolicyDocument.Status.APPROVED, version__status=DocumentVersion.Status.CURRENT
    ).select_related("document", "version")
    if area:
        qs = qs.filter(document__policy_area=area)
    if document:
        qs = qs.filter(document__filename=document)
    return qs


def candidates(question: str, embedder: Embedder, area: str | None = None, document: str | None = None) -> Candidates:
    from .bm25 import BM25

    qs = _searchable(area, document)
    current = list(qs.filter(embedding_model=embedder.identity))
    stale = qs.exclude(embedding_model=embedder.identity).count()
    if not current:
        return Candidates([], np.zeros(0), np.zeros(0), stale)
    q = embedder.embed([question])[0]
    cosine = np.stack([c.vector() for c in current]) @ q
    keyword = np.array(BM25([c.text for c in current]).normalised(question))
    return Candidates(current, cosine, keyword, stale)


def order(c: Candidates, cfg: RetrievalConfig) -> list[int]:
    """Chunk indexes, best first. Ties keep the stable database order, so results never depend on the machine."""
    by_cosine = [int(i) for i in np.argsort(-c.cosine, kind="stable")]
    if cfg.method == SEMANTIC:
        return by_cosine
    from .bm25 import rrf

    by_keyword = [int(i) for i in np.argsort(-c.keyword, kind="stable")]
    fused = np.array(rrf(by_cosine, by_keyword, k=cfg.rrf_k))
    return [int(i) for i in np.argsort(-fused, kind="stable")]


def passes(c: Candidates, i: int, cfg: RetrievalConfig) -> bool:
    return bool(c.cosine[i] >= cfg.floor or (cfg.gate == GATE_SK and c.keyword[i] >= cfg.f_kw))


def returned(c: Candidates, cfg: RetrievalConfig) -> list[int]:
    """What the assistant would actually use: ranked chunks that pass the gate, cut to top-k."""
    return [i for i in order(c, cfg) if passes(c, i, cfg)][: cfg.top_k]


def retrieve(
    question: str, embedder: Embedder, cfg: RetrievalConfig, area: str | None = None, document: str | None = None
) -> SearchResult:
    c = candidates(question, embedder, area, document)
    picked = returned(c, cfg)
    ch = c.chunks
    return SearchResult(
        passages=[
            Passage(
                ch[i].passage_id,
                ch[i].document.filename,
                ch[i].text,
                version=ch[i].version.number,
                document_id=ch[i].document_id,
                sha256=ch[i].version.sha256,
            )
            for i in picked
        ],
        scores=[float(c.cosine[i]) for i in picked],
        stale_skipped=c.stale_skipped,
        searched=len(ch),
    )
