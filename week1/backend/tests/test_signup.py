import pytest

from accounts.models import User
from profiles.models import HealthProfile

from .conftest import PASSWORD

URL = "/api/auth/signup/"
VALID = {"name": "Maya Example", "email": "maya@example.test", "password": PASSWORD}


@pytest.mark.django_db
class TestSignup:
    def test_valid_signup_creates_user_and_profile(self, browser):
        resp = browser.post(URL, VALID)
        assert resp.status_code == 201
        user = User.objects.get(email="maya@example.test")
        assert user.role == User.Role.USER
        assert HealthProfile.objects.get(user=user).full_name == "Maya Example"

    def test_response_never_contains_password_or_hash(self, browser):
        body = browser.post(URL, VALID).content.decode()
        assert PASSWORD not in body and "password" not in body and "pbkdf2" not in body and "argon2" not in body

    def test_password_is_hashed_not_stored_in_plaintext(self, browser):
        browser.post(URL, VALID)
        user = User.objects.get(email="maya@example.test")
        assert user.password != PASSWORD
        assert user.password.startswith("md5$")  # test hasher; production uses Argon2 (see settings)
        assert user.check_password(PASSWORD)

    def test_email_is_normalised_to_lowercase(self, browser):
        browser.post(URL, {**VALID, "email": "  MAYA@Example.TEST "})
        assert User.objects.filter(email="maya@example.test").exists()

    def test_duplicate_email_rejected_case_insensitively(self, browser, user):
        resp = browser.post(URL, {**VALID, "email": user.email.upper()})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "validation_error"
        assert "email" in resp.json()["error"]["details"]
        assert User.objects.filter(email=user.email).count() == 1

    @pytest.mark.parametrize(
        "payload, field",
        [
            ({**VALID, "email": "not-an-email"}, "email"),
            ({**VALID, "email": ""}, "email"),
            ({**VALID, "name": "A"}, "name"),
            ({**VALID, "name": ""}, "name"),
            ({**VALID, "password": "short1!"}, "password"),
            ({**VALID, "password": "1234567890123"}, "password"),  # numeric only
            ({**VALID, "password": "password1234"}, "password"),  # common
            ({**VALID, "password": "maya@example.test"}, "password"),  # similar to email
        ],
    )
    def test_invalid_input_is_rejected_with_field_errors(self, browser, payload, field):
        resp = browser.post(URL, payload)
        assert resp.status_code == 400
        assert field in resp.json()["error"]["details"]
        assert User.objects.count() == 0

    def test_missing_fields(self, browser):
        resp = browser.post(URL, {})
        assert resp.status_code == 400
        assert {"name", "email", "password"} <= set(resp.json()["error"]["details"])

    def test_cannot_self_register_as_admin(self, browser):
        browser.post(URL, {**VALID, "role": "admin", "is_staff": True, "is_superuser": True})
        user = User.objects.get(email="maya@example.test")
        assert user.role == User.Role.USER and not user.is_admin

    def test_no_public_admin_signup_endpoint_exists(self, browser):
        for path in ("/api/admin/signup/", "/api/admin/register/", "/api/auth/admin/signup/"):
            assert browser.post(path, VALID).status_code == 404

    def test_csrf_token_required(self, browser):
        resp = browser.post(URL, VALID, csrf=False)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "csrf_failed"
        assert User.objects.count() == 0
