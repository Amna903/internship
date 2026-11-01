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
os.environ["ASSISTANT_PROVIDER"] = "fake"  # CI has no Ollama; tests never call a real model
os.environ["ASSISTANT_EMBEDDER"] = "fake"  # deterministic offline embeddings in tests and CI
os.environ["ENABLE_API_DOCS"] = "true"

from .settings import *  # noqa: E402,F401,F403
