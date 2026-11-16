"""Text embeddings: a local Ollama model, and a deterministic fake for tests and CI.

Each embedder has an `identity` (model name and version) that is stored with every vector it produces.
Vectors from different embedders are not comparable, so search only uses vectors whose identity matches
the current embedder.
"""

import hashlib
import json
import re
import socket
import urllib.error
import urllib.request

import numpy as np
from django.conf import settings

from .llm import LLMTimeout, LLMUnavailable


def unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)


class Embedder:
    identity = "unknown"

    def embed(self, texts: list[str]) -> np.ndarray:
        """One unit-length float32 row per text."""
        raise NotImplementedError


class OllamaEmbedder(Embedder):
    def __init__(self, base_url: str, model: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.identity = f"ollama/{model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        request = urllib.request.Request(f"{self.base_url}/api/embed",
                                         data=json.dumps({"model": self.model, "input": texts}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
        except (socket.timeout, TimeoutError) as exc:
            raise LLMTimeout(f"no embedding within {self.timeout_seconds}s") from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                raise LLMTimeout(f"no embedding within {self.timeout_seconds}s") from exc
            raise LLMUnavailable(f"embedding server unreachable or failed: {exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise LLMUnavailable("embedding server sent a response that is not JSON") from exc
        vectors = body.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise LLMUnavailable("embedding server returned the wrong number of vectors")
        return unit(np.asarray(vectors, dtype=np.float32))


class FakeEmbedder(Embedder):
    """Deterministic and offline: hashed word counts in DIMS buckets, unit length. The same text always gives
    the same vector, and texts that share words are similar, so retrieval tests are meaningful without a
    model. `version` lets tests simulate a changed embedder."""

    DIMS = 256

    def __init__(self, version: str = "v1"):
        self.identity = f"fake-hash/{version}"
        self._salt = version.encode()

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = np.zeros((len(texts), self.DIMS), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                bucket = int.from_bytes(hashlib.sha256(self._salt + word.encode()).digest()[:4], "big") % self.DIMS
                rows[i, bucket] += 1.0
        return unit(rows)


def get_embedder() -> Embedder:
    cfg = settings.ASSISTANT
    if cfg["EMBEDDER"] == "fake":
        return FakeEmbedder()
    return OllamaEmbedder(base_url=cfg["OLLAMA_URL"], model=cfg["EMBED_MODEL"], timeout_seconds=cfg["TIMEOUT_SECONDS"])
