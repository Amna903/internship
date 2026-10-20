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
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Run `python scripts/init_env.py` to create a .env file."
    )
if not DEBUG and (SECRET_KEY.startswith("replace-me") or len(SECRET_KEY) < 32):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a real random value (>= 32 chars) when DEBUG is off.")

# JWTs are signed with their own key so that a leak of one key does not compromise the other mechanism.
JWT_SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY") or SECRET_KEY

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")

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
COOKIE_SECURE = env_bool("COOKIE_SECURE", not DEBUG)

SESSION_COOKIE_NAME = "hp_admin_session"
SESSION_COOKIE_AGE = env_int("ADMIN_SESSION_MINUTES", 30) * 60  # idle timeout (sliding, see below)
SESSION_SAVE_EVERY_REQUEST = True  # every request pushes the expiry forward -> idle timeout
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = COOKIE_SECURE
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to echo it in the X-CSRFToken header
CSRF_COOKIE_SAMESITE = "Lax"
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
if not DEBUG:
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)  # raise once HTTPS is verified
    SECURE_REFERRER_POLICY = "same-origin"

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
