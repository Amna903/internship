"""Production configuration must fail loudly at startup, never fall back silently.

Each case imports config.settings in a fresh interpreter with a controlled environment
(no .env file is read: DOTENV_PATH points nowhere), so the checks run exactly as on a server.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
SECRET = "s" * 50
JWT_KEY = "j" * 50
PROD = {
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": SECRET,
    "JWT_SIGNING_KEY": JWT_KEY,
    "DJANGO_ALLOWED_HOSTS": "app.example.test",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.test",
    "COOKIE_SECURE": "true",
}


def load_settings(env: dict[str, str]) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "JWT_", "COOKIE_", "CSRF_"))}
    clean["HP_SKIP_DOTENV"] = "1"
    code = "import config.settings as s; print(s.ALLOWED_HOSTS, s.COOKIE_SECURE, s.COOKIE_SAMESITE)"
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env={**clean, **env}, capture_output=True, text=True)


def without(key: str) -> dict[str, str]:
    return {k: v for k, v in PROD.items() if k != key}


def test_complete_production_config_loads():
    result = load_settings(PROD)
    assert result.returncode == 0, result.stderr
    assert "['app.example.test'] True Lax" in result.stdout


@pytest.mark.parametrize(
    "env, message",
    [
        (without("JWT_SIGNING_KEY"), "JWT_SIGNING_KEY is required"),
        ({**PROD, "JWT_SIGNING_KEY": SECRET}, "JWT_SIGNING_KEY must differ"),
        ({**PROD, "JWT_SIGNING_KEY": "short"}, "JWT_SIGNING_KEY must be a real random value"),
        ({**PROD, "DJANGO_SECRET_KEY": "replace-me" + "x" * 40}, "DJANGO_SECRET_KEY must be a real random value"),
        (without("DJANGO_ALLOWED_HOSTS"), "DJANGO_ALLOWED_HOSTS is required"),
        ({**PROD, "DJANGO_ALLOWED_HOSTS": "*"}, "not '*'"),
        (without("CSRF_TRUSTED_ORIGINS"), "CSRF_TRUSTED_ORIGINS is required"),
        ({**PROD, "COOKIE_SECURE": "false"}, "COOKIE_SECURE cannot be false"),
        ({**PROD, "COOKIE_SECURE": "ture"}, "is not a boolean"),
        ({**PROD, "COOKIE_SAMESITE": "None"}, "COOKIE_SAMESITE must be Lax or Strict"),
        ({**PROD, "ACCESS_TOKEN_MINUTES": "ten"}, "is not an integer"),
    ],
)
def test_production_refuses_unsafe_or_missing_config(env, message):
    result = load_settings(env)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr and message in result.stderr, result.stderr


def test_all_problems_are_reported_together():
    result = load_settings({"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": SECRET, "COOKIE_SECURE": "false"})
    for message in ("JWT_SIGNING_KEY is required", "DJANGO_ALLOWED_HOSTS is required",
                    "CSRF_TRUSTED_ORIGINS is required", "COOKIE_SECURE cannot be false"):
        assert message in result.stderr


def test_debug_keeps_local_defaults():
    result = load_settings({"DJANGO_DEBUG": "true", "DJANGO_SECRET_KEY": "dev", "COOKIE_SECURE": "false"})
    assert result.returncode == 0, result.stderr
    assert "['localhost', '127.0.0.1'] False Lax" in result.stdout
