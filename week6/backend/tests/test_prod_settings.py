"""Week 6 Step 2: production settings refuse unsafe configurations; security headers, CSRF, cookies and
same-origin-only CORS under the production module. Each refusal is checked in a fresh subprocess."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
GOOD = {"DJANGO_SECRET_KEY": "s" * 40 + "a1B2c3", "JWT_SIGNING_KEY": "j" * 40 + "z9Y8x7",
        "DJANGO_ALLOWED_HOSTS": "clinic.example.org", "CSRF_TRUSTED_ORIGINS": "https://clinic.example.org",
        "DATABASE_URL": "sqlite:////tmp/prod-check.sqlite3"}
CLEAR = ("DJANGO_DEBUG", "COOKIE_SECURE", "SECURE_SSL_REDIRECT", "BEHIND_TLS_PROXY", "SECURE_HSTS_SECONDS",
         "ENABLE_API_DOCS", "COOKIE_SAMESITE")


def load(**overrides):
    env = {k: v for k, v in os.environ.items() if k not in CLEAR and not k.startswith("DJANGO_") and k != "DATABASE_URL"}
    env |= GOOD | {"DJANGO_SETTINGS_MODULE": "config.settings_prod"} | overrides
    code = ("import django; django.setup(); from django.conf import settings as s; "
            "print(s.DEBUG, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS)")
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)


def test_good_production_settings_load_with_secure_defaults():
    r = load()
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["False", "True", "True", "True", "86400"]


@pytest.mark.parametrize("overrides, message", [
    ({"DJANGO_DEBUG": "true"}, "DJANGO_DEBUG must be false"),
    ({"COOKIE_SECURE": "false"}, "COOKIE_SECURE"),
    ({"SECURE_SSL_REDIRECT": "false"}, "SECURE_SSL_REDIRECT"),
    ({"BEHIND_TLS_PROXY": "false"}, "BEHIND_TLS_PROXY"),
    ({"SECURE_HSTS_SECONDS": "0"}, "SECURE_HSTS_SECONDS"),
    ({"DJANGO_ALLOWED_HOSTS": "localhost"}, "localhost"),
    ({"CSRF_TRUSTED_ORIGINS": "http://clinic.example.org"}, "https://"),
    ({"DJANGO_ALLOWED_HOSTS": "*"}, "real hostnames"),
    ({"DJANGO_SECRET_KEY": "short"}, "at least 32"),
    ({"JWT_SIGNING_KEY": GOOD["DJANGO_SECRET_KEY"]}, "must differ"),
])
def test_unsafe_production_settings_refuse_to_start(overrides, message):
    r = load(**overrides)
    assert r.returncode != 0 and message in r.stderr


def test_dev_settings_are_debug_over_http():
    env = {k: v for k, v in os.environ.items() if k not in CLEAR and k != "DJANGO_SETTINGS_MODULE"}
    env |= {"DJANGO_SETTINGS_MODULE": "config.settings_dev", "DJANGO_SECRET_KEY": "dev-key"}
    r = subprocess.run([sys.executable, "-c", "import django; django.setup(); from django.conf import settings as s; "
                        "print(s.DEBUG, s.SESSION_COOKIE_SECURE)"], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert r.stdout.split() == ["True", "False"], r.stderr


@pytest.mark.django_db
class TestHeaders:
    def test_security_headers(self, client):
        r = client.get("/health/")
        assert r["X-Content-Type-Options"] == "nosniff" and r["X-Frame-Options"] == "DENY"
        assert r["Referrer-Policy"] == "same-origin"

    def test_no_cors_for_a_foreign_origin(self, client):
        r = client.get("/health/", HTTP_ORIGIN="https://evil.example")
        assert "Access-Control-Allow-Origin" not in r
        r = client.options("/api/auth/user/login/", HTTP_ORIGIN="https://evil.example",
                           HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        assert "Access-Control-Allow-Origin" not in r

    def test_csrf_is_enforced_on_unsafe_methods(self, admin):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        r = c.post("/api/admin/login/", {"email": admin.email, "password": "x"}, content_type="application/json")
        assert r.status_code == 403
