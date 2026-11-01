"""One interface for the language model, with a real local client and a fake one.

`OllamaClient` talks to a local Ollama server (no data leaves the machine). `FakeLLM` returns scripted
replies, and can simulate slowness, errors and invalid output, so every safety path is tested in CI,
where there is no Ollama. Callers only ever see an `LLMReply` or one of the errors below; the reason for
a failure goes to the server log, never to the user.

Timeouts: one HTTP call per answer (stream=false), so the socket timeout is effectively the deadline for
the whole answer. It allows for a COLD START: the first call after Ollama loads the model took about 9 s
for embeddings and is slower for generation, so the deadline is generous and `manage.py warm_llm` can
load the model ahead of time.
"""

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from django.conf import settings


class LLMError(Exception):
    """Base class. `reason` is for the server log only."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LLMUnavailable(LLMError):
    """The model server can't be reached or answered with an error."""


class LLMTimeout(LLMError):
    """The model did not answer before the deadline."""


@dataclass
class LLMReply:
    text: str
    model: str
    prompt_tokens: int  # as counted by the model server (exact, unlike the prompt budget estimate)
    output_tokens: int
    seconds: float


class LLMClient:
    """chat(messages, json_schema) -> LLMReply, or raises LLMUnavailable / LLMTimeout."""

    model = "unknown"

    def chat(self, messages: list[dict], json_schema: dict) -> LLMReply:
        raise NotImplementedError


class OllamaClient(LLMClient):
    def __init__(self, base_url: str, model: str, temperature: float, max_output_tokens: int, context_tokens: int,
                 timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.context_tokens = context_tokens
        self.timeout_seconds = timeout_seconds

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(f"{self.base_url}{path}", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read())
        except (socket.timeout, TimeoutError) as exc:
            raise LLMTimeout(f"no answer within {self.timeout_seconds}s") from exc
        except urllib.error.HTTPError as exc:
            raise LLMUnavailable(f"model server returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise LLMTimeout(f"no answer within {self.timeout_seconds}s") from exc
            raise LLMUnavailable(f"model server unreachable: {exc.reason.__class__.__name__}") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise LLMUnavailable("model server sent a response that is not JSON") from exc

    def chat(self, messages: list[dict], json_schema: dict) -> LLMReply:
        started = time.monotonic()
        body = self._post("/api/chat", {
            "model": self.model, "messages": messages, "stream": False,
            # Ollama's structured-output option: the reply is constrained to this JSON schema. The server
            # still validates it (assistant/schema.py), because a constrained reply can be empty or cut off.
            "format": json_schema,
            "options": {"temperature": self.temperature, "num_predict": self.max_output_tokens,
                        "num_ctx": self.context_tokens},
        })
        try:
            text = body["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMUnavailable("model server response has no message content") from exc
        return LLMReply(text=text, model=self.model, prompt_tokens=int(body.get("prompt_eval_count") or 0),
                        output_tokens=int(body.get("eval_count") or 0), seconds=time.monotonic() - started)

    def warm_up(self) -> float:
        """Load the model into memory with a one-token call; returns the seconds it took."""
        started = time.monotonic()
        self._post("/api/generate", {"model": self.model, "prompt": "ok", "stream": False,
                                     "options": {"num_predict": 1}})
        return time.monotonic() - started


@dataclass
class FakeLLM(LLMClient):
    """Scripted replies for tests and CI. Each item in `replies` is a string (returned as the reply text)
    or an exception instance (raised). `seen` keeps every message list it was sent, so tests can check
    exactly what would have reached a real model."""

    replies: list = field(default_factory=list)
    model: str = "fake-llm"
    seen: list = field(default_factory=list)

    def chat(self, messages: list[dict], json_schema: dict) -> LLMReply:
        self.seen.append(messages)
        reply = self.replies.pop(0) if self.replies else json.dumps(
            {"status": "insufficient_information", "answer": "", "citations": []})
        if isinstance(reply, Exception):
            raise reply
        prompt_chars = sum(len(m["content"]) for m in messages)
        return LLMReply(text=reply, model=self.model, prompt_tokens=prompt_chars // 4,
                        output_tokens=len(reply) // 4, seconds=0.0)


def get_llm() -> LLMClient:
    """The configured client. Settings: settings.ASSISTANT (from environment variables)."""
    cfg = settings.ASSISTANT
    if cfg["PROVIDER"] == "fake":
        return FakeLLM()
    return OllamaClient(base_url=cfg["OLLAMA_URL"], model=cfg["MODEL"], temperature=cfg["TEMPERATURE"],
                        max_output_tokens=cfg["MAX_OUTPUT_TOKENS"], context_tokens=cfg["CONTEXT_TOKENS"],
                        timeout_seconds=cfg["TIMEOUT_SECONDS"])
