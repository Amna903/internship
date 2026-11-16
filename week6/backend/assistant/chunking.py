"""Split a policy into overlapping chunks of whole sentences.

Chunks are sized by an APPROXIMATE token count (see prompts.approx_tokens) so a few retrieved chunks fit
the prompt budget comfortably. Consecutive chunks share their boundary sentence, so a fact that spans two
sentences is still found whole in at least one chunk. Markdown headings are dropped (they carry no policy
content).
"""

import re

from .prompts import approx_tokens

CHUNK_TOKENS = 80
OVERLAP_SENTENCES = 1


def sentences(text: str) -> list[str]:
    body = " ".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(body.split())) if s.strip()]


def chunk(text: str, max_tokens: int = CHUNK_TOKENS, overlap: int = OVERLAP_SENTENCES) -> list[str]:
    parts = sentences(text)
    chunks, current = [], []
    for s in parts:
        if current and approx_tokens(" ".join(current + [s])) > max_tokens:
            chunks.append(" ".join(current))
            current = current[-overlap:] if overlap else []
        current.append(s)
    if current and (not chunks or " ".join(current) not in chunks[-1]):
        chunks.append(" ".join(current))
    return chunks
