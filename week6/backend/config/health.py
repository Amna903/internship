"""Liveness and readiness (Week 6). /health/: the process answers. /ready/: it can serve traffic.

/ready/ checks the database, the job broker (Redis) and the served model artifact; any failure gives 503.
The LLM (Ollama) is reported but doesn't gate readiness: without it the assistant and agent answer
"unavailable" calmly while everything else keeps working. Only check names and "ok"/"error" are returned,
never connection strings or error text.
"""

import socket
import time
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def health(request):
    return JsonResponse({"status": "ok"})


def _db() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone()[0] == 1


def _broker() -> bool:
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return True  # unit tests: no broker by design
    url = urlparse(settings.CELERY_BROKER_URL)
    with socket.create_connection((url.hostname, url.port or 6379), timeout=1) as s:
        s.sendall(b"PING\r\n")
        return s.recv(16).startswith(b"+PONG")


def _model() -> bool:
    from ml.inference import get_model

    return bool(get_model().version)


def _llm() -> bool:
    url = urlparse(settings.ASSISTANT["OLLAMA_URL"])
    if settings.ASSISTANT["PROVIDER"] == "fake":
        return True
    with socket.create_connection((url.hostname, url.port or 11434), timeout=1):
        return True


def _run(check) -> tuple[str, float]:
    started = time.perf_counter()
    try:
        ok = check()
    except Exception:  # never echo the reason (it may contain hosts or credentials)
        ok = False
    return ("ok" if ok else "error"), round((time.perf_counter() - started) * 1000, 1)


def ready(request):
    checks = {name: _run(fn) for name, fn in (("database", _db), ("broker", _broker), ("model", _model), ("llm", _llm))}
    gating = ("database", "broker", "model")
    ok = all(checks[n][0] == "ok" for n in gating)
    body = {
        "status": "ready" if ok else "not_ready",
        "checks": {n: {"status": s, "ms": ms, "gates_readiness": n in gating} for n, (s, ms) in checks.items()},
    }
    return JsonResponse(body, status=200 if ok else 503)
