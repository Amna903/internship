"""Django settings for the HealthProfile project.

Everything environment-specific comes from environment variables (see .env.example).
No secret ever lives in source control.
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Real environment variables always win over .env (override=False).
# HP_SKIP_DOTENV lets the config tests check the environment exactly as a server would see it.
if not os.environ.get("HP_SKIP_DOTENV"):
    load_dotenv(BASE_DIR / ".env")


# Every configuration problem is collected here and raised together at the end of this module,
# so a misconfigured deployment fails at startup with one message listing everything to fix.
CONFIG_ERRORS: list[str] = []


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    CONFIG_ERRORS.append(f"{name}={raw!r} is not a boolean (use true/false).")
    return default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        CONFIG_ERRORS.append(f"{name}={raw!r} is not an integer.")
        return default


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        CONFIG_ERRORS.append(f"{name} is required when DJANGO_DEBUG is off.")
    return value


def check_secret(name: str, value: str) -> None:
    if value and (value.startswith("replace-me") or len(value) < 32):
        CONFIG_ERRORS.append(f"{name} must be a real random value of at least 32 characters.")


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Run `python scripts/init_env.py` to create a .env file."
    )

# JWTs are signed with their own key so that a leak of one key does not compromise the other mechanism.
# Local DEBUG runs may fall back to SECRET_KEY; production must set a separate key explicitly.
JWT_SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY", "").strip()

if DEBUG:
    JWT_SIGNING_KEY = JWT_SIGNING_KEY or SECRET_KEY
    ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
else:
    check_secret("DJANGO_SECRET_KEY", SECRET_KEY)
    if not JWT_SIGNING_KEY:
        env_required("JWT_SIGNING_KEY")
    check_secret("JWT_SIGNING_KEY", JWT_SIGNING_KEY)
    if JWT_SIGNING_KEY and JWT_SIGNING_KEY == SECRET_KEY:
        CONFIG_ERRORS.append("JWT_SIGNING_KEY must differ from DJANGO_SECRET_KEY.")
    # No localhost defaults in production: the deployment must say which hosts and origins it serves.
    ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
    CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
    for name, value in (("DJANGO_ALLOWED_HOSTS", ALLOWED_HOSTS), ("CSRF_TRUSTED_ORIGINS", CSRF_TRUSTED_ORIGINS)):
        if not value:
            env_required(name)
    if "*" in ALLOWED_HOSTS:
        CONFIG_ERRORS.append("DJANGO_ALLOWED_HOSTS must list real hostnames, not '*'.")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "accounts",
    "profiles",
    "adminpanel",
    "audit",
    "predictions",
    "assistant",
    "agent",
    "monitoring",
]

MIDDLEWARE = [
    "config.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# --------------------------------------------------------------------------
# Database: PostgreSQL via DATABASE_URL, SQLite fallback for quick local runs.
# --------------------------------------------------------------------------
DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

# --------------------------------------------------------------------------
# Passwords: Argon2id first (OWASP recommendation), PBKDF2 kept so older hashes still verify.
# --------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Cookies, sessions (admin flow) and CSRF
# --------------------------------------------------------------------------
# One explicit policy for every cookie we set (JWT, admin session, CSRF).
COOKIE_SECURE = env_bool("COOKIE_SECURE", not DEBUG)
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "Lax").strip().capitalize()
if COOKIE_SAMESITE not in {"Lax", "Strict"}:
    # "None" would send auth cookies on cross-site requests; this app is same-origin by design.
    CONFIG_ERRORS.append(f"COOKIE_SAMESITE must be Lax or Strict, got {COOKIE_SAMESITE!r}.")
if not DEBUG and not COOKIE_SECURE:
    CONFIG_ERRORS.append("COOKIE_SECURE cannot be false when DJANGO_DEBUG is off (auth cookies would travel over plain HTTP).")

SESSION_COOKIE_NAME = "hp_admin_session"
SESSION_COOKIE_AGE = env_int("ADMIN_SESSION_MINUTES", 30) * 60  # idle timeout (sliding, see below)
SESSION_SAVE_EVERY_REQUEST = True  # every request pushes the expiry forward -> idle timeout
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = COOKIE_SAMESITE
SESSION_COOKIE_SECURE = COOKIE_SECURE
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to echo it in the X-CSRFToken header
CSRF_COOKIE_SAMESITE = COOKIE_SAMESITE
CSRF_COOKIE_SECURE = COOKIE_SECURE
CSRF_FAILURE_VIEW = "config.exceptions.csrf_failure"

# --------------------------------------------------------------------------
# JWT (standard-user flow). Tokens travel only in HttpOnly cookies.
# --------------------------------------------------------------------------
JWT_ACCESS_COOKIE = "hp_access"
JWT_REFRESH_COOKIE = "hp_refresh"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("ACCESS_TOKEN_MINUTES", 10)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("REFRESH_TOKEN_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "UPDATE_LAST_LOGIN": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --------------------------------------------------------------------------
# Django REST Framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    # No global authentication: each view declares exactly which mechanism it accepts,
    # so JWT and session auth can never be mixed up by accident.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "login": os.environ.get("THROTTLE_LOGIN", "10/min"),
        "signup": os.environ.get("THROTTLE_SIGNUP", "20/hour"),
        "predictions": os.environ.get("THROTTLE_PREDICTIONS", "60/min"),
        "clusters": os.environ.get("THROTTLE_CLUSTERS", "60/min"),
        # Each assistant call runs a local model for seconds; a low limit protects the machine.
        "assistant": os.environ.get("THROTTLE_ASSISTANT", "10/min"),
        "agent_actions": os.environ.get("THROTTLE_AGENT_ACTIONS", "30/min"),
        # Each run can call the local model several times; a low limit protects the machine.
        "agent": os.environ.get("THROTTLE_AGENT", "10/min"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "HealthProfile API",
    "DESCRIPTION": (
        "Role-based HealthTech profile builder (synthetic data only, not a medical system).\n\n"
        "**Two authentication flows**\n"
        "- Standard users: JWT access/refresh tokens in HttpOnly cookies (`/api/auth/...`).\n"
        "- Admins: server-side session cookie (`/api/admin/...`).\n\n"
        "All state-changing requests need the CSRF token: call `GET /api/auth/csrf` first and send the "
        "`csrftoken` cookie value in an `X-CSRFToken` header."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}
ENABLE_API_DOCS = env_bool("ENABLE_API_DOCS", DEBUG)

# --------------------------------------------------------------------------
# Hardening for non-debug deployments
# --------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
if env_bool("BEHIND_TLS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "same-origin"
# HSTS is opt-in because it is sticky in browsers: set it once HTTPS is verified end to end.
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0) if not DEBUG else 0

# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True
STATIC_URL = "static/"

# Throttle counters live in the cache. Local-memory is fine for one process; use Redis in production.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

if CONFIG_ERRORS:
    raise ImproperlyConfigured("Invalid configuration:\n  - " + "\n  - ".join(CONFIG_ERRORS))


# ---- Week 4: clinic-policy FAQ assistant (local LLM through Ollama; nothing leaves the machine) ----
ASSISTANT = {
    "PROVIDER": os.environ.get("ASSISTANT_PROVIDER", "ollama"),  # "ollama" or "fake" (tests, CI)
    "OLLAMA_URL": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    "MODEL": os.environ.get("ASSISTANT_MODEL", "llama3.2:3b"),
    # Low but not zero: answers should stick to the passages and be repeatable; 0.1 keeps wording natural.
    "TEMPERATURE": float(os.environ.get("ASSISTANT_TEMPERATURE", "0.1")),
    # Room for a short answer plus up to 4 citations in JSON; longer output is cut off and fails validation.
    "MAX_OUTPUT_TOKENS": int(os.environ.get("ASSISTANT_MAX_OUTPUT_TOKENS", "512")),
    # The context window the model is asked to use; prompts are budgeted to fit (assistant/prompts.py).
    "CONTEXT_TOKENS": int(os.environ.get("ASSISTANT_CONTEXT_TOKENS", "4096")),
    # Deadline for one answer, including a cold start (first call after the model loads).
    "TIMEOUT_SECONDS": float(os.environ.get("ASSISTANT_TIMEOUT_SECONDS", "60")),
    # Sampling seed sent to Ollama, so runs repeat on the same machine (recorded in tuning and evaluation results).
    "SEED": int(os.environ.get("ASSISTANT_SEED", "42")),
    "EMBEDDER": os.environ.get("ASSISTANT_EMBEDDER", "ollama"),  # "ollama" or "fake" (tests, CI)
    "EMBED_MODEL": os.environ.get("ASSISTANT_EMBED_MODEL", "nomic-embed-text:latest"),
}

# Week 5 Step 10: background indexing jobs on Celery + Redis (config/celery.py, assistant/jobs.py).
# Job states live in assistant.IndexJob, so no result backend. Delivery is at least once (acks_late), and the
# job is safe to repeat. Eager mode (run inline, no broker) is for unit tests only (settings_test.py).
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_DEFAULT_QUEUE = os.environ.get("CELERY_QUEUE", "healthprofile")  # tests use their own queue name
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_TIMEOUT = 2  # seconds; a down broker fails the publish fast (queue_unavailable)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
INDEX_JOB = {
    "MAX_ATTEMPTS": 3,
    # Seconds to wait before retry 1 and retry 2 (only transient embedder failures are retried).
    "BACKOFF_SECONDS": [int(s) for s in os.environ.get("INDEX_JOB_BACKOFF", "5,10").split(",")],
    "SOFT_TIME_LIMIT": 120,
    "TIME_LIMIT": 150,
}

