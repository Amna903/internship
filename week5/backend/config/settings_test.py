"""Settings used by pytest. Forces production-like cookie/CSRF behaviour regardless of any local .env."""

import os

os.environ["DJANGO_SECRET_KEY"] = "test-only-secret-key-do-not-use-anywhere-else-0123456789"
os.environ["JWT_SIGNING_KEY"] = "test-only-jwt-signing-key-do-not-use-anywhere-else-0123456789"
os.environ["DJANGO_DEBUG"] = "false"
os.environ["COOKIE_SECURE"] = "true"
os.environ["COOKIE_SAMESITE"] = "Lax"
os.environ["DJANGO_ALLOWED_HOSTS"] = "testserver,localhost"
os.environ["CSRF_TRUSTED_ORIGINS"] = "http://testserver"
os.environ["ACCESS_TOKEN_MINUTES"] = "10"
os.environ["REFRESH_TOKEN_DAYS"] = "7"
os.environ["ADMIN_SESSION_MINUTES"] = "30"
os.environ["THROTTLE_LOGIN"] = "10/min"
os.environ["THROTTLE_SIGNUP"] = "20/hour"
os.environ["THROTTLE_PREDICTIONS"] = "60/min"
os.environ["THROTTLE_CLUSTERS"] = "60/min"
os.environ["THROTTLE_ASSISTANT"] = "10/min"
os.environ["THROTTLE_AGENT_ACTIONS"] = "30/min"
os.environ["THROTTLE_AGENT"] = "10/min"
os.environ["ASSISTANT_PROVIDER"] = "fake"  # CI has no Ollama; tests never call a real model
# Deterministic offline embeddings in tests and CI. Only the test-only "flaky" fake may be chosen instead (the
# real-worker job test injects failures with it); anything else, such as a developer's "ollama", is overridden.
os.environ["ASSISTANT_EMBEDDER"] = "flaky" if os.environ.get("ASSISTANT_EMBEDDER") == "flaky" else "fake"
os.environ["ENABLE_API_DOCS"] = "true"
# Unit tests run jobs inline with no broker and no backoff. The real-worker test (tests/test_index_worker.py)
# starts its worker with CELERY_TASK_ALWAYS_EAGER=false, so these are defaults, not overrides.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("INDEX_JOB_BACKOFF", "0,0")

from .settings import *  # noqa: E402,F401,F403
