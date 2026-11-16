"""Regression tests for the unified JSON error envelope.

Bug history: the first version of `api_exception_handler` read `exc.detail` unconditionally.
Django's `Http404` (raised by `get_object_or_404`) has no `.detail`, so every unknown-id request
returned an HTML 500 instead of a JSON 404. Found by test_deactivate_unknown_profile_is_404.
"""

import pytest


@pytest.mark.django_db
class TestErrorEnvelope:
    def test_get_object_or_404_returns_json_404_not_500(self, admin_browser):
        resp = admin_browser.post("/api/admin/profiles/99999/deactivate/")
        assert resp.status_code == 404
        assert resp["Content-Type"] == "application/json"
        assert resp.json()["error"]["code"] == "not_found"

    def test_unknown_route_returns_json_404(self, browser):
        resp = browser.get("/api/definitely/not/here/")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"

    def test_every_error_has_code_message_details(self, browser):
        for resp in (browser.get("/api/profiles/me/"), browser.post("/api/auth/signup/", {})):
            err = resp.json()["error"]
            assert set(err) == {"code", "message", "details"}

    def test_method_not_allowed_uses_envelope(self, browser):
        resp = browser.get("/api/auth/signup/")
        assert resp.status_code == 405
        assert resp.json()["error"]["code"] == "method_not_allowed"
