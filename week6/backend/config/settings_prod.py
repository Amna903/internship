"""Production settings (Week 6 Step 2). Use DJANGO_SETTINGS_MODULE=config.settings_prod behind the TLS proxy.

Safe defaults are set before the shared base loads, and the result is then checked: the process refuses to
start if any production invariant is broken, rather than running half-secured.
"""

import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

for key, value in {
    "DJANGO_DEBUG": "false",
    "COOKIE_SECURE": "true",
    "SECURE_SSL_REDIRECT": "true",
    "BEHIND_TLS_PROXY": "true",
    "SECURE_HSTS_SECONDS": "86400",
    "ENABLE_API_DOCS": "false",
}.items():
    os.environ.setdefault(key, value)

from .settings import *  # noqa: E402,F401,F403
from .settings import (  # noqa: E402
    ALLOWED_HOSTS,
    COOKIE_SECURE,
    CSRF_TRUSTED_ORIGINS,
    DEBUG,
    SECURE_HSTS_SECONDS,
    SECURE_SSL_REDIRECT,
)

PROD_ERRORS = []
if DEBUG:
    PROD_ERRORS.append("DJANGO_DEBUG must be false.")
if not COOKIE_SECURE:
    PROD_ERRORS.append("COOKIE_SECURE must be true.")
if not SECURE_SSL_REDIRECT:
    PROD_ERRORS.append("SECURE_SSL_REDIRECT must be true.")
if os.environ.get("BEHIND_TLS_PROXY", "").lower() != "true":
    PROD_ERRORS.append("BEHIND_TLS_PROXY must be true (requests arrive through the HTTPS proxy).")
if SECURE_HSTS_SECONDS <= 0:
    PROD_ERRORS.append("SECURE_HSTS_SECONDS must be positive.")
LOCAL = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
_origin_hosts = [urlparse(o).hostname or "" for o in CSRF_TRUSTED_ORIGINS]  # exact names: *.localhost is allowed
if any(h in LOCAL for h in ALLOWED_HOSTS) or any(h in LOCAL for h in _origin_hosts):
    PROD_ERRORS.append("DJANGO_ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS must not name localhost in production.")
if any(not o.startswith("https://") for o in CSRF_TRUSTED_ORIGINS):
    PROD_ERRORS.append("CSRF_TRUSTED_ORIGINS must be https:// origins.")
# Internal probes (container healthchecks) reach /health/ and /ready/ over plain HTTP inside the network.
SECURE_REDIRECT_EXEMPT = [r"^health/$", r"^ready/$"]

if PROD_ERRORS:
    raise ImproperlyConfigured("Production settings refused:\n  - " + "\n  - ".join(PROD_ERRORS))
