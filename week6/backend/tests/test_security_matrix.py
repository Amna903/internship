"""Week 6 Step 10 (S2): an authorization matrix built from the URL configuration. Every /api/ route is called
anonymously and as a signed-in member with every method its view allows; only the explicit allow-lists may answer
anything but 401/403. A new route that forgets its permission fails here."""

import uuid

import pytest
from django.urls import URLResolver, get_resolver

# Reachable without signing in (sign-up, sign-in, CSRF, probes, docs). Docs are off in production.
PUBLIC = {
    "api/health/",
    "api/auth/csrf/",
    "api/auth/signup/",
    "api/auth/user/login/",
    "api/auth/user/refresh/",
    "api/auth/user/logout/",
    "api/admin/login/",
    "api/admin/logout/",
    "api/schema/",
    "api/docs/",
}
# A member may use only their own profile; everything else under /api/ is admin-only.
MEMBER = {"api/profiles/me/"}
DUMMY = {"int": "1", "uuid": str(uuid.uuid4())}


def routes():
    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern), p.callback

    for route, callback in walk(get_resolver().url_patterns):
        if route.startswith("api/"):
            yield route, callback


def concrete(route):
    out = route
    for conv, value in DUMMY.items():
        while f"<{conv}:" in out:
            start = out.index(f"<{conv}:")
            out = out[:start] + value + out[out.index(">", start) + 1 :]
    return "/" + out


def methods(callback):
    cls = getattr(callback, "cls", None)
    if cls is None:
        return ["get"]
    return [m for m in ("get", "post", "put", "patch", "delete") if hasattr(cls, m)]


CASES = [(route, m) for route, cb in routes() for m in methods(cb)]


def call(client, route, method, headers=None):
    return getattr(client, method)(concrete(route), {}, format="json", **(headers or {}))


def test_matrix_covers_every_api_route():
    assert len({r for r, _ in CASES}) >= 35
    assert PUBLIC | MEMBER <= {r for r, _ in CASES}


@pytest.mark.django_db
@pytest.mark.parametrize("route, method", [c for c in CASES if c[0] not in PUBLIC], ids=lambda v: str(v))
def test_anonymous_is_refused(route, method):
    from rest_framework.test import APIClient

    assert call(APIClient(), route, method).status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.parametrize("route, method", [c for c in CASES if c[0] not in PUBLIC | MEMBER], ids=lambda v: str(v))
def test_member_is_refused_admin_routes(user_browser, route, method):
    # The CSRF header is sent, so a 403 here is the permission check, not a missing token.
    response = call(user_browser.client, route, method, user_browser._csrf_headers())
    assert response.status_code in (401, 403)
    body = response.json() if response.get("Content-Type", "").startswith("application/json") else {}
    assert body.get("error", {}).get("code") != "csrf_failed"
