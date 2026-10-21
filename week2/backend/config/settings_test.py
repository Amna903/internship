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
os.environ["ENABLE_API_DOCS"] = "true"

from .settings import *  # noqa: E402,F401,F403
